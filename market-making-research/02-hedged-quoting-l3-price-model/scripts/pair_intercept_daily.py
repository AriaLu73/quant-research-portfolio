#!/usr/bin/env python3
"""H-W 全合约不挑选的按日汇总,多口径并排。用法:python pair_intercept_daily.py _fr_h20,_fr_h3,_fr_h3_cap1k"""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pd.set_option("display.width", 220)
for tag in sys.argv[1].split(","):
    D = pd.read_csv(os.path.join(ROOT, "data", "research3", f"pair_intercept{tag}.csv"))
    if "error" in D:
        D = D[D.error.isna()]
    D = D[D.fills > 0]
    for L, X in D.groupby("L"):
        g = X.groupby("day").agg(contracts=("sym", "size"), pos=("rt_net", lambda x: int((x > 0).sum())), net=("rt_net", "sum"), vol=("rt_vol", "sum"), worst=("rt_net", "min"),
                                 best=("rt_net", "max"), orders_s=("orders_per_s", "sum"), pair=("pair_share", "mean"), abs_end_pos=("end_pos_usd", lambda x: x.abs().sum()))
        g["bp"] = g.net / g.vol * 1e4
        top = X.groupby("sym").rt_net.sum().sort_values(ascending=False)
        print(f"\n== {tag}  L = {L:g} ms:7 日合计 ${top.sum():,.0f} / ${g.vol.sum():,.0f}({top.sum() / g.vol.sum() * 1e4:+.2f} bp);正合约 {int((top > 0).sum())}/{len(top)};"
              f"去掉最赚 3 个后 ${top.iloc[3:].sum():,.0f};近 4 天(0601–0901)${g.net.iloc[-4:].sum():,.0f}")
        print(g.round(2).to_string())
