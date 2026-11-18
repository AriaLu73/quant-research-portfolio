#!/usr/bin/env python3
"""research3:MM-UH 的容量上限(只看流量,不看策略):BTC-USDC 永续上真实吃单里,打到离公允价 δ bp 之外的成交额有多少。
公允价 = USDT 中价 × (1 + 基差 60 秒滚动中位数);真实吃单 = 剔除单价位成对打印。全天数据(默认 9 月 8 个训练日)。
对每个 δ 与每笔上限 cap(一张吃单最多接多少美元;inf = 全接):USDC 腿可接额/天;两腿成交 = 2 倍。
用法:Python314/python.exe -X utf8 scripts/research3/uh_capacity.py [days]"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uh_val as V

DAYS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["20260901", "20260902", "20260903", "20260910", "20260911", "20260914", "20260917", "20260918"]
DELTAS = (0.5, 1, 2, 3, 4, 6); CAPS = (5_000, 10_000, 25_000, 50_000, 150_000, np.inf)
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
    all_usd = float(Tg.usd.sum()); Tg = Tg[~Tg.pair & (Tg.ts > g[0] + 60_000_000) & (Tg.ts < g[-1])]
    f0 = V.at(ats, amid, Tg.ts.values, strict=True) * (1 + D[np.clip(np.searchsorted(g, Tg.ts.values, "left") - 1, 0, len(g) - 1)] / 1e4)
    Tm = T.merge(pd.DataFrame(dict(ts=Tg.ts.values, sgn=Tg.sgn.values, f0=f0)), on=["ts", "sgn"])
    Tm["d"] = Tm.sgn * (Tm.p - Tm.f0) / Tm.f0 * 1e4
    rec = dict(day=day, published_usd=all_usd, real_usd=float(Tg.usd.sum()), real_n=len(Tg), big_ge25k=int((Tg.usd >= 25_000).sum()), max_taker=float(Tg.usd.max()))
    for dl in DELTAS:
        x = Tm[Tm.d >= dl].groupby(["ts", "sgn"]).usd.sum()
        for c in CAPS:
            rec[f"d{dl}_c{c}"] = float(x.clip(upper=c).sum())
        rec[f"d{dl}_hours"] = int(pd.Series((x.index.get_level_values(0) // 3_600_000_000)).nunique())
    rows.append(rec)
R = pd.DataFrame(rows); pd.set_option("display.width", 220)
print(R[["day", "published_usd", "real_usd", "real_n", "big_ge25k", "max_taker"]].round(0).to_string(index=False))
print(f"\n日均:公布吃单额 ${R.published_usd.mean():,.0f},真实吃单额 ${R.real_usd.mean():,.0f}(最低 ${R.real_usd.min():,.0f},最高 ${R.real_usd.max():,.0f})")
tab = []
for dl in DELTAS:
    r = dict(delta_bp=dl, hours_with_flow=R[f"d{dl}_hours"].mean())
    for c in CAPS:
        r[("全接" if c == np.inf else f"每单≤${int(c / 1000)}k")] = R[f"d{dl}_c{c}"].mean()
    tab.append(r)
print("\n日均 USDC 腿可接额($;报价挂在离公允价 δ bp,每张真实吃单最多接 cap):")
print(pd.DataFrame(tab).round(0).to_string(index=False))
t2 = pd.DataFrame(tab).set_index("delta_bp").drop(columns="hours_with_flow") * 2 * 30 / 1e6
print("\n折成两腿月成交额($M,× 2 腿 × 30 天;上限口径:假设每张够得着的吃单都接到、库存不受限):"); print(t2.round(1).to_string())
