#!/usr/bin/env python3
"""research7 大 tick 品种第三步:币安公允价"挂 / 撤"规则在逐笔委托真实排队下是否成立(2026-10-01 一天)。

起因      第二轮(ltk_ref.py,8–9 月 L2)的样本外结果:加上币安公允价规则后,队首口径每笔 +0.5…+1.1 bp,排到队尾 −0.5…−1.7 bp。
          两个口径符号相反(与 BTC 相同的局面),由逐笔委托的真实排队裁决。
所属阶段  阶段 4 / 6 的方法在其它品种上的应用;不改变 BTC 线已有结论。
对应公式  F_t = 币安同名永续最后成交价 × exp(基差);执行层:保持 / 撤单 / 重挂。
规则      与 ltk_ref.py 相同,θ = −0.25 tick(8–9 月训练段选定,10-01 对它是样本外):
          某一侧只在 ε·(F − P) ≥ θ·tick 时挂在同侧最优价;不满足即撤;重新满足时在当时的最优价重挂(回到队尾——真实排队下的代价)。
          基差 = 过去 300 秒 ln(KuCoin 中间价 / 币安价)每秒采样的中位数,在线计算,只用过去。
          币安价格按滞后 100 毫秒读取(保守)。
并列方案  ref_fix / ref_jit   带规则;固定延迟 1.8 ms / 行情与下单按实测分布抽样
          all_fix             不带规则,始终贴最优价(对照)
          单量 = 约 $2,000 名义金额(与离线相同);不设库存上限(测量探针,只看每笔净值)。
数据      KuCoin 逐笔委托 data/research4/l3_raw/20261001(自采;TradFi 合约);币安 data/research7/feat/bn_<sym>_20261001.npz。
注意      l3sim 的 TICK / 合约乘数原先按 BTC 写死,这里在运行前按品种设置(l3sim.TICK、l3sim.MULT、数据目录)。
用法      .venv/Scripts/python.exe scripts/research7/ltk_l3.py run <KuCoin 合约> <币安合约>
          .venv/Scripts/python.exe scripts/research7/ltk_l3.py report <KuCoin 合约> [...]
"""
import collections
import glob
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attribution as AT
import calib as C
import l3_prep as P
import l3sim as L
import ltk_screen as S

DAY = "20261001"
RAW = os.path.join(C.ROOT, "data", "research4", "l3_raw")
FEAT = os.path.join(C.ROOT, "data", "research7", "feat")
OUT = os.path.join(C.ROOT, "data", "research7", "ltk_l3")
STEP_NS = 100_000_000
THETA = -0.25             # tick:8–9 月训练段选定(ltk_ref.py)
BASIS_S = 300             # 基差窗口(秒):同 ltk_ref.py
ORDER_USD = 2000.0        # 每单名义金额:同离线
AWAY = 0                  # 不带规则的对照:最优价一离开我方价位就重挂(这些品种价差常为 1–4 个 tick,不保留)
SEED = 81
NAMES = ("ref_fix", "ref_jit", "all_fix", "imp_ref_jit", "imp_all_jit")


