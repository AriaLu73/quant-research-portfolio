#!/usr/bin/env python3
"""research7 大 tick 线:把 ltk_l3.py 在各品种上的结果汇总成一张表(2026-10-01,逐笔委托真实排队)。

用途      回答"铺开到所有有数据的品种,带币安公允价规则的贴盘口,每个品种每天多少美元、合计多少"。
所属阶段  阶段 4 / 6 的方法在其它品种上的应用;不对应报价公式中的某一项。
列的含义  每笔净值 = (价差收益 + 60 秒 markout + 返佣) / 成交额(bp):不含 60 秒之后的库存漂移;
          每天美元(每笔口径)= 成交额 × 每笔净值,折算到 24 小时;
          含持仓的净盈亏 = 全部成交按 FIFO 结清、期末未平的库存按末尾中间价计,再加返佣,折算到 24 小时
          (探针不设库存上限,这一列含方向性持仓的盈亏,波动大,只作对照)。
          区间:按小时自助抽样 2,000 次的 95% 区间。
用法      .venv/Scripts/python.exe scripts/research7/ltk_l3_summary.py [ref_jit|ref_fix|all_fix]
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attribution as AT
import ltk_l3 as K
import ltk_screen as S

name = sys.argv[1] if len(sys.argv) > 1 else "ref_jit"
rng = np.random.default_rng(17)
rows = []
for f in sorted(glob.glob(os.path.join(K.OUT, "*.npz"))):
    sym = os.path.basename(f)[:-4]
    z = np.load(f)
    tick, mult = float(z["tick"]), float(z["mult"])
    bbo, sw, F = z["bbo"], z["sw"], z[name]
    if len(bbo) < 100:
        continue
    bt, bm = bbo[:, 0], (bbo[:, 1] + bbo[:, 2]) / 2.0 * tick
    rb = S.rebate(sym)
    dur_h = (bt[-1] - bt[0]) / 3.6e12
    scale = 24.0 / dur_h
    mkt = float(np.sum(sw[:, 2] * mult * sw[:, 3] * tick))
    if not len(F):
        rows.append((sym, float(z["tick_bp"]), 0, 0.0, np.nan, np.nan, np.nan, 0.0, 0.0, mkt * scale))
        continue
    a = AT.attribute(F[:, 0].astype(np.int64), np.where(F[:, 1] == 0, 1, -1), F[:, 2] * tick, F[:, 3] * mult, bt, bm, int(bt[-1]), -rb, horizons_s=(60.0,))
    nv = float(np.nansum(a["notional"]))
    hour = a["t"] // (3600 * 10**9)
    hs = np.unique(hour)
    def pf(ix):
        m = np.isin(hour, ix)
        n_ = np.nansum(a["notional"][m])
        return (np.nansum(a["spread"][m]) + np.nansum(a["markout_60"][m]) - np.nansum(a["fee"][m])) / n_ * 1e4 if n_ > 0 else np.nan
    bs = [pf(hs[rng.integers(0, len(hs), len(hs))]) for _ in range(2000)]
    lo, hi = np.nanpercentile(bs, (2.5, 97.5))
    e = pf(hs)
    rows.append((sym, float(z["tick_bp"]), len(F), nv * scale, e, lo, hi, nv * scale * e / 1e4, (float(np.nansum(a["total"])) - float(np.nansum(a["fee"]))) * scale, mkt * scale))
rows.sort(key=lambda r: -r[1])
print(f"方案 {name}:贴最优价" + ("、只在我方报价比币安公允价好 −0.25 tick 以上时挂(θ 取自 8–9 月训练段)" if "ref" in name else "、不带规则(跟价)") + ";2026-10-01 逐笔委托真实排队;每单约 $2,000;各列已折算到 24 小时")
print(f"{'品种':<13}{'tick bp':>8}{'成交笔':>7}{'成交额$/天':>12}{'占全市场':>8}{'每笔净值 bp(95% 区间)':>30}{'$/天(每笔口径)':>14}{'$/天(含持仓)':>14}")
tot = [0.0, 0.0, 0.0]
pos = 0
for sym, tb, n, nv, e, lo, hi, usd, usd_all, mkt in rows:
    print(f"{sym:<14}{tb:>7.2f}{n:>8d}{nv:>13,.0f}{nv / mkt if mkt else 0:>9.1%}   {e:>+6.2f}({lo:>+6.2f} … {hi:>+6.2f}){usd:>14.2f}{usd_all:>15.2f}")
    tot[0] += nv; tot[1] += usd; tot[2] += usd_all
    pos += usd > 0
print(f"{'合计':<13}{'':>8}{'':>7}{tot[0]:>13,.0f}{'':>8}{'':>30}{tot[1]:>14.2f}{tot[2]:>15.2f}    每笔口径为正的品种 {pos} / {len(rows)}")
for lab, cond in (("tick ≥ 1 bp", lambda r: r[1] >= 1), ("tick 0.3–1 bp", lambda r: 0.3 <= r[1] < 1), ("tick < 0.3 bp", lambda r: r[1] < 0.3)):
    g = [r for r in rows if cond(r)]
    nv = sum(r[3] for r in g)
    print(f"   {lab:<14} {len(g)} 个品种:成交额 ${nv:,.0f}/天,每笔口径 ${sum(r[7] for r in g):+.2f}/天(合并每笔净值 {sum(r[7] for r in g) / nv * 1e4 if nv else float('nan'):+.2f} bp),含持仓 ${sum(r[8] for r in g):+.2f}/天")
