#!/usr/bin/env python3
"""MIDCAP-2 选品种的样本外检验(教材第 23 章:挑品种必须只用当时能知道的信息)。
规则(事先写定):训练 = 0601/0701/0801 三天;入选 = 三天净利都 > 0(ungated,指定 mode);检验 = 0901(只报告,不再筛)。
同时报告:更早三天(1001/0101/0401)的表现(另一种行情)、入选组与落选组在检验日的对比、归因。"""
import os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
f = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "research3", "touch_mm_replay_cap3_all.csv")
R = pd.read_csv(f)
if "error" in R:
    R = R[R.error.isna()]
R["day"] = R.day.astype(str)
TR, TE, OLD = ["20260601", "20260701", "20260801"], ["20260901"], ["20251001", "20260101", "20260401"]
pd.set_option("display.width", 250)
for mode in ("touch", "penny"):
    X = R[(R["mode"] == mode) & (R.gated == False)]  # noqa: E712
    P = X.pivot_table(index="sym", columns="day", values="net")
    V = X.pivot_table(index="sym", columns="day", values="vol")
    have = P[TR + TE].dropna()
    sel = have[(have[TR] > 0).all(axis=1)].index
    rest = have.index.difference(sel)
    print(f"\n================ mode = {mode} (ungated, cap 3 clip, clip $1k) ================")
    print(f"有四天数据的合约 {len(have)};训练三天全正 → 入选 {len(sel)};落选 {len(rest)}")
    te = have.loc[sel, TE[0]]
    print(f"检验日 0901 入选组:为正 {int((te > 0).sum())}/{len(sel)},合计 ${te.sum():,.0f},中位 ${te.median():,.1f},最差 ${te.min():,.0f};成交额合计 ${V.loc[sel, TE[0]].sum():,.0f}"
          f"({te.sum() / V.loc[sel, TE[0]].sum() * 1e4:+.2f} bp)")
    tr_ = have.loc[rest, TE[0]]
    print(f"检验日 0901 落选组:为正 {int((tr_ > 0).sum())}/{len(rest)},合计 ${tr_.sum():,.0f}({tr_.sum() / V.loc[rest, TE[0]].sum() * 1e4:+.2f} bp)")
    out = P.loc[sel].copy()
    out["train_sum"] = out[TR].sum(axis=1); out["test"] = out[TE[0]]
    out["old_sum"] = out.reindex(columns=OLD).sum(axis=1, min_count=1)
    meta = X.groupby("sym").agg(spr_ticks=("spread_med_ticks", "median"), tick_bp=("tick_bp", "median"), vol_day=("vol", "mean"), avg_pos=("avg_abs_pos_usd", "mean"))
    out = out.join(meta).sort_values("test", ascending=False)
    cols = [c for c in OLD if c in out] + TR + TE + ["train_sum", "old_sum", "spr_ticks", "tick_bp", "vol_day", "avg_pos"]
    print(out[cols].to_string(float_format=lambda v: f"{v:,.0f}" if abs(v) >= 10 else f"{v:,.2f}"))
    if "attr_spread" in X:
        A = X[X.sym.isin(sel) & X.day.isin(TE)].agg({"attr_spread": "sum", "attr_adverse5": "sum", "attr_holding": "sum", "rebate": "sum", "net": "sum", "vol": "sum"})
        print("入选组检验日归因($):", {k: round(float(v), 1) for k, v in A.items()})