class RefTouch:
    """贴最优价的测量探针;use_ref=True 时按币安公允价规则决定每一侧挂不挂。"""

    def __init__(self, name, lat, sym, bn, tick_bp, size, use_ref, improve=False):
        # improve=True:价差 ≥ 2 个 tick 时不加入现有最优价,而是挂在比它好一个 tick 的价位(价格优先 → 进簿即排在最前,不靠速度)。
        # 2026-10-08 用户问"为什么排不到前面"后新增:此前所有探针都只加入最优价(BTC 价差恒为 1 tick,没有别的位置),
        # 没有检验宽价差品种上"改善一个 tick"这条路。仿真器不把我方订单放进公开盘口,所以 sim.best() 是别人的最优价。
        self.improve = improve
        self.name, self.lat, self.orders, self.sym = name, lat, [], sym
        self.g0, self.lpb = bn
        self.thr = THETA * tick_bp                               # bp
        self.size, self.use = size, use_ref
        self.work, self.fills, self.pos = [None, None], [], 0.0
        self.sec, self.diffs, self.basis = None, collections.deque(maxlen=BASIS_S), None
        self.n_place = self.n_cancel = 0

    def _bn(self, ts):
        j = ts // STEP_NS - self.g0 - 1                           # 滞后一个网格点(100 毫秒)
        return self.lpb[j] if 0 <= j < len(self.lpb) else None

    def on_event(self, sim, ts):
        bb, ba = sim.best(0), sim.best(1)
        if bb is None or ba is None or bb >= ba:
            return
        lb = self._bn(ts)
        s = ts // L.NS
        if s != self.sec:                                         # 每秒采样一次基差(先取中位数再加入本秒的值:只用过去)
            self.sec = s
            if len(self.diffs) >= BASIS_S // 2:
                self.basis = float(np.median(self.diffs))
            if lb is not None and np.isfinite(lb):
                self.diffs.append(math.log((bb + ba) / 2.0 * L.TICK) - lb)
        for side in (0, 1):
            o = self.work[side]
            if o is not None and (o.state not in ("pending", "live") or o.cancel_at is not None):
                o = self.work[side] = None
            want = bb if side == 0 else ba
            if self.improve and ba - bb >= 2:
                want = bb + 1 if side == 0 else ba - 1             # 比别人的最优价好一个 tick(仍在价差之内,不会吃单)
            allow = True
            if self.use:
                if self.basis is None or lb is None or not np.isfinite(lb):
                    allow = False
                else:
                    F = math.exp(lb + self.basis)
                    pchk = (o.tick if o is not None else want) * L.TICK
                    edge = (1 if side == 0 else -1) * (F - pchk) / pchk * 1e4
                    allow = edge >= self.thr
            if self.improve and o is not None and allow:
                # 改善版:只要我方仍严格优于别人的最优价就保持;一旦被追平或被压过(别人挂到了我方价位或更好),撤掉重挂
                still_best = (o.tick > bb) if side == 0 else (o.tick < ba)
                if still_best or o.tick == want:
                    continue
                allow_keep = False
            elif o is not None and allow and (self.use or abs(o.tick - want) <= AWAY):
                continue                                          # 保持(带规则时:只要仍比公允价好就留着,保留排队位置)
            if o is not None:
                sim.cancel(o, ts)
                self.n_cancel += 1
                self.work[side] = None
                continue
            if allow:
                self.work[side] = sim.place(self, side, want, self.size, ts)
                self.n_place += 1

    def on_fill(self, sim, o, qty, ts, sweep_qty):
        self.fills.append((ts, o.side, o.tick, qty, -999 if o.level0 is None else o.level0, o.ahead0, self.pos, sweep_qty))
        self.pos += (qty if o.side == 0 else -qty) * L.MULT[self.sym]

    def on_break(self, sim, ts):
        self.work = [None, None]


def run(sym, bsym):
    tick, mult = S.spec(sym)
    L.TICK, L.MULT[sym], L.L3_DIR[sym], L.TRD_DIR = tick, mult, RAW, RAW           # 按品种设置(见文件头)
    hours = sorted(os.path.basename(f)[:2] for f in glob.glob(os.path.join(RAW, DAY, f"??_{sym}_l3.jsonl.gz")))
    zb = np.load(os.path.join(FEAT, f"bn_{bsym}_{DAY}.npz"))
    bn = (int(zb["g0"]), np.log(zb["px"].astype(np.float64)))
    px = float(np.nanmedian(zb["px"]))
    tick_bp = tick / px * 1e4
    size = max(1, int(round(ORDER_USD / (mult * px))))                               # 单位换算:美元 → 张
    lt = np.load(os.path.join(P.OUT, "latency_empirical.npz"))
    fix = lambda: L.Latency(fixed_ms=1.8)
    jit = lambda: L.EmpiricalLatency(P.Load(), lt, lead_ms=0.3, seed=SEED, md_jitter=True)
    ags = [RefTouch("ref_fix", fix(), sym, bn, tick_bp, size, True), RefTouch("ref_jit", jit(), sym, bn, tick_bp, size, True),
           RefTouch("all_fix", fix(), sym, bn, tick_bp, size, False),
           RefTouch("imp_ref_jit", jit(), sym, bn, tick_bp, size, True, improve=True), RefTouch("imp_all_jit", jit(), sym, bn, tick_bp, size, False, improve=True)]
    rec = P.Recorder()
    sim = L.L3Sim(sym, fix(), ags, recorder=rec, trade_ticks=P.load_trade_ticks(DAY, hours, sym))
    sim.run(DAY, hours, prewarm_s=0)
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(os.path.join(OUT, f"{sym}.npz"), bbo=np.asarray(rec.bbo, np.int64).reshape(-1, 5), sw=np.asarray(rec.sw, np.int64).reshape(-1, 6),
                        tick=tick, mult=mult, size=size, tick_bp=tick_bp, breaks=sim.breaks, paired=sim.paired_n, hours=len(hours),
                        msgs=np.array([[a.n_place, a.n_cancel] for a in ags]), **{a.name: np.asarray(a.fills, float).reshape(-1, 8) for a in ags})
    print(f"{sym}: {len(hours)} 个小时文件;1 tick = {tick_bp:.2f} bp;单量 {size} 张;" + "  ".join(f"{a.name} 成交 {len(a.fills)}" for a in ags) + f";断流 {sim.breaks}  LTKL3_DONE", flush=True)


