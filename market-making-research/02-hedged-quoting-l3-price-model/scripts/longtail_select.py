#!/usr/bin/env python3
"""长尾体检:按第 19 节预注册规则选合约(09-10/18/24),并(若已有)报告检验日 09-21。用法:python longtail_select.py [test]"""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = pd.read_csv(os.path.join(ROOT, "data", "research3", "longtail_scan.csv"))
if "error" in D:
    print("出错:", int(D.error.notna().sum())); D = D[D.error.isna()]
D["day"] = D.day.astype(int).astype(str)
SEL_DAYS, TEST = ["20260910", "20260918", "20260924"], "20260921"
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
S = D[D.day.isin(SEL_DAYS) & (D.n_at > 0)]
print("== 全体概览(选择期三天,每 (合约,日) 一行)==")
print(f"合约 {S.sym.nunique()};真实挂单方 5 s 净(含返佣)> 0 的 (合约,日) 占 {((S.e5 + S.reb) > 0).mean():.1%};300 s 净 > 0 占 {((S.e300 + S.reb) > 0).mean():.1%};现金结算($200 clip)> 0 占 {(S.net200 > 0).mean():.1%}")
def agg(X):
    w = X.at_f
    return pd.Series(dict(days=len(X), pos_days=int((X.net200 > 0).sum()), net200=X.net200.sum(), vol200=X.vol200.sum(), net1000=X.net1000.sum(), vol1000=X.vol1000.sum(),
                          e5=np.average(X.e5.fillna(0), weights=w) if w.sum() else np.nan, e300=np.average(X.e300.fillna(0), weights=w) if w.sum() else np.nan,
                          reb=X.reb.iloc[0], at_f_day=w.sum() / len(X), real_day=X.real_usd.sum() / len(X), pair=np.average(X.pair_share, weights=X.taker_usd), spr=X.spr_med.median(),
                          half_bp=X.half_bp.median(), cls=X.cls.iloc[0]))
G = S.groupby("sym").apply(agg, include_groups=False)
G["net300"] = G.e300 + G.reb; G["bp200"] = G.net200 / G.vol200 * 1e4
sel = G[(G.net200 > 0) & (G.pos_days >= 2) & (G.net300 > 0) & (G.at_f_day >= 10000) & (G.days == 3)]
print(f"\n== 入选(预注册三条件)== {len(sel)} 个 / {len(G)};按类别:{sel.cls.value_counts().to_dict()}")
print(f"选择期合计($200 clip):净 ${sel.net200.sum():,.0f} / 成交额 ${sel.vol200.sum():,.0f} = {sel.net200.sum() / sel.vol200.sum() * 1e4:+.2f} bp;日均成交额 ${sel.vol200.sum() / 3:,.0f}(月 ${sel.vol200.sum() / 3 * 30 / 1e6:.1f}M);$1k clip:净 ${sel.net1000.sum():,.0f} / ${sel.vol1000.sum():,.0f}")
print(sel.sort_values("net200", ascending=False)[["cls", "pos_days", "net200", "vol200", "bp200", "e5", "e300", "net300", "at_f_day", "real_day", "pair", "spr", "half_bp"]].head(40).round(2).to_string())
sel.index.to_series().to_csv(os.path.join(ROOT, "data", "research3", "longtail_selected.txt"), index=False, header=False)
print("\n条件逐条的通过数:", dict(net200_pos=int((G.net200 > 0).sum()), pos_days2=int((G.pos_days >= 2).sum()), net300_pos=int((G.net300 > 0).sum()), flow10k=int((G.at_f_day >= 10000).sum())))
if len(sys.argv) > 1:
    T = D[(D.day == TEST) & D.sym.isin(sel.index)]
    if len(T):
        w = T.at_f; e300 = np.average(T.e300.fillna(0), weights=w); reb = np.average(T.reb, weights=w)
        print(f"\n== 检验日 {TEST}:入选 {len(sel)} 个里有数据 {len(T)} 个 ==")
        for k in (200, 1000):
            net, vol = T[f"net{k}"].sum(), T[f"vol{k}"].sum()
            print(f"clip ${k}:净 ${net:,.0f} / 成交额 ${vol:,.0f} = {net / vol * 1e4:+.2f} bp;正合约 {int((T[f'net{k}'] > 0).sum())}/{len(T)}({(T[f'net{k}'] > 0).mean():.0%});外推月成交额 ${vol * 30 / 1e6:.1f}M、月净 ${net * 30:,.0f}")
        net, vol = T.net200.sum(), T.vol200.sum()
        c1, c2, c3, c4 = net > 0, (T.net200 > 0).mean() >= 0.55, net / vol * 1e4 >= 1.0, e300 + reb > 0
        print(f"真实挂单方 5 s 毛 {np.average(T.e5.fillna(0), weights=w):+.2f}、300 s 毛 {e300:+.2f} bp(返佣 {reb:.2f})")
        print(f"预注册标准($200 clip):① 组合净利 > 0:{c1} ② 正合约 ≥ 55%:{c2} ③ 净 ≥ +1.0 bp:{c3} ④ 300 s 毛 + 返佣 > 0:{c4}"); print("结论:", "通过(候选)" if (c1 and c2 and c3 and c4) else "不通过")
        print(T.sort_values("net200")[["sym", "net200", "vol200", "e5", "e300", "at_f", "endpos200"]].round(1).to_string(index=False))
