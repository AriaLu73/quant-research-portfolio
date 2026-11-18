#!/usr/bin/env python3
"""research7 L2 排队推断相对逐笔委托真实排队的误差标定(10-01、10-02 两天两种数据都有)。

用途      同一组探针策略(贴盘口排队 / 盘口外固定距离;第一版用基准 GLFT,因其对毫秒级时序过于敏感而弃用,见标定文档)、同一个固定延迟(1.8 ms,排除延迟抽样的随机性),
          分别在 l3sim(真实排队)与 l2sim(三种撤单归属规则)上运行,逐小时比较成交笔数、成交额、净盈亏与归因。
所属阶段  阶段 0 的补充;研究二第 4 条(队列位置推断方法及其误差)。不对应报价公式中的某一项。
预登记    docs/research7/00_范围_阈值_预登记.md 第 6 节:规则在 10-01 上选(成交额与真实排队之差的绝对值最小),10-02 上验收
          (成交笔数与 markout 之差 ≤ 2 倍合并标准误且相对差 ≤ 30%)。
用法      .venv/Scripts/python.exe scripts/research7/l2_vs_l3.py l3 <YYYYMMDD> <HH>
          .venv/Scripts/python.exe scripts/research7/l2_vs_l3.py l2 <YYYYMMDD>
          .venv/Scripts/python.exe scripts/research7/l2_vs_l3.py report
"""
import glob
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attribution as AT
import glft_backtest as B
import l2sim as S
import l3_prep as P
import l3sim as L

SYM = "XBTUSDTM"
OUT = os.path.join(P.OUT, "l2_vs_l3")
FIX_MS = 1.8                      # 固定延迟(毫秒):用户口径 行情 0.3 + 下单 1.5;这里只为排除抽样随机性
HOUR_NS = 3600 * L.NS
GAMMAS = (("touch", None), ("deep", None))   # 两个探针策略(变量名沿用:第一项是名字)
RULES = ("prop", "back", "front")


class Probe:
    """标定用的探针策略(不是交易策略,不计库存上限):每侧一张单,规则只依赖价格、对毫秒级事件顺序不敏感。
    mode "touch"  始终挂在同侧最优价上(加入队尾);最优价离开我方价位超过 away 个 tick 才撤单重挂 —— 成交取决于排队位置。
    mode "deep"   挂在中间价外 dist 个 tick;理论价与挂单价相差超过 band 个 tick 才撤单重挂 —— 成交来自扫单。
    常数(都只为标定而设,ASSUMPTION):单量 200 张 = 阶段 1 的 Δ;away 5 tick;dist 200 tick(20 美元 ≈ 2.4 bp ≈ 1/κ);band 50 tick。
    每到整点库存记 0(与逐笔委托回放"每小时独立"一致)。"""
    SIZE, AWAY, DIST, BAND = 200, 5, 200, 50

    def __init__(self, name, mode, lat):
        self.name, self.mode, self.lat, self.orders = name, mode, lat, []
        self.work, self.pos, self.fills, self.hour = [None, None], 0.0, [], None
        self.n_place = self.n_cancel = 0

    def on_event(self, sim, ts):
        h = ts // HOUR_NS
        if h != self.hour:
            self.hour, self.pos = h, 0.0
        bb, ba = sim.best(0), sim.best(1)
        if bb is None or ba is None or bb >= ba:
            return
        for side in (0, 1):
            o = self.work[side]
            if o is not None and (o.state not in ("pending", "live") or o.cancel_at is not None):
                o = self.work[side] = None
            if self.mode == "touch":
                want = bb if side == 0 else ba
                keep = o is not None and abs(o.tick - want) <= self.AWAY
            else:
                mid2 = bb + ba                                      # 2 × 中间价(tick),避免半个 tick
                want = (mid2 - 2 * self.DIST) // 2 if side == 0 else -((-(mid2 + 2 * self.DIST)) // 2)
                keep = o is not None and abs(o.tick - want) <= self.BAND
            if keep:
                continue
            if o is not None:
                sim.cancel(o, ts)
                self.n_cancel += 1
            self.work[side] = sim.place(self, side, want, self.SIZE, ts)
            self.n_place += 1

    def on_fill(self, sim, o, qty, ts, sweep_qty):
        self.fills.append((ts, o.side, o.tick, qty, -999 if o.level0 is None else o.level0, o.ahead0, self.pos, sweep_qty))
        self.pos += (qty if o.side == 0 else -qty) * L.MULT[SYM]

    def on_break(self, sim, ts):
        self.work = [None, None]


def run_l3(day, hh):
    ags = [Probe(n, n, L.Latency(fixed_ms=FIX_MS)) for n, _ in GAMMAS]
    sim = L.L3Sim(SYM, L.Latency(fixed_ms=FIX_MS), ags, trade_ticks=P.load_trade_ticks(day, [hh], SYM))
    sim.run(day, [hh])
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(os.path.join(OUT, f"l3_{day}_{hh}.npz"), **{a.name: np.asarray(a.fills, float).reshape(-1, 8) for a in ags})
    print(f"l3 {day} {hh}: " + "  ".join(f"{a.name} {len(a.fills)}" for a in ags) + "  CMP_L3_DONE", flush=True)