def report(syms):
    lines = []
    Pn = lambda s="": (lines.append(s), print(s, flush=True))
    Pn(f"大 tick 品种:币安公允价规则(θ = {THETA} tick)在逐笔委托真实排队下 —— 2026-10-01(对规则是样本外);每单约 ${ORDER_USD:,.0f}")
    rng = np.random.default_rng(13)
    for sym in syms:
        z = np.load(os.path.join(OUT, f"{sym}.npz"))
        tick, mult = float(z["tick"]), float(z["mult"])
        bbo, sw = z["bbo"], z["sw"]
        bt, bm = bbo[:, 0], (bbo[:, 1] + bbo[:, 2]) / 2.0 * tick
        rb = S.rebate(sym)
        dur_h = (bt[-1] - bt[0]) / 3.6e12
        mkt_usd = float(np.sum(sw[:, 2] * mult * sw[:, 3] * tick))
        Pn(f"\n== {sym}:1 tick = {float(z['tick_bp']):.2f} bp;可用 {dur_h:.1f} 小时;全市场吃单成交额 ${mkt_usd:,.0f};返佣 {rb} bp;断流 {int(z['breaks'])} 次")
        for vi, name in enumerate(NAMES):
            F = z[name]
            if not len(F):
                Pn(f"   {name:<8} 没有成交")
                continue
            a = AT.attribute(F[:, 0].astype(np.int64), np.where(F[:, 1] == 0, 1, -1), F[:, 2] * tick, F[:, 3] * mult, bt, bm, int(bt[-1]), -rb, horizons_s=(10.0, 60.0, 300.0))
            nv = float(np.nansum(a["notional"]))
            hour = a["t"] // (3600 * 10**9)
            hs = np.unique(hour)

            def per_fill(ix_hours, key):
                m = np.isin(hour, ix_hours)
                n_ = np.nansum(a["notional"][m])
                return (np.nansum(a["spread"][m]) + np.nansum(a[key][m]) - np.nansum(a["fee"][m])) / n_ * 1e4 if n_ > 0 else np.nan
            out = []
            for key, lab in (("markout_10", "10 s"), ("markout_60", "60 s"), ("markout_300", "300 s")):
                bs = [per_fill(hs[rng.integers(0, len(hs), len(hs))], key) for _ in range(2000)]
                lo, hi = np.nanpercentile(bs, (2.5, 97.5))
                out.append(f"{lab} {per_fill(hs, key):+.2f}({lo:+.2f} … {hi:+.2f})")
            ah = F[:, 5]
            Pn(f"   {name:<8} 成交 {len(F):4d}  成交额 ${nv:>9,.0f}(占全市场 {nv / mkt_usd:.1%})  价差 {np.nansum(a['spread']) / nv * 1e4:+.2f}  mk60 {np.nansum(a['markout_60']) / nv * 1e4:+.2f} bp"
               f" | 每笔净值(价差 + markout + 返佣):" + ";".join(out)
               + f" | 进簿时前方张数 中位 {np.median(ah):.0f}(= 0 的占 {np.mean(ah == 0):.0%}) | 下单 + 撤单 {int(z['msgs'][vi].sum()):,} 条")
    open(os.path.join(OUT, "ltk_l3_report.txt"), "w", encoding="utf8").write("\n".join(lines))


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2], sys.argv[3])
    else:
        report(sys.argv[2:])
