#!/usr/bin/env python3
"""毒性过滤做市的回合结算(流程阶段 6,不用 markout 假设):检验日上,两侧始终在显示最优价(小 tick 合约可用内 1 tick 抢到最前,代价 ≤ 0.1 bp 忽略),
只在模型预测毛收益 > −返佣 时保留该侧挂单;真实吃单打到该侧 → 成交 min(clip, 吃单额);库存上限 ±3 clip;日末按中价平;含返佣。
对照:不过滤(一直挂)。模型 = tox_analyze 同款(训练日拟合,默认超参)。"""
import os, sys
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
name = sys.argv[1]; REB = float(sys.argv[2]) if len(sys.argv) > 2 else 0.7; CAP, CLIP = 3, 1000.0
D = pd.read_parquet(os.path.join(ROOT, "data", "research3", f"tox_{name}.parquet")); D["day"] = D.day.astype(str)
FE = [c for c in ["own_r_0.1", "own_r_1", "own_r_10", "lead_r_0.1", "lead_r_1", "lead_r_10", "gap", "flow_1", "flow_10", "imb", "spr", "half_bp", "vol60", "age", "dt_last"] if c in D]
rows = []
for s, X in D.groupby("sym"):
    days = sorted(X.day.unique()); tr_d, te_d = days[:len(days) // 2], days[len(days) // 2:]
    tr = X[X.day.isin(tr_d)]
    if len(tr) < 2000:
        continue
    m = HistGradientBoostingRegressor(random_state=0).fit(tr[FE].values, tr.e5.clip(-50, 50).values, sample_weight=tr.f.values)
    for d in te_d:
        te = X[X.day == d].sort_values("ts"); pred = m.predict(te[FE].values)
        for label, keep in (("filter", pred > -REB), ("always", np.ones(len(te), bool))):
            pos = cash = vol = 0.0; n = 0
            for sg, px, f, k, m0 in zip(te.sg.values, te.px.values, te.f.values, keep, te.mid0.values):
                if not k:
                    continue
                dd = -sg; pu = pos * m0
                if (dd > 0 and pu >= CAP * CLIP - 1e-9) or (dd < 0 and pu <= -CAP * CLIP + 1e-9):
                    continue
                pos += dd * f / px; cash -= dd * f; vol += f; n += 1
            leg = cash + pos * te.mid_end.iloc[0]
            rows.append(dict(sym=s, day=d, mode=label, fills=n, vol=vol, leg=leg, net=leg + vol * REB / 1e4, end_pos=pos * te.mid_end.iloc[0]))
R = pd.DataFrame(rows); R.to_csv(os.path.join(ROOT, "data", "research3", f"tox_replay_{name}.csv"), index=False)
pd.set_option("display.width", 220)
g = R.groupby(["sym", "mode"]).agg(days=("day", "size"), net=("net", "sum"), pos_days=("net", lambda x: int((x > 0).sum())), worst=("net", "min"), best=("net", "max"), vol_day=("vol", "mean"), leg=("leg", "sum"))
g["net_bp"] = g.net / (g.vol_day * g.days) * 1e4
print(g.round(2).to_string())
t = R.groupby(["mode", "day"]).agg(net=("net", "sum"), vol=("vol", "sum")).reset_index()
print("\n全部合约合计,按日:"); print(t.pivot(index="day", columns="mode", values="net").round(1).to_string())
print(t.groupby("mode").agg(net=("net", "sum"), vol=("vol", "sum"), pos_days=("net", lambda x: int((x > 0).sum())), days=("net", "size")).round(0).to_string())