def run_l2(day):
    ev = np.load(os.path.join(P.OUT, "l2", f"{SYM}_{day}.npz"))
    ags = []
    for n, _ in GAMMAS:
        for r in RULES:
            a = Probe(f"{n}_{r}", n, L.Latency(fixed_ms=FIX_MS))
            a.cancel_rule = r
            ags.append(a)
    rec = P.Recorder()
    sim = S.L2Sim(SYM, L.Latency(fixed_ms=FIX_MS), ags, recorder=rec)
    sim.run(ev)
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(os.path.join(OUT, f"l2_{day}.npz"), bbo=np.asarray(rec.bbo, np.int64).reshape(-1, 5),
                        **{a.name: np.asarray(a.fills, float).reshape(-1, 8) for a in ags})
    print(f"l2 {day}: " + "  ".join(f"{a.name} {len(a.fills)}" for a in ags) + f"  重置 {sim.breaks}  非盘口打印 {sim.paired_n} 笔 / {sim.paired_qty} 张"
          f"  成交 {sim.trade_qty} 张中未与 L2 减少配上对的 {sim.unpaired_qty} 张  CMP_L2_DONE", flush=True)


def hour_stats(F, bt, bm, t_end):
    """一个小时的成交 → (笔数, 成交额, 净盈亏, 价差, markout10, 持有) 美元。"""
    if not len(F):
        return np.zeros(6)
    a = AT.attribute(F[:, 0].astype(np.int64), np.where(F[:, 1] == 0, 1, -1), F[:, 2] * L.TICK, F[:, 3] * L.MULT[SYM], bt, bm, t_end, B.MAKER_FEE_BP)
    s = lambda k: float(np.nansum(a[k]))
    return np.array([len(F), s("notional"), s("total") - s("fee"), s("spread"), s("markout_10"), s("hold_10")])


def report():
    lines = []
    Pn = lambda x="": (lines.append(x), print(x, flush=True))
    Pn(f"L2 排队推断 对 逐笔委托真实排队(XBTUSDTM;同一策略、固定延迟 {FIX_MS} ms;每小时独立、小时初空仓)")
    for day in B.DAYS:
        z2 = np.load(os.path.join(OUT, f"l2_{day}.npz"))
        b2 = z2["bbo"]
        t2, m2 = b2[:, 0], (b2[:, 1] + b2[:, 2]) / 2.0 * L.TICK
        hours = sorted(os.path.basename(f)[-6:-4] for f in glob.glob(os.path.join(OUT, f"l3_{day}_??.npz")))
        for n, _ in GAMMAS:
            rows = {k: [] for k in ("l3",) + RULES}
            for hh in hours:
                mk = np.load(os.path.join(P.OUT, "market", f"{SYM}_{day}_{hh}.npz"))["bbo"]
                if len(mk) < 2:
                    continue
                lo, hi = int(mk[0, 0]), int(mk[-1, 0])                  # 这个小时里逐笔委托回放可用的时间段;L2 的成交只取同一段
                F3 = np.load(os.path.join(OUT, f"l3_{day}_{hh}.npz"))[n]
                rows["l3"].append(hour_stats(F3, mk[:, 0], (mk[:, 1] + mk[:, 2]) / 2.0 * L.TICK, hi))
                for r in RULES:
                    F2 = z2[f"{n}_{r}"]
                    F2 = F2[(F2[:, 0] >= lo) & (F2[:, 0] <= hi)]
                    rows[r].append(hour_stats(F2, t2, m2, hi))
            R = {k: np.array(v) for k, v in rows.items()}
            T3 = R["l3"].sum(0)
            Pn(f"\n== {day}  {n}({len(hours)} 个小时)")
            Pn("   口径          成交笔数    成交额 $    净盈亏 $  价差 bp  mk10 bp  持有 bp   净 bp   | 相对真实排队:笔数差(倍合并标准误 / 相对)  成交额差  逐小时净盈亏差 均值 ± 标准差")
            for k in ("l3",) + RULES:
                T = R[k].sum(0)
                bp = lambda x: x / T[1] * 1e4 if T[1] > 0 else float("nan")
                extra = ""
                if k != "l3":
                    dn = T[0] - T3[0]
                    dh = R[k][:, 2] - R["l3"][:, 2]
                    extra = f"   | {dn:+.0f}({abs(dn) / math.sqrt(max(T[0] + T3[0], 1)):.2f} / {dn / max(T3[0], 1):+.0%})  {(T[1] - T3[1]) / max(T3[1], 1):+.0%}  {dh.mean():+.2f} ± {dh.std(ddof=1):.2f}"
                name = "真实排队" if k == "l3" else "L2 " + k
                Pn(f"   {name:<12}{T[0]:>8.0f}{T[1]:>12,.0f}{T[2]:>+11.2f}{bp(T[3]):>+9.2f}{bp(T[4]):>+9.2f}{bp(T[5]):>+9.2f}{bp(T[2]):>+8.2f}{extra}")
    open(os.path.join(OUT, "report.txt"), "w", encoding="utf8").write("\n".join(lines))


if __name__ == "__main__":
    {"l3": run_l3, "l2": run_l2, "report": report}[sys.argv[1]](*sys.argv[2:])
