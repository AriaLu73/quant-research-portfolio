#!/usr/bin/env python3
"""H-W(可见单拦截成对打印)全合约汇总 + 无偏选择检验。用法:python pair_intercept_report.py <tag 后缀,如 _all18>"""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = pd.read_csv(os.path.join(ROOT, "data", "research3", f"pair_intercept{sys.argv[1]}.csv"))
if "error" in D:
    print("errors:", int(D.error.notna().sum())); D = D[D.error.isna()]
D = D[D.fills > 0].copy(); D["day"] = D.day.astype(int).astype(str)
A = pd.read_csv(os.path.join(ROOT, "data", "research3", "flow_anatomy_alts.csv")); A = A[A.error.isna()] if "error" in A else A
A["day"] = A.day.astype(int).astype(str)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
TR, TE = ["20260601", "20260701", "20260801"], "20260901"
for L, X in D.groupby("L"):
    print(f"\n==================== 生效延迟 L = {L:g} ms(要求观测间隔 ≥ {L + 1:g} ms)====================")
    g = X.groupby("sym").agg(days=("day", "size"), net=("rt_net", "sum"), pos=("rt_net", lambda x: int((x > 0).sum())), worst=("rt_net", "min"), vol_day=("rt_vol", "mean"),
                             pair=("pair_share", "mean"), e5=("e5_bp", "mean"), ord_s=("orders_per_s", "mean"), spr=("spr_ticks", "median"), tick_bp=("tick_bp", "median"))
    g["net_bp"] = g.net / (g.vol_day * g.days) * 1e4
    print(f"合约 {len(g)};7 日合计净利 > 0 的 {int((g.net > 0).sum())};全体合计 ${g.net.sum():,.0f},成交额 ${(g.vol_day * g.days).sum():,.0f}")
    print("前 15:"); print(g.sort_values("net", ascending=False).head(15).round(2).to_string())
    print("后 5:"); print(g.sort_values("net").head(5).round(2).to_string())
    P = X.pivot_table(index="sym", columns="day", values="rt_net"); V = X.pivot_table(index="sym", columns="day", values="rt_vol")
    have = P[TR + [TE]].dropna(); sel = have[(have[TR] > 0).all(axis=1)].index; rest = have.index.difference(sel)
    te = have.loc[sel, TE]
    print(f"\n[选法 A] 训练三天(0601/0701/0801)全正 → 入选 {len(sel)}/{len(have)};检验日 0901:正 {int((te > 0).sum())}/{len(sel)},合计 ${te.sum():,.0f},成交额 ${V.loc[sel, TE].sum():,.0f}"
          + (f"({te.sum() / V.loc[sel, TE].sum() * 1e4:+.2f} bp)" if len(sel) else ""))
    if len(sel):
        o = have.loc[sel].copy(); o["vol_test"] = V.loc[sel, TE]; print(o.sort_values(TE, ascending=False).round(0).to_string())
    print(f"        落选组检验日:正 {int((have.loc[rest, TE] > 0).sum())}/{len(rest)},合计 ${have.loc[rest, TE].sum():,.0f}")
    days = sorted(A.day.unique()); rows = []
    for i in range(1, len(days)):
        a = A[A.day == days[i - 1]]; s = a[(a.pair_share >= 0.7) & (a.half_bp >= 2.0)].sym
        h = X[(X.day == days[i]) & (X.sym.isin(s))]
        rows.append(dict(test_day=days[i], n=len(h), pos=int((h.rt_net > 0).sum()), net=h.rt_net.sum(), vol=h.rt_vol.sum()))
    Rr = pd.DataFrame(rows)
    print(f"[选法 B] 事前结构筛选(前一可用日 成对占比 ≥ 0.7 且 半点差 ≥ 2 bp):合约日 {int(Rr.n.sum())},为正 {int(Rr.pos.sum())},合计 ${Rr.net.sum():,.0f},成交额 ${Rr.vol.sum():,.0f}({Rr.net.sum() / max(1, Rr.vol.sum()) * 1e4:+.2f} bp)")
    print(Rr.round(0).to_string(index=False))
