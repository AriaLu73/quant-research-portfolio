"""出场探针(用户 2026-11-09:"成交之后 10–60 s 内用 maker 单出去的概率有多大(不考虑赚了多少价差,只考虑可以成交),按成交概率最大的计算报价")。
对象  XBTUSDCM,P1 原论文目录 Δt = 2000 ms 在 l3sim 里的 17,288 笔 maker 成交(loss_diagnosis/out/P1_dt2000_XBTUSDCM/fills_attributed.csv)。
做法  重放同一天的 L3,不放 P1 策略,只放"出场探针":每笔成交在其成交时刻(交易所钟)发一张反方向、同张数的 post-only 限价单,
      引擎延迟 1.8 ms(与 P1 回放同口径),按 L3 精确排队判定成交(引擎 scripts/research7/l3sim.py,价格优先、时间优先、前方撤单、部分成交)。
报价规则(执行者对"按成交概率最大的计算报价"的理解,用户没说过具体规则):
      挂在不穿价前提下最激进的价位 —— 点差 ≥ 2 tick 时比本侧最优价改善 1 tick(新最优价、前方 0);点差 = 1 tick 时加入本侧最优价排队。
      任何时刻这个目标价变了(盘口移动)就先撤单、撤单生效后按新目标价重挂剩余量(跟盘口,排队位置重来)。
      持续到全部成交或满 60 s;60 s 未成交完的剩余量记为未出场(探针撤掉)。
独立性 每笔成交的探针各自独立(引擎里每个探针一个 agent,agent 之间互不分量 —— l3sim 类注释"多个互不影响的策略");
      探针之间、探针与 P1 自己的其它挂单之间不排队竞争。这是上界口径:真实里同时出场的多张单会互相排队。
因子  同一遍重放记录全部吃单(match):时间、吃单单号、吃单方向、吃单限价(L3 match 的 price)、成交价(公开成交流 tradeId → tick),
      离线按因子库 own_taker_limit_slack(rdagent_local/data/three/results/own_taker_limit_slack.py,fill1s 入库)的原公式在探针发出时刻计算。
断流  探针存活期间遇到断流,标记 interrupted,不进概率统计。日末数据结束时未满 60 s 的,标记 censored。
用法  python exit_probe_run.py <day>      → out/P1_dt2000_XBTUSDCM/exit_probe/<day>_probes.csv、<day>_takers.npz
      python exit_probe_run.py all [par]  → 9 天子进程并行(BelowNormal、不弹窗)
不是策略回测:不改 P1、不恢复 11-09 挂起的 Step 12 进程。
"""
import heapq
import os
import subprocess
import sys
import time

import numpy as np
import pandas as pd

ROOT = r"主动做市策略"
REPRO = os.path.join(ROOT, "repro")
sys.path.insert(0, os.path.join(REPRO, "sim_l3"))
OUT = os.path.join(ROOT, "loss_diagnosis", "out", "P1_dt2000_XBTUSDCM", "exit_probe"); os.makedirs(OUT, exist_ok=True)
SYM, LAT_MS, HOLD_NS = "XBTUSDCM", 1.8, 60 * 1_000_000_000
DAYS = ["20261001", "20261002", "20261013", "20261014", "20261015", "20261016", "20261017", "20261018", "20261019"]
FLAGS = 0x08000000 | 0x00004000


class Slot:
    """一个探针一个 agent(引擎里 agent 之间互不分量)。"""
    def __init__(self, pid):
        self.pid, self.orders, self.filled, self.fill_log = pid, [], 0, []
        self.broken = False

    def on_event(self, sim, ts):
        pass

    def on_fill(self, sim, o, qty, ts, sweep_qty):
        self.filled += qty
        self.fill_log.append((ts, o.tick, qty))

    def on_break(self, sim, ts):
        self.broken = True


class Manager:
    def __init__(self, fills, L):
        self.L = L
        self.queue = [(int(r.ts), i) for i, r in fills.iterrows()]       # (开始时刻, 行号)
        heapq.heapify(self.queue)
        self.fills = fills
        self.active = {}            # pid → dict(state)
        self.done = []
        self.orders = []
        self.sim = None
        self._last_bbo = None

    def on_fill(self, *a):
        pass

    def on_break(self, sim, ts):
        pass

    def target(self, es, bb, ba):
        if ba - bb >= 2:
            return bb + 1 if es == 1 else ba - 1, "improve"
        return (ba if es == 1 else bb), "join"

    def _finish(self, sim, pid, ts, reason):
        st = self.active.pop(pid)
        slot = st["slot"]
        for o in slot.orders:
            if o.state in ("pending", "live"):
                sim.cancel(o, ts)
        fl = slot.fill_log
        q = st["qty"]
        cum, t_full, t_first, vw = 0, None, None, 0.0
        for t, tk, f in fl:
            if t_first is None:
                t_first = t
            take = min(f, q - cum)
            if take <= 0:
                break
            vw += tk * take; cum += take
            if cum >= q and t_full is None:
                t_full = t
        self.done.append(dict(row=st["row"], start_ts=st["start"], exit_side=st["es"], qty=q, filled_qty=cum, first_fill_ts=t_first, full_fill_ts=t_full,
                              exit_vwap_tick=(vw / cum) if cum else np.nan, n_place=st["n_place"], n_repeg=st["n_repeg"], first_mode=st["first_mode"],
                              first_ahead0=st["first_ahead0"], spread0=st["spread0"], interrupted=slot.broken, end_reason=reason))
        # 下一条消息起这个 slot 不再参与(重建列表,不在遍历中原地修改)
        sim.agents = [a for a in sim.agents if a is not slot]

    def on_event(self, sim, ts):
        bb, ba = sim.best(0), sim.best(1)
        if bb is None or ba is None or ba <= bb:
            return
        # 1) 到时的新探针
        while self.queue and self.queue[0][0] <= ts:
            t0, i = heapq.heappop(self.queue)
            r = self.fills.iloc[i]
            es = 0 if r.side > 0 else 1                       # 我方卖成交(side +1)→ 空头 → 买入出场(引擎 side 0)
            slot = Slot(i)
            sim.agents = sim.agents + [slot]
            self.active[i] = dict(row=int(r.row_id), start=t0, es=es, qty=int(r.qty), slot=slot, cur=None, n_place=0, n_repeg=0,
                                  first_mode=None, first_ahead0=None, spread0=ba - bb, deadline=t0 + HOLD_NS)
        # 2) 推进全部活探针
        for pid in list(self.active):
            st = self.active[pid]; slot = st["slot"]
            if slot.filled >= st["qty"]:
                self._finish(sim, pid, ts, "filled"); continue
            if ts >= st["deadline"]:
                self._finish(sim, pid, ts, "timeout"); continue
            o = st["cur"]
            tgt, mode = self.target(st["es"], bb, ba)
            if o is not None and o.state in ("pending", "live"):
                if o.tick != tgt and o.cancel_at is None:
                    sim.cancel(o, ts); st["n_repeg"] += 1
                if st["first_ahead0"] is None and o.state == "live":
                    st["first_ahead0"] = o.ahead0
                continue                                     # 撤单生效前不重挂(先撤后挂)
            left = st["qty"] - slot.filled
            if left <= 0:
                continue
            st["cur"] = sim.place(slot, st["es"], tgt, left, ts, tag=f"exit{pid}")
            st["n_place"] += 1
            if st["first_mode"] is None:
                st["first_mode"] = mode


