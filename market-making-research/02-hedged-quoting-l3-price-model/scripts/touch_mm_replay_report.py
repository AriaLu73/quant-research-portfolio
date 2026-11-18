#!/usr/bin/env python3
"""MIDCAP-2 汇总:每合约 × mode × gated 的 7 日回放结果;稳健性口径 = 正收益天数、最差日、近期(0601–0901)合计、每万 U 净、库存占用。"""
import os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
f = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "research3", "touch_mm_replay_cap3_all.csv")
R = pd.read_csv(f)
R = R[R.error.isna()] if "error" in R else R
R["day"] = R.day.astype(str); R["recent"] = R.day >= "20260601"
pd.set_option("display.width", 260)


def summ(g):
    rec = g[g.recent]
    return pd.Series(dict(days=len(g), pos_days=int((g.net > 0).sum()), net_all=g.net.sum(), worst_day=g.net.min(),
                          net_recent=rec.net.sum(), recent_pos=int((rec.net > 0).sum()), recent_days=len(rec),
                          vol_day=g.vol.mean(), net_bp=g.net.sum() / g.vol.sum() * 1e4 if g.vol.sum() else np.nan,
                          spread_leg_bp=g.spread_leg.sum() / g.vol.sum() * 1e4 if g.vol.sum() else np.nan,
                          avg_abs_pos=g.avg_abs_pos_usd.mean(), peak_pos=g.peak_pos_usd.max(), spr_ticks=g.spread_med_ticks.median(), tick_bp=g.tick_bp.median()))


S = R.groupby(["sym", "mode", "gated"]).apply(summ).reset_index()
for mode in ("touch", "penny"):
    for gated in (False, True):
        x = S[(S["mode"] == mode) & (S.gated == gated)].sort_values("net_recent", ascending=False)
        print(f"\n=== mode={mode} gated={gated}: 按近期 4 天(0601–0901)合计净利排序,前 25 ===")
        print(x.drop(columns=["mode", "gated"]).head(25).to_string(index=False, float_format=lambda v: f"{v:,.1f}"))
        ok = x[(x.recent_pos == x.recent_days) & (x.recent_days >= 3)]
        print(f"近期每天都为正的合约:{len(ok)} 个;它们近期合计 ${ok.net_recent.sum():,.0f} / {ok.recent_days.iloc[0] if len(ok) else 0} 天")
S.to_csv(os.path.join(ROOT, "data", "research3", "touch_mm_replay_summary.csv"), index=False)
