#!/usr/bin/env python3
"""research3:MM-UH-FV 的吃单深度先验(1/k)与到达率先验(A),按新口径在 9 月训练日上重估。
口径 = strategies/research3/mm_uh_fv.py:公允价 = USDT 中价 × (1 + 基差 60 秒滚动中位数);吃单 = 同毫秒同向成交合并、取最远价;
成交价严格在当时 USDC 买一卖一之间的不计;深度相对该吃单到达时刻的公允价;只用正深度。
先验(与 scripts/research2/u14_priors.py / u15_prep.py 同法):各日 MLE k = 1 / 正深度均值 → Gamma(α = m²/v, β = m/v);各日到达率同理。
训练日 = 9 月 8 个训练日的全天数据。输出 data/research3/uh_val/fv_priors.json。用法:Python314/python.exe -X utf8 scripts/research3/uh_fv_priors.py"""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uh_val as V

DAYS = ["20260901", "20260902", "20260903", "20260910", "20260911", "20260914", "20260917", "20260918"]
WIN = 60
rows = []
for day in DAYS:
    d = V.day_data(day); ats, amid, uts = d["ats"], d["amid"], d["uts"]; umid = (d["ubb"] + d["uba"]) / 2
    g = np.arange(max(uts[0], ats[0]) + 1_000_000, min(uts[-1], ats[-1]), 1_000_000)
    z = (V.at(uts, umid, g) / V.at(ats, amid, g) - 1.0) * 1e4
    D = pd.Series(z).rolling(WIN, min_periods=30).median().values
    t = d["tr"]; t = t.assign(p=t.px * V.TICK)
    T = t.groupby(["ts", "sgn"]).agg(pmin=("p", "min"), pmax=("p", "max")).reset_index()
    T = T[(T.ts > g[0] + 60_000_000) & (T.ts < g[-1])]
    tt, sg = T.ts.values, T.sgn.values
    near = np.where(sg > 0, T.pmin.values, T.pmax.values); far = np.where(sg > 0, T.pmax.values, T.pmin.values)
    iu = np.clip(np.searchsorted(uts, tt, "left") - 1, 0, len(uts) - 1)
    inside = (near > d["ubb"][iu] + 0.5 * V.TICK) & (near < d["uba"][iu] - 0.5 * V.TICK)
    Dt = D[np.clip(np.searchsorted(g, tt, "left") - 1, 0, len(g) - 1)]
    f0 = V.at(ats, amid, tt, strict=True) * (1 + Dt / 1e4)
    depth = sg * (far - f0) / f0 * 1e4
    ok = ~inside & np.isfinite(depth)
    pos = depth[ok & (depth > 0)]
    secs = (g[-1] - g[0]) / 1e6
    rows.append(dict(day=day, takers=int(len(T)), inside=int(inside.sum()), counted=int(ok.sum()), pos=int(len(pos)), invk=float(pos.mean()), k=float(1 / pos.mean()), rate=float(len(pos) / secs)))
R = pd.DataFrame(rows); pd.set_option("display.width", 200); print(R.round(4).to_string(index=False))
mk, vk = R.k.mean(), R.k.var(ddof=1); mA, vA = R.rate.mean(), R.rate.var(ddof=1)
out = dict(days=DAYS, basis_win_s=WIN, fl_k_alpha0=float(mk * mk / vk), fl_k_beta0=float(mk / vk), sk_A_alpha0=float(mA * mA / vA), sk_A_beta0=float(mA / vA),
           invk_ref=float(1 / mk), A_ref=float(mA))
print(f"k 先验:α0 = {out['fl_k_alpha0']:.2f},β0 = {out['fl_k_beta0']:.2f} bp → 先验 1/k = {out['fl_k_beta0'] / out['fl_k_alpha0']:.2f} bp(现用 12.87 / 81.14 → 6.31 bp)")
print(f"A 先验:α = {out['sk_A_alpha0']:.3f},β = {out['sk_A_beta0']:.1f} s → {out['A_ref']:.5f}/s = {out['A_ref'] * 3600:.1f}/小时(现用 0.452 / 27.65 → 0.01636/s)")
json.dump(out, open(os.path.join(V.OUT, "fv_priors.json"), "w"), indent=1)