def run_day(day):
    import engine_bridge as B
    L, E = B.L, B.E
    B.patch_engine(SYM)
    F = pd.read_csv(os.path.join(ROOT, "loss_diagnosis", "out", "P1_dt2000_XBTUSDCM", "fills_attributed.csv"), dtype={"day": str})
    F["row_id"] = np.arange(len(F))
    fills = F[F.day == day].reset_index(drop=True)
    takers = []

    class Sim(L.L3Sim):
        def _on_match(self, d, seq, ts):
            tt = self.trade_ticks.get(d.get("tradeId"))
            if tt is None:
                o = self.book.get(d["makerOrderId"]); tt = o[1] if o is not None else -1
            try:
                tp = float(d.get("price") or 0.0)
            except ValueError:
                tp = 0.0
            takers.append((ts, d["takerOrderId"], 1 if d["side"] == "buy" else -1, tp, tt, int(d["size"])))
            return super()._on_match(d, seq, ts)

    hours = E.hours_of(day, SYM)
    if os.environ.get("PROBE_HOURS"):                       # 冒烟用:只跑指定小时
        hours = os.environ["PROBE_HOURS"].split(",")
        fills = fills[(fills.ts // 3_600_000_000_000 % 24).astype(int).astype(str).str.zfill(2).isin(hours)].reset_index(drop=True)
        mgr_suffix = "_smoke"
    else:
        mgr_suffix = ""
    mgr = Manager(fills, L)
    sim = Sim(SYM, L.Latency(fixed_ms=LAT_MS), [mgr], recorder=None, trade_ticks=E.P.load_trade_ticks(day, hours, SYM))
    t = time.time()
    E.run_hours(sim, day, hours, prewarm_s=300)
    for pid in list(mgr.active):                             # 数据结束时还活着的:截尾
        mgr._finish(sim, pid, sim._ts, "censored")
    P = pd.DataFrame(mgr.done).sort_values("row")
    P.to_csv(os.path.join(OUT, f"{day}_probes{mgr_suffix}.csv"), index=False)
    T = np.array([(a, b, c, e, f) for a, _, b, c, e, f in [(x[0], None, x[2], x[3], x[4], x[5]) for x in takers]], dtype=float) if takers else np.zeros((0, 5))
    oid = np.array([x[1] for x in takers])
    np.savez_compressed(os.path.join(OUT, f"{day}_takers{mgr_suffix}.npz"), ts=T[:, 0].astype(np.int64), d=T[:, 1].astype(np.int8), taker_px=T[:, 2], fill_tick=T[:, 3].astype(np.int64),
                        size=T[:, 4].astype(np.int64), oid=oid)
    print(f"{day}: 探针 {len(P):,}(成交 {int((P.end_reason == 'filled').sum()):,}、超时 {int((P.end_reason == 'timeout').sum()):,}、截尾 {int((P.end_reason == 'censored').sum()):,}、"
          f"断流 {int(P.interrupted.sum()):,});吃单记录 {len(takers):,};用时 {(time.time() - t) / 60:.1f} min", flush=True)


def run_all(par):
    py = sys.executable; running, jobs = [], list(DAYS)
    while jobs or running:
        while jobs and len(running) < par:
            d = jobs.pop(0)
            fh = open(os.path.join(OUT, f"{d}_run.log"), "w", encoding="utf-8")
            running.append((d, subprocess.Popen([py, "-X", "utf8", "-W", "ignore", __file__, d], stdout=fh, stderr=subprocess.STDOUT, creationflags=FLAGS), fh))
            print(f"[start] {d} {time.strftime('%H:%M')}", flush=True)
        time.sleep(10)
        for x in running[:]:
            if x[1].poll() is not None:
                x[2].close(); running.remove(x); print(f"[end] {x[0]} rc={x[1].returncode} {time.strftime('%H:%M')}", flush=True)
    print("EXIT_PROBE_DONE", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "all":
        run_all(int(sys.argv[2]) if len(sys.argv) > 2 else 2)
    else:
        run_day(sys.argv[1])
