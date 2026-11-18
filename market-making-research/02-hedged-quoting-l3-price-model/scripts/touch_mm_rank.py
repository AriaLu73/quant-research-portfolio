#!/usr/bin/env python3
"""MIDCAP-1 汇总(阶段 5 结果 → 阶段 6 候选):从 touch_mm_scan.csv 得每合约的
  无条件净收益(队首口径,含 我方费率 返佣)、按状态桶的净收益与可成交额、最佳状态门控下的 $/天,
  以及"训练(0601/0701/0801)→ 检验(0901)"的稳定性(门控在训练日上选,检验日只报告)。"""
import os
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
S = pd.read_csv(os.path.join(ROOT, "data", "research3", "touch_mm_scan.csv"))
S = S[S.n.notna()]
REB = 0.7
TRAIN = ["20260601", "20260701", "20260801"]; TEST = ["20260901"]
S["day"] = S.day.astype(str)


def agg(g):
    f = g.fill_usd.sum()
    return pd.Series(dict(n=g.n.sum(), fill_usd=f, hs=g.e0.sum() / f, net1=g.e1.sum() / f + REB, net5=g.e5.sum() / f + REB,
                          net30=g.e30.sum() / f + REB, sweep=g.sweep_n.sum() / g.n.sum(), days=g.day.nunique()))


pd.set_option("display.width", 250)
meta = S.groupby("sym").agg(tick_bp=("tick_bp", "median"), spr_med=("spread_med_ticks", "median"), taker_usd_day=("taker_usd", lambda x: x.sum() / S[S.sym == x.name].day.nunique() if False else np.nan))
meta["taker_usd_day"] = S.groupby(["sym", "day"]).taker_usd.first().groupby("sym").mean()
U = S.groupby("sym").apply(agg)
U["usd_day"] = U.fill_usd / U.days
U["pnl_day_5s"] = U.usd_day * U.net5 / 1e4
R = meta.join(U)
print("=== 无条件(队首、贴盘口双边、clip $1k):按 5s 净收益排序 ===")
print(R.sort_values("net5", ascending=False).head(30).to_string(float_format=lambda v: f"{v:,.2f}"))

# 状态门控:训练日上每个 (sym, side, imb, spr) 桶的 net5 > 0 且样本 ≥ 50 → 允许报价;检验日看同门控的表现
rows = []
for sym, g in S.groupby("sym"):
    tr = g[g.day.isin(TRAIN)]; te = g[g.day.isin(TEST)]
    if tr.empty or te.empty:
        continue
    b = tr.groupby(["side", "imb", "spr"]).apply(agg).reset_index()
    ok = b[(b.net5 > 0) & (b.n >= 50)][["side", "imb", "spr"]]
    if ok.empty:
        rows.append(dict(sym=sym, gated_buckets=0)); continue
    trg = tr.merge(ok, on=["side", "imb", "spr"]); teg = te.merge(ok, on=["side", "imb", "spr"])
    a_tr, a_te = agg(trg), agg(teg) if not teg.empty else None
    share = trg.fill_usd.sum() / tr.fill_usd.sum()
    rows.append(dict(sym=sym, gated_buckets=len(ok), train_net5=a_tr.net5, train_usd_day=a_tr.fill_usd / 3, fill_share=share,
                     test_net5=(a_te.net5 if a_te is not None else np.nan), test_usd_day=(a_te.fill_usd if a_te is not None else 0),
                     test_pnl_day=(a_te.fill_usd * a_te.net5 / 1e4 if a_te is not None else 0), test_net1=(a_te.net1 if a_te is not None else np.nan)))
G = pd.DataFrame(rows).set_index("sym").join(meta)
print("\n=== 状态门控(训练 0601/0701/0801 选桶 → 检验 0901),按检验日 $/天 ===")
print(G.sort_values("test_pnl_day", ascending=False).head(30).to_string(float_format=lambda v: f"{v:,.2f}"))
print("\n门控后检验日为正的合约数:", int((G.test_pnl_day > 0).sum()), "/", len(G))
# 哪类状态普遍更好(全部合约合并,训练日)
B = S[S.day.isin(TRAIN)].groupby(["imb", "spr"]).apply(agg)
print("\n=== 状态桶合并(全部合约,训练日):imb = 我方侧队相对对侧;spr = 点差 tick 数 ===")
print(B.to_string(float_format=lambda v: f"{v:,.2f}"))
R.to_csv(os.path.join(ROOT, "data", "research3", "touch_mm_rank_uncond.csv")); G.to_csv(os.path.join(ROOT, "data", "research3", "touch_mm_rank_gated.csv"))
