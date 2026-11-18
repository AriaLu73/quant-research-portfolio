#!/usr/bin/env python3
"""毒性可预测性分析:训练 = 前一半交易日,检验 = 后一半(按日期排序,事先写定)。
① 单变量:训练日五分位切点 → 检验日各分位的挂单方 5 s / 30 s 毛收益(clip 加权 bp)。
② 模型:sklearn HistGradientBoostingRegressor(默认超参,不调)按合约拟合 e5;检验日按预测排序,报告"只在预测净收益 > 0 时挂"的实际净收益与保留成交额占比。
用法:python tox_analyze.py commod"""
import os, sys
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
name = sys.argv[1]
D = pd.read_parquet(os.path.join(ROOT, "data", "research3", f"tox_{name}.parquet"))
D["day"] = D.day.astype(str)
REB = float(sys.argv[2]) if len(sys.argv) > 2 else 0.7
FE = [c for c in ["own_r_0.1", "own_r_1", "own_r_10", "lead_r_0.1", "lead_r_1", "lead_r_10", "gap", "flow_1", "flow_10", "imb", "spr", "half_bp", "vol60", "age", "dt_last"] if c in D]
pd.set_option("display.width", 250)
def wm(x, c):
    return float((x[c] * x.f).sum() / x.f.sum()) if len(x) and x.f.sum() else np.nan
summ = []
for s, X in D.groupby("sym"):
    days = sorted(X.day.unique()); tr_d, te_d = days[:len(days) // 2], days[len(days) // 2:]
    tr, te = X[X.day.isin(tr_d)], X[X.day.isin(te_d)]
    if len(tr) < 2000 or len(te) < 2000:
        continue
    print(f"\n================ {s}: 训练 {tr_d[0]}–{tr_d[-1]} n={len(tr)},检验 {te_d[0]}–{te_d[-1]} n={len(te)};无条件 e5 训练 {wm(tr, 'e5'):+.2f} 检验 {wm(te, 'e5'):+.2f} bp;e30 检验 {wm(te[te.v30], 'e30'):+.2f}")
    if name == "commod" or len(sys.argv) > 3:
        rows = []
        for c in FE:
            qs = np.unique(tr[c].quantile([.2, .4, .6, .8]).values)
            bt = np.searchsorted(qs, te[c].values, side="right")
            r = dict(feature=c)
            for q in range(len(qs) + 1):
                v = te[bt == q]; r[f"q{q + 1}_e5"] = wm(v, "e5"); r[f"q{q + 1}_share"] = v.f.sum() / te.f.sum()
            rows.append(r)
        print(pd.DataFrame(rows).round(2).to_string(index=False))
    m = HistGradientBoostingRegressor(random_state=0).fit(tr[FE].values, tr.e5.clip(-50, 50).values, sample_weight=tr.f.values)
    te = te.assign(pred=m.predict(te[FE].values))
    out = dict(sym=s, n_te=len(te), f_te_day=te.f.sum() / len(te_d), e5_all=wm(te, "e5"), e30_all=wm(te[te.v30], "e30"), corr=float(np.corrcoef(te.pred, te.e5.clip(-50, 50))[0, 1]))
    line = []
    for thr in (-REB, -REB + 0.3, -REB + 0.6):
        k = te[te.pred > thr]
        line.append(f"预测毛 > {thr:+.1f}: 保留 {k.f.sum() / te.f.sum():.0%} 额、${k.f.sum() / len(te_d):,.0f}/天,实际净5s {wm(k, 'e5') + REB:+.2f} 净30s {wm(k[k.v30], 'e30') + REB:+.2f} 净300s {wm(k[k.v300], 'e300') + REB:+.2f} bp,正天数 {int((k.groupby('day').apply(lambda x: wm(x, 'e5'), include_groups=False) + REB > 0).sum())}/{k.day.nunique()}")
        if thr == -REB:
            out.update(keep=k.f.sum() / te.f.sum(), keep_usd_day=k.f.sum() / len(te_d), net5=wm(k, "e5") + REB, net30=wm(k[k.v30], "e30") + REB, net300=wm(k[k.v300], "e300") + REB,
                       pos_days=int((k.groupby("day").apply(lambda x: wm(x, "e5"), include_groups=False) + REB > 0).sum()), te_days=k.day.nunique())
    print("  模型(检验日): corr %.3f" % out["corr"]); [print("   ", x) for x in line]
    # 十分位
    te["dec"] = pd.qcut(te.pred, 10, labels=False, duplicates="drop")
    dd = te.groupby("dec").apply(lambda x: pd.Series(dict(share=x.f.sum() / te.f.sum(), pred=wm(x, "pred"), e5=wm(x, "e5"), e30=wm(x[x.v30], "e30"), e300=wm(x[x.v300], "e300"))), include_groups=False)
    print(dd.round(2).T.to_string())
    summ.append(out)
S = pd.DataFrame(summ)
print("\n== 汇总(检验日;阈值 = 预测毛收益 > −返佣)=="); print(S.round(3).sort_values("net5", ascending=False).to_string(index=False))
S.to_csv(os.path.join(ROOT, "data", "research3", f"tox_{name}_summary.csv"), index=False)
