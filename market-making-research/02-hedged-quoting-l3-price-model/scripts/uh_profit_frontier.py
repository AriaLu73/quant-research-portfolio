#!/usr/bin/env python3
"""research3:BTC-USDC 这条线的利润上限(只看流量与成交后收益,不含库存约束):报价常挂在离公允价 δ bp、每张真实吃单最多接 cap 美元。
公允价 = USDT 中价 × (1 + 基差 60 秒滚动中位数)。净 = 对冲后 5 分钟 markout + USDC 返佣 我方费率 + 对冲腿返佣 我方费率 − 对冲价差与等待漂移 1.0(s2d 实测 B+E)。
全天数据(默认 9 月 8 个训练日)。输出每天的可接额、净 bp、美元/天。用法:Python314/python.exe -X utf8 scripts/research3/uh_profit_frontier.py"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uh_val as V

DAYS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["20260901", "20260902", "20260903", "20260910", "20260911", "20260914", "20260917", "20260918"]
DELTAS = (1, 2, 3, 4, 5, 6, 8, 10, 15); CAPS = (5_000, 10_000, 25_000, np.inf); ADJ = 1.2 + 0.7 - 1.0
rows = []
for day in DAYS:
    d = V.day_data(day); ats, amid, uts = d["ats"], d["amid"], d["uts"]; umid = (d["ubb"] + d["uba"]) / 2
    g = np.arange(max(uts[0], ats[0]) + 1_000_000, min(uts[-1], ats[-1]), 1_000_000)
    z = (V.at(uts, umid, g) / V.at(ats, amid, g) - 1.0) * 1e4
    D = pd.Series(z).rolling(60, min_periods=30).median().values
    t = d["tr"]; T = t.assign(usd=t.px * V.TICK * t.qty, p=t.px * V.TICK)
    Tg = T.groupby(["ts", "sgn"]).agg(pmin=("p", "min"), pmax=("p", "max"), usd=("usd", "sum")).reset_index()
    Tg = Tg.merge(d["anat"].rename(columns={"sg": "sgn"}), on=["ts", "sgn"], how="left")
    Tg["pair"] = Tg.pair.fillna(False).astype(bool) & (Tg.pmax == Tg.pmin)
    Tg = Tg[~Tg.pair & (Tg.ts > g[0] + 60_000_000) & (Tg.ts < g[-1] - 300_000_000)].reset_index(drop=True)
    tt, sg = Tg.ts.values, Tg.sgn.values
    a0 = V.at(ats, amid, tt, strict=True); f0 = a0 * (1 + D[np.clip(np.searchsorted(g, tt, "left") - 1, 0, len(g) - 1)] / 1e4)
    U5, A5 = V.at(uts, umid, tt + 300_000_000), V.at(ats, amid, tt + 300_000_000)
    key = pd.MultiIndex.from_arrays([tt, sg])
    Tm = T.merge(pd.DataFrame(dict(ts=tt, sgn=sg, f0=f0)), on=["ts", "sgn"]); Tm["d"] = Tm.sgn * (Tm.p - Tm.f0) / Tm.f0 * 1e4
    for dl in DELTAS:
        x = Tm[Tm.d >= dl].groupby(["ts", "sgn"]).usd.sum()
        if not len(x):
            continue
        pos = key.get_indexer(x.index); q = f0[pos] * (1 + sg[pos] * dl / 1e4); s = -sg[pos]
        r = s * ((U5[pos] - q) / q - (A5[pos] - a0[pos]) / a0[pos]) * 1e4
        for c in CAPS:
            f = np.minimum(x.values, c)
            rows.append(dict(day=day, delta=dl, cap=c, usd=float(f.sum()), pnl=float((f * (r + ADJ)).sum() / 1e4)))
R = pd.DataFrame(rows); nd = len(DAYS); pd.set_option("display.width", 200)
G = R.groupby(["delta", "cap"]).agg(usd_day=("usd", lambda x: x.sum() / nd), pnl_day=("pnl", lambda x: x.sum() / nd), pos_days=("pnl", lambda x: int((x > 0).sum()))).reset_index()
G["net_bp"] = G.pnl_day / G.usd_day * 1e4
for col, name in (("pnl_day", "每天净利 $"), ("usd_day", "USDC 腿可接额 $/天"), ("net_bp", "每美元净 bp"), ("pos_days", f"为正的天数(共 {nd})")):
    print(f"\n== {name}(行 = 报价离公允价 δ bp,列 = 每张吃单最多接)==")
    print(G.pivot(index="delta", columns="cap", values=col).rename(columns={5000.0: "≤$5k", 10000.0: "≤$10k", 25000.0: "≤$25k", np.inf: "全接"}).round(1).to_string())
# 多档叠加的上限:每个吃单在每个价位上都被我们接到(连续阶梯)= 对 δ 的"增量可接额 × 该档收益"求和;这里用 δ 网格近似
print("\n注:单一价位的结果。多档同时挂时,更深的档只接到越过它的那部分,总利润不超过各档相加。")
