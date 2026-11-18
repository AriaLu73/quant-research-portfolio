#!/usr/bin/env python3
"""research7 阶段 0 验收:2026-10-02 实盘订单 对 同期逐笔委托回放(预登记见 docs/research7/00_范围_阈值_预登记.md 第 4 节)。

用途      把我方 10-02 18:49–21:22 UTC 的真实订单(BTC-USDC 报价单、BTC-USDT 对冲单)从公开逐笔委托流里拿掉,
          换成仿真订单重放,比较"实盘成交了哪些"与"仿真判定成交了哪些"。只读;不连接交易所。
所属阶段  阶段 0。不属于任何研究模块,不对应报价公式中的某一项。
两种重放
  T0-1 actual  仿真订单的进簿时刻 = 交易所公开流里我方订单 open 的那一条;撤单时刻 = 公开流里 done(canceled) 的那一条。
               检验排队规则本身(假设 H1、H2):真实成交必须全部复现,且不得多出成交。
  T0-2 model   进簿时刻 = 引擎发单时刻 + 延迟模型;撤单生效 = 引擎发撤单时刻 + 延迟模型。检验延迟模型(假设 H3)。
               这里的起点是"引擎已经发出",所以延迟只算下单段:正常 1.5 ms、拥堵 49.7 ms
               (= 用户裁决的总延迟 1.8 / 50 ms 减去行情段 0.3 ms;来源 memory latency-figures-authoritative)。
变量与 <符号表> 的对应
          ε = +1 买入成交、−1 卖出成交;P 成交价;m_0 成交时刻中间价;m_h 成交后 h 的中间价;
          markout(h) = ε (m_h − m_0) / m_0 × 1e4(bp);成交时优势 = ε (m_0 − P) / m_0 × 1e4(bp)
用法      .venv/Scripts/python.exe scripts/research7/live_recon.py run <XBTUSDCM|XBTUSDTM>
          .venv/Scripts/python.exe scripts/research7/live_recon.py report
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l3sim as L
import l3_prep as P

JOURNAL = os.path.join(L.ROOT, "data", "research5", "live_20261002", "trade_events.jsonl")
OUT = os.path.join(P.OUT, "live_recon")
DAY, HOURS = "20261002", ("18", "19", "20", "21")
SYM_OF = {"BTC-USDC": "XBTUSDCM", "BTC-USDT": "XBTUSDTM"}
LOOK_NS = 100 * L.MS      # 提前这么久把"将要发出的订单"交给仿真器排队(只是实现细节:进簿时刻仍按发单时刻 + 延迟计算)
MARKOUT_S = (1, 10)       # 预登记 4.1:1 秒、10 秒
N_SEEDS = 20              # T0-2b 的随机数种子个数(ASSUMPTION:20 个足以把抽样造成的标准误压到成交笔数标准差的 1/4.5)


def read_journal(sym):
    """读实盘总线日志(已解码的 jsonl)。返回 {引擎订单号: 订单字典},只含 sym 的订单。
    字段:side(0 买 1 卖)、tick、size(张)、t_send(引擎发单,纳秒,我方时钟)、ex_id(交易所订单号)、
          t_cancel(引擎发撤单,纳秒,无则 None)、fills [(交易所时间纳秒, 张数, 成交 tick, 是否挂单方)]、rejected。
    时钟:我方机器用 Amazon Time Sync,与 KuCoin 时钟的差实测 −0.04 ms(不确定度约 ±0.8 ms;
          docs/research5/experiments.md 2026-10-06 两所时钟差实测)。这里不做校正,误差计入 T0-2 的不确定性。"""
    mult = L.MULT[sym]
    od = {}
    with open(JOURNAL, encoding="utf8") as fh:
        for line in fh:
            r = json.loads(line)
            m = r["msg"]
            if SYM_OF.get(m.get("symbol")) != sym:
                continue
            oid = m.get("order_id", "")
            if r["type"] == "Order":
                od[oid] = dict(side=0 if m["side"] == "buy" else 1, tick=L.to_tick(m["price"]),
                               size=int(round(float(m["quantity"]) / mult)),      # 单位换算:BTC → 张
                               t_send=r["ts_ns"], ex_id=None, t_cancel=None, fills=[], rejected=False)
            elif oid in od:
                o = od[oid]
                if r["type"] == "OrderReport":
                    if m.get("exchange_order_id"):
                        o["ex_id"] = m["exchange_order_id"]
                    if m["status"] == "rejected":
                        o["rejected"] = True
                elif r["type"] == "KVGroup":
                    o["t_cancel"] = o["t_cancel"] or r["ts_ns"]
                elif r["type"] == "Fill":
                    o["fills"].append((m["ts_ns"], int(round(float(m["quantity"]) / mult)), L.to_tick(m["price"]), bool(m["is_maker"])))
    return od


class Replay:
    """把实盘订单放进仿真器的策略。mode = "actual"(T0-1)或 "model"(T0-2)。"""

    def __init__(self, od, mode, lat=None):
        self.od, self.mode, self.orders, self.lat = od, mode, [], lat
        self.sim_of = {}                                   # 引擎订单号 → SimOrder
        self.by_ex = {o["ex_id"]: k for k, o in od.items() if o["ex_id"]}
        self.sends = sorted((o["t_send"], k) for k, o in od.items())
        self.cancels = sorted((o["t_cancel"], k) for k, o in od.items() if o["t_cancel"])
        self.i = self.j = 0
        self.skipped = set()                               # 落在预热 / 断流期间、无法评估的订单
        self.got = []                                      # (引擎订单号, 交易所时间, 张数)

    # --- T0-1:进簿与撤单都取自交易所的真实记录
    def on_own_open(self, sim, ex_id, ts):
        k = self.by_ex.get(ex_id)
        if self.mode != "actual" or k is None:
            return
        if not sim.ready:
            self.skipped.add(k)
            return
        o = self.od[k]
        self.sim_of[k] = sim.rest_now(self, o["side"], o["tick"], o["size"], k)

    def on_own_done(self, sim, ex_id, reason, ts):
        so = self.sim_of.get(self.by_ex.get(ex_id))
        if self.mode == "actual" and so is not None and reason != "filled" and so.state == "live":
            so.state = "cancelled"

    # --- T0-2:进簿与撤单按延迟模型
    def on_event(self, sim, ts):
        if self.mode != "model":
            return
        while self.i < len(self.sends) and self.sends[self.i][0] <= ts + LOOK_NS:
            t, k = self.sends[self.i]
            self.i += 1
            o = self.od[k]
            if t < ts:                                     # 发单时刻已过(预热 / 断流刚结束):不评估
                self.skipped.add(k)
            else:
                self.sim_of[k] = sim.place(self, o["side"], o["tick"], o["size"], t, k)
        while self.j < len(self.cancels) and self.cancels[self.j][0] <= ts + LOOK_NS:
            t, k = self.cancels[self.j]
            self.j += 1
            if k in self.sim_of:
                sim.cancel(self.sim_of[k], t)

    def on_fill(self, sim, o, qty, ts, sweep_qty):
        self.got.append((o.tag, ts, qty))

    def on_break(self, sim, ts):
        for k, so in self.sim_of.items():
            if so.state == "lost":
                self.skipped.add(k)


def run(sym):
    od = read_journal(sym)
    own = {o["ex_id"]: (o["side"], o["tick"]) for o in od.values() if o["ex_id"]}
    a1, a2 = Replay(od, "actual"), Replay(od, "model")
    # T0-2b:实测延迟分布(按负载分档抽样),N_SEEDS 个随机数种子各跑一遍,看成交笔数的均值与离散
    table = np.load(os.path.join(P.OUT, "latency_empirical.npz"))
    emp = [Replay(od, "model", L.EmpiricalLatency(P.Load(), table, lead_ms=0.0, seed=s)) for s in range(N_SEEDS)]
    rec = P.Recorder()
    # T0-2 的延迟:起点是引擎发单时刻,只算下单段(见文件头)
    lat = L.Latency(load=P.Load(), normal_ms=1.5, busy_ms=49.7)
    sim = L.L3Sim(sym, lat, [a1, a2] + emp, recorder=rec, own_ids=own, trade_ticks=P.load_trade_ticks(DAY, HOURS, sym))
    sim.run(DAY, HOURS)
    os.makedirs(OUT, exist_ok=True)
    res = dict(sym=sym, breaks=sim.breaks, n_orders=len(od), paired_n=sim.paired_n, paired_qty=sim.paired_qty, orders={})
    for k, o in od.items():
        row = dict(side=o["side"], tick=o["tick"], size=o["size"], t_send=o["t_send"], rejected=o["rejected"],
                   real=[f for f in o["fills"]])
        for name, ag in [("actual", a1), ("model", a2)] + [(f"emp{i}", e) for i, e in enumerate(emp)]:
            so = ag.sim_of.get(k)
            row[name] = None if (so is None or k in ag.skipped) else dict(
                state=so.state, fills=so.fills, ahead0=so.ahead0, level0=so.level0, rest_at=so.rest_at)
        res["orders"][k] = row
    json.dump(res, open(os.path.join(OUT, f"{sym}.json"), "w"))
    np.save(os.path.join(OUT, f"{sym}_bbo.npy"), np.asarray(rec.bbo, np.int64).reshape(-1, 5))
    print(f"{sym}: 订单 {len(od):,}  断流 {sim.breaks}  成对打印 {sim.paired_n} 笔 / {sim.paired_qty} 张  RECON_RUN_DONE", flush=True)


def mid_at(bbo, t):
    """t(纳秒,数组)时刻的中间价(美元):取 t 之前最后一次买一卖一变化,不用未来数据。"""
    i = np.searchsorted(bbo[:, 0], t, side="right") - 1
    ok = i >= 0
    i = np.clip(i, 0, len(bbo) - 1)
    return np.where(ok, (bbo[i, 1] + bbo[i, 2]) / 2.0 * L.TICK, np.nan)


def stats(rows, bbo, key):
    """key = "real" / "actual" / "model"。返回 成交订单数、成交张数、每笔的 [成交时优势, markout 1 s, markout 10 s](bp)。"""
    n_f, q, per = 0, 0, []
    for k, r in rows:
        fl = [(f[0], f[1], f[2]) for f in r["real"] if f[3]] if key == "real" else [(t, f, r["tick"]) for t, f in r[key]["fills"]]
        if not fl:
            continue
        n_f += 1
        for t, f, tick in fl:
            q += f
            eps = 1.0 if r["side"] == 0 else -1.0
            m0 = mid_at(bbo, np.array([t]))[0]
            row = [eps * (m0 - tick * L.TICK) / m0 * 1e4]
            for h in MARKOUT_S:
                row.append(eps * (mid_at(bbo, np.array([t + h * L.NS]))[0] - m0) / m0 * 1e4)
            per.append(row)
    return n_f, q, np.asarray(per, float).reshape(-1, 1 + len(MARKOUT_S))


def report():
    lines = ["阶段 0 验收:实盘 对 逐笔委托回放(2026-10-02 18:49–21:22 UTC)", ""]
    for sym in ("XBTUSDCM", "XBTUSDTM"):
        res = json.load(open(os.path.join(OUT, f"{sym}.json")))
        bbo = np.load(os.path.join(OUT, f"{sym}_bbo.npy"))
        lines.append(f"== {sym}  订单 {res['n_orders']:,}  回放中断流 {res['breaks']} 次")
        for mode in ("actual", "model"):
            # 只比较两边都能评估的订单:仿真里没有落在预热 / 断流期,且实盘没有被交易所拒单
            rows = [(k, r) for k, r in res["orders"].items() if r[mode] is not None and not r["rejected"]]
            n = len(rows)
            real_f = {k for k, r in rows if any(f[3] for f in r["real"])}
            sim_f = {k for k, r in rows if r[mode]["fills"]}
            rq = sum(f[1] for k, r in rows for f in r["real"] if f[3])
            sq = sum(f for k, r in rows for _, f in r[mode]["fills"])
            rej = sum(1 for k, r in rows if r[mode]["state"] == "rejected")
            lines.append(f"  [{mode}] 可评估订单 {n:,}(其余 {res['n_orders'] - n:,} 张在预热 / 断流期或被拒)")
            lines.append(f"     成交订单  实盘 {len(real_f)}  仿真 {len(sim_f)}  两边都成交 {len(real_f & sim_f)}  只实盘 {len(real_f - sim_f)}  只仿真 {len(sim_f - real_f)}")
            lines.append(f"     成交张数  实盘 {rq}  仿真 {sq}   仿真判拒单(只挂不吃){rej} 张")
            if n:
                # 成交笔数按泊松,标准误 √n;合并标准误 = √(n_real + n_sim)(预登记 4.2)
                se = math.sqrt(max(len(real_f) + len(sim_f), 1))
                rel = (len(sim_f) - len(real_f)) / max(len(real_f), 1)
                lines.append(f"     成交率    实盘 {len(real_f) / n:.4%}  仿真 {len(sim_f) / n:.4%}  差 {len(sim_f) - len(real_f):+d} 笔 = {abs(len(sim_f) - len(real_f)) / se:.2f} 倍合并标准误,相对差 {rel:+.0%}")
            for key, lab in (("real", "实盘"), (mode, "仿真")):
                _, _, per = stats(rows, bbo, key)
                if len(per):
                    mu, sd = np.nanmean(per, axis=0), np.nanstd(per, axis=0, ddof=1) if len(per) > 1 else np.full(per.shape[1], np.nan)
                    lines.append(f"     {lab} 每笔(bp,n={len(per)})  成交时优势 {mu[0]:+.2f}(sd {sd[0]:.2f})  markout 1 s {mu[1]:+.2f}(sd {sd[1]:.2f})  10 s {mu[2]:+.2f}(sd {sd[2]:.2f})")
            for k in sorted(real_f ^ sim_f, key=lambda k: res["orders"][k]["t_send"]):
                r = res["orders"][k]
                lines.append(f"       不一致 {k}  {'买' if r['side'] == 0 else '卖'} {r['tick'] * L.TICK:.1f} x{r['size']}  实盘 {r['real']}  仿真 {r[mode]['state']} {r[mode]['fills']}  进簿时前方 {r[mode]['ahead0']} 张、档位 {r[mode]['level0']}")
        # T0-2b:实测延迟分布,多个种子
        ns, nr, both, qs, mk = [], [], [], [], []
        for i in range(N_SEEDS):
            mode = f"emp{i}"
            rows = [(k, r) for k, r in res["orders"].items() if r.get(mode) is not None and not r["rejected"]]
            real_f = {k for k, r in rows if any(f[3] for f in r["real"])}
            sim_f = {k for k, r in rows if r[mode]["fills"]}
            ns.append(len(sim_f)), nr.append(len(real_f)), both.append(len(real_f & sim_f))
            qs.append(sum(f for k, r in rows for _, f in r[mode]["fills"]))
            _, _, per = stats(rows, bbo, mode)
            if len(per):
                mk.append(np.nanmean(per, axis=0))
        if ns:
            m_s, m_r = float(np.mean(ns)), float(np.mean(nr))
            se = math.sqrt(max(m_s + m_r, 1.0))
            lines.append(f"  [emp × {N_SEEDS} 个种子] 成交订单  实盘 {m_r:.1f}  仿真 均值 {m_s:.2f}(各种子 {min(ns)}–{max(ns)},标准差 {np.std(ns, ddof=1):.2f})  两边都成交 均值 {np.mean(both):.2f}")
            lines.append(f"     差 {m_s - m_r:+.2f} 笔 = {abs(m_s - m_r) / se:.2f} 倍合并标准误,相对差 {(m_s - m_r) / max(m_r, 1):+.0%};成交张数 仿真均值 {np.mean(qs):.0f}")
            if mk:
                mm = np.mean(mk, axis=0)
                lines.append(f"     仿真 每笔(bp,种子平均)  成交时优势 {mm[0]:+.2f}  markout 1 s {mm[1]:+.2f}  10 s {mm[2]:+.2f}")
        lines.append("")
    txt = "\n".join(lines)
    open(os.path.join(OUT, "report.txt"), "w", encoding="utf8").write(txt)
    print(txt)


if __name__ == "__main__":
    run(sys.argv[2]) if sys.argv[1] == "run" else report()
