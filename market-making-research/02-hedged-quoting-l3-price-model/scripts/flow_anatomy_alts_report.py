#!/usr/bin/env python3
"""flow_anatomy_alts.csv 汇总:每合约 7 天合并——成对打印占比、真实吃单额/天、真实挂单方在显示最优价的毛收益(bp,我方费率 返佣为净)。"""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = pd.read_csv(os.path.join(ROOT, "data", "research3", "flow_anatomy_alts.csv"))
if "error" in D:
    print("errors:", int(D.error.notna().sum())); D = D[D.error.isna()]
pd.set_option("display.width", 260); pd.set_option("display.max_rows", 200)
def agg(X):
    def w(c, f="at_f"):
        m = X[c].notna() & (X[f] > 0)
        return float((X.loc[m, c] * X.loc[m, f]).sum() / X.loc[m, f].sum()) if m.any() else np.nan
    return pd.Series(dict(days=len(X), taker_day=X.taker_usd.sum() / len(X), pair=X.taker_usd.mul(X.pair_share).sum() / X.taker_usd.sum(), real_day=X.real_usd.sum() / len(X),
                          spr=X.spr_med.median(), tick_bp=X.tick_bp.median(), e1=w("at_e1"), e5=w("at_e5"), e30=w("at_e30"), e300=w("at_e300"),
                          partial_e5=w("partial_e5", "partial_f"), thru_e5=w("thru_e5", "thru_f"), partial_share=X.partial_f.sum() / max(1e-9, X.at_f.sum()),
                          spr1_e5=w("spr1_e5", "spr1_f"), spr2_e5=w("spr2_e5", "spr2_f"), spr3p_e5=w("spr3p_e5", "spr3p_f"),
                          same_e5=w("same_big_e5", "same_big_f"), opp_e5=w("opp_big_e5", "opp_big_f"), pos_days_e5=int((X.at_e5 + 0.7 > 0).sum())))
A = D.groupby("sym").apply(agg, include_groups=False)
A["net5"] = A.e5 + 0.7; A["net30"] = A.e30 + 0.7
print("全体(74 合约)分布:成对打印占比 分位 10/50/90% =", A.pair.quantile([.1, .5, .9]).round(2).tolist(), ";net5 分位 =", A.net5.quantile([.1, .5, .9]).round(2).tolist())
print("net5 > 0 的合约数:", int((A.net5 > 0).sum()), "/", len(A), ";net30 > 0:", int((A.net30 > 0).sum()))
cols = ["days", "taker_day", "pair", "real_day", "spr", "tick_bp", "e1", "e5", "e30", "e300", "net5", "net30", "pos_days_e5", "partial_share", "partial_e5", "thru_e5", "spr1_e5", "spr2_e5", "spr3p_e5", "same_e5", "opp_e5"]
print("\n== 按 net5(真实挂单方 5 s 净收益,含返佣)排序 ==")
print(A.sort_values("net5", ascending=False)[cols].round(2).to_string())
A.to_csv(os.path.join(ROOT, "data", "research3", "flow_anatomy_alts_bysym.csv"))
# 成对占比 vs 点差 的关系
A["sprb"] = pd.cut(A.spr, [0, 1, 2, 4, 9, 1000], labels=["1", "2", "3-4", "5-9", "10+"])
print("\n== 按点差中位(tick)分组:合约数、成对占比中位、真实流量/天中位、net5 中位 ==")
print(A.groupby("sprb", observed=True).agg(n=("pair", "size"), pair=("pair", "median"), real_day=("real_day", "median"), taker_day=("taker_day", "median"), net5=("net5", "median"), net30=("net30", "median"),
                                            partial_e5=("partial_e5", "median"), thru_e5=("thru_e5", "median")).round(2).to_string())
