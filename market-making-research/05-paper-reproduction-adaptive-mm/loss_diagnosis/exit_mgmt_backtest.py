"""库存管理改版回测(用户 2026-11-09 原话:"库存管理改成成交之后以成交概率最高的方式报价回测,60s之后没有成交的按照原库存管理 进行回测")。
对象  XBTUSDCM,P1 原论文 g3 目录,Δt = 2000 ms,每侧 V_LO = 74 张,l3sim 精确排队、post-only、延迟 1.8 ms,10 月 9 个测试日。
三组同场回放(引擎里 agent 之间互不分量,同一天同一簿):
  P1_orig   对照组:原 P1(目录报价 + A1·I 倾斜,无平仓)。用来与 2026-11-09 P0 的 P1 2000 ms 结果逐日对账。
  EXIT_A    每笔成交记为一批库存(先进先出;反向成交按先进先出冲掉旧批)。成交后 60 s 内的批次合计量,在平仓方向挂一张"成交概率最高"的出场单:
            点差 ≥ 2 tick 时比本侧最优价改善 1 tick,点差 = 1 tick 时加入最优价;目标价或应挂量一变就先撤、撤单生效后重挂(跟盘口)。
            满 60 s 还没冲掉的批次不再进出场单,回到原库存管理(目录报价的 A1·I 倾斜)。目录的双边报价照常保留(平仓方向同时有目录单和出场单)。
  EXIT_B    同 EXIT_A,但平仓方向有 60 s 内批次时,把该方向的目录报价撤掉(只留出场单);批次满 60 s 或出完后目录报价恢复。
  A / B 的区别是用户原话没说清的一处(出场单挂出去时同侧目录报价留不留),两种都跑,由用户选。
PnL  不含返佣 = W + I × 日末 L3 中价(与 Table 8 l3sim 列同口径);返佣 = OUR_FEE bp × 成交张数 × 日末中价;总 = 两者之和。
用法  python exit_mgmt_backtest.py <day> [hours]   单日;python exit_mgmt_backtest.py all [par]  9 天子进程并行
输出  out/P1_dt2000_XBTUSDCM/exit_mgmt/<day>_<agent>.npz(fills、records、W、I、lots 日志)与 <day>_summary.json
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time

import numpy as np

ROOT = r"主动做市策略"; REPRO = os.path.join(ROOT, "repro")
for p in (os.path.join(REPRO, "sim_l3"), os.path.join(REPRO, "a"), os.path.join(REPRO, "b")):
    sys.path.insert(0, p)
SYM = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--sym=")), os.environ.get("EXIT_SYM", "XBTUSDCM"))   # 2026-11-09 用户:"btcusdt也跑一下";detach(WMI)不继承环境变量,用 --sym=
V_LO = {"XBTUSDCM": 74, "XBTUSDTM": 24}[SYM]                # reports/step00/vlo.md
MULT = {"XBTUSDCM": 0.0001, "XBTUSDTM": 0.001}[SYM]
REB = {"XBTUSDCM": OUR_FEE, "XBTUSDTM": 0.7e-4}[SYM]           # 我方费率档 maker 返佣(contracts.yaml)
DT, LAT = 2000, 1.8
OUT = os.path.join(ROOT, "loss_diagnosis", "out", f"P1_dt2000_{SYM}", "exit_mgmt"); os.makedirs(OUT, exist_ok=True)
HOLD_NS, NS = 60 * 1_000_000_000, 1_000_000_000
DAYS = ["20261001", "20261002", "20261013", "20261014", "20261015", "20261016", "20261017", "20261018", "20261019"]
FLAGS = 0x08000000 | 0x00004000


def make_agents(cat, g, day0):
    import agents as AG

    class ExitAgent(AG.PaperPolicyAgent):
        def __init__(self, name, variant, *a, **kw):
            super().__init__(name, *a, **kw)
            self.variant = variant
            self.lots = []              # [sign(+1 多 / −1 空), 剩余张数, 开仓时刻]
            self.exit = None            # 当前出场单
            self.exit_log = []          # (ts, 张数) 出场单成交
            self.revert_log = []        # (ts, 张数) 满 60 s 回到原库存管理的批次量
            self._reverted = set()

        # ---- 批次账
        def _book_lot(self, sign, qty, ts):
            left = qty
            while left > 0 and self.lots and self.lots[0][0] == -sign:      # 反向成交:先进先出冲掉旧批
                take = min(left, self.lots[0][1]); self.lots[0][1] -= take; left -= take
                if self.lots[0][1] == 0:
                    self.lots.pop(0)
            if left > 0:
                self.lots.append([sign, left, ts])

        def _young(self, ts):
            if not self.lots:
                return 0, None
            q = 0
            for lot in self.lots:
                if ts - lot[2] < HOLD_NS:
                    q += lot[1]
                elif id(lot) not in self._reverted:
                    self._reverted.add(id(lot)); self.revert_log.append((ts, lot[1]))
            return q, (1 if self.lots[0][0] > 0 else 0)    # 多头 → 卖出平仓(引擎 side 1)

        def on_fill(self, sim, o, qty, ts, sweep_qty):
            super().on_fill(sim, o, qty, ts, sweep_qty)
            self._book_lot(1 if o.side == 0 else -1, qty, ts)
            if o is self.exit:
                self.exit_log.append((ts, qty))

        def on_break(self, sim, ts):
            super().on_break(sim, ts)
            if self.exit is not None and self.exit.state in ("pending", "live"):
                self.exit.state = "lost"
            self.exit = None

        def _requote(self, sim, ts, side, tick):
            if self.variant == "B":
                q, es = self._young(ts)
                if q > 0 and side == es:                     # 平仓方向有 60 s 内批次:不挂目录单
                    o = self.live[side]
                    if o is not None and o.state in ("pending", "live") and o.cancel_at is None:
                        sim.cancel(o, ts); self._close(o, "canceled")
                    self.live[side] = None
                    return
            super()._requote(sim, ts, side, tick)

        def on_event(self, sim, ts):
            super().on_event(sim, ts)
            if self.next_bnd is None:
                return
            bb, ba = sim.best(0), sim.best(1)
            if bb is None or ba is None or ba <= bb:
                return
            q, es = self._young(ts)
            if self.variant == "B" and q > 0:
                o = self.live[es]
                if o is not None and o.state in ("pending", "live") and o.cancel_at is None:
                    sim.cancel(o, ts); self._close(o, "canceled"); self.live[es] = None
            e = self.exit
            if e is not None and e.state in ("pending", "live"):
                if q == 0 or e.side != es:
                    if e.cancel_at is None:
                        sim.cancel(e, ts)
                    return
                tgt = (bb + 1 if es == 1 else ba - 1) if ba - bb >= 2 else (ba if es == 1 else bb)
                if (e.tick != tgt or e.left != q) and e.cancel_at is None:
                    sim.cancel(e, ts)
                return                                       # 先撤后挂:撤单生效前不挂新单
            if q <= 0:
                self.exit = None
                return
            tgt = (bb + 1 if es == 1 else ba - 1) if ba - bb >= 2 else (ba if es == 1 else bb)
            self.exit = sim.place(self, es, tgt, q, ts, tag=f"{self.name}:exit")

    a0 = AG.PaperPolicyAgent("P1_orig", cat, g, V_LO, DT, day0, lat_ms=LAT)
    aA = ExitAgent("EXIT_A", "A", cat, g, V_LO, DT, day0, lat_ms=LAT)
    aB = ExitAgent("EXIT_B", "B", cat, g, V_LO, DT, day0, lat_ms=LAT)
    return [a0, aA, aB]


def run_day(day, hours=None):
    import engine_bridge as B
    import arrivals as AR
    import step06_catalog as S6
    import step14_run as S14
    L, E = B.L, B.E
    B.patch_engine(SYM)
    day0 = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    g = AR.GState("g3")
    cat, _ = S6.load_catalog(os.path.join(REPRO, "data", "step06", SYM, "base", f"dt{DT}", f"{day}_g3.npz"))
    ags = make_agents(cat, g, day0)
    for a in ags:
        a.lat = L.Latency(fixed_ms=LAT)
    hours = hours or E.hours_of(day, SYM)
    disp = S14.Dispatcher(ags, record_bbo=True)
    sim = L.L3Sim(SYM, L.Latency(fixed_ms=LAT), ags, recorder=disp, trade_ticks=E.P.load_trade_ticks(day, hours, SYM))
    t = time.time()
    E.run_hours(sim, day, hours, prewarm_s=300)
    mid_end = disp.bbo_mid2[-1] / 2.0
    unit = 0.1 * MULT
    out = {}
    for a in ags:
        fl = np.asarray(a.fills, np.int64).reshape(-1, 10); qty = int(fl[:, 3].sum()) if len(fl) else 0
        gross = (a.W + a.I * mid_end) * unit; reb = REB * mid_end * qty * unit
        ex = np.asarray(getattr(a, "exit_log", []), np.int64).reshape(-1, 2); rv = np.asarray(getattr(a, "revert_log", []), np.int64).reshape(-1, 2)
        np.savez_compressed(os.path.join(OUT, f"{day}_{a.name}.npz"), fills=fl, records=np.asarray(a.records, np.int64).reshape(-1, 10), W=a.W, I=a.I, exit_log=ex, revert_log=rv,
                            lots_end=np.asarray(getattr(a, "lots", []), np.int64).reshape(-1, 3))
        out[a.name] = dict(fills=int(len(fl)), qty=qty, notional=float((fl[:, 2] * fl[:, 3]).sum() * unit) if len(fl) else 0.0, gross=gross, rebate=reb, total=gross + reb,
                           I_end=a.I, exit_fill_qty=int(ex[:, 1].sum()) if len(ex) else 0, reverted_qty=int(rv[:, 1].sum()) if len(rv) else 0, breaks=a.n_breaks)
    np.savez_compressed(os.path.join(OUT, f"{day}_bbo.npz"), ts=np.asarray(disp.bbo_ts, np.int64), mid2=np.asarray(disp.bbo_mid2, np.int64))
    with open(os.path.join(OUT, f"{day}_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    for k, v in out.items():
        print(f"{day} {k}: 成交 {v['fills']:,} 笔 {v['qty']:,} 张 ${v['notional']:,.0f} | 不含返佣 {v['gross']:+.1f} 返佣 {v['rebate']:+.1f} 总 {v['total']:+.1f} USDC | 日末 I {v['I_end']:+.0f} | "
              f"出场单成交 {v['exit_fill_qty']:,} 张 | 满 60 s 回原库存管理 {v['reverted_qty']:,} 张", flush=True)
    print(f"{day} 用时 {(time.time() - t) / 60:.1f} min", flush=True)


def run_all(par):
    py = sys.executable; running, jobs = [], list(DAYS)
    while jobs or running:
        while jobs and len(running) < par:
            d = jobs.pop(0); fh = open(os.path.join(OUT, f"{d}_run.log"), "w", encoding="utf-8")
            running.append((d, subprocess.Popen([py, "-X", "utf8", "-W", "ignore", __file__, d, f"--sym={SYM}"], stdout=fh, stderr=subprocess.STDOUT, creationflags=FLAGS), fh))
            print(f"[start] {d} {time.strftime('%H:%M')}", flush=True)
        time.sleep(10)
        for x in running[:]:
            if x[1].poll() is not None:
                x[2].close(); running.remove(x); print(f"[end] {x[0]} rc={x[1].returncode} {time.strftime('%H:%M')}", flush=True)
    print("EXIT_MGMT_DONE", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "all":
        par = [a for a in sys.argv[2:] if not a.startswith("--")]
        run_all(int(par[0]) if par else 3)
    else:
        hrs = [a for a in sys.argv[2:] if not a.startswith("--")]
        run_day(sys.argv[1], hrs[0].split(",") if hrs else None)
