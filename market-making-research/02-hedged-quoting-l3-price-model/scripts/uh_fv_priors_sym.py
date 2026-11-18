#!/usr/bin/env python3
"""research3:MM-UH-FV2 在其它 USDC 合约上的深度先验(1/k)与到达率先验(A),口径同 mm_uh_fv2(60 秒滚动中位基差、盘口内打印不计、深度按吃单自身时刻)。
用法:Python314/python.exe -X utf8 scripts/research3/uh_fv_priors_sym.py <USDC 原生合约名> <USDT 事件标签> <sk_sb_m0>
  例:XRPUSDCM XRP_B 1.8288   ETHUSDCM ETHUSDTM <sb>   → data/research3/uh_val/fv_priors_<USDC 合约>.json(含 γ(s1))"""
import json, math, os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EV = os.path.join(ROOT, "data", "research2", "events")
SPECS = json.load(open(os.path.join(ROOT, "data", "research2", "kc_contract_specs.json")))
DAYS = ["20260901", "20260902", "20260903", "20260910", "20260911", "20260914", "20260917", "20260918"]
usdc, usdt_tag, sb_m0 = sys.argv[1], sys.argv[2], float(sys.argv[3])
tick_c = float(SPECS[usdc]["tick"])
at = lambda ts, v, t, strict=False: v[np.clip(np.searchsorted(ts, t, "left" if strict else "right") - 1, 0, len(v) - 1)]
rows = []
for day in DAYS:
    pu, pa = os.path.join(EV, f"book_{usdc}_{day}.parquet"), os.path.join(EV, f"book_{usdt_tag}_{day}.parquet")
    if not (os.path.exists(pu) and os.path.exists(pa)):
        print("skip", day); continue
    u = pd.read_parquet(pu, columns=["ts", "bb", "ba"]); a = pd.read_parquet(pa, columns=["ts", "bb", "ba"])
    t = pd.read_parquet(os.path.join(EV, f"trades_{usdc}_{day}.parquet"), columns=["ts", "sgn", "px", "qty"])
    uts, ubb, uba = u.ts.values.astype(np.int64), u.bb.values * tick_c, u.ba.values * tick_c; umid = (ubb + uba) / 2
    ats = a.ts.values.astype(np.int64); am = (a.bb.values + a.ba.values) / 2.0            # tick 单位即可:只用比值的对数差?不,用相对中价 → 需同单位
    am = am * (umid.mean() / am.mean())                                                     # 把 USDT 中价缩放到同一价格单位(只影响常数基差,不影响深度/中位数差)
    g = np.arange(max(uts[0], ats[0]) + 1_000_000, min(uts[-1], ats[-1]), 1_000_000)
    z = (at(uts, umid, g) / at(ats, am, g) - 1.0) * 1e4
    D = pd.Series(z).rolling(60, min_periods=30).median().values
    T = t.assign(p=t.px * tick_c).groupby(["ts", "sgn"]).agg(pmin=("p", "min"), pmax=("p", "max")).reset_index()
    T = T[(T.ts > g[0] + 60_000_000) & (T.ts < g[-1])]
    tt, sg = T.ts.values, T.sgn.values
    near = np.where(sg > 0, T.pmin.values, T.pmax.values); far = np.where(sg > 0, T.pmax.values, T.pmin.values)
    iu = np.clip(np.searchsorted(uts, tt, "left") - 1, 0, len(uts) - 1)
    inside = (near > ubb[iu] + 0.5 * tick_c) & (near < uba[iu] - 0.5 * tick_c)
    f0 = at(ats, am, tt, strict=True) * (1 + D[np.clip(np.searchsorted(g, tt, "left") - 1, 0, len(g) - 1)] / 1e4)
    depth = sg * (far - f0) / f0 * 1e4
    pos = depth[~inside & np.isfinite(depth) & (depth > 0)]
    if len(pos) < 5:
        print("few", day, len(pos)); continue
    rows.append(dict(day=day, takers=len(T), inside=int(inside.sum()), pos=len(pos), invk=float(pos.mean()), k=float(1 / pos.mean()), rate=float(len(pos) / ((g[-1] - g[0]) / 1e6)),
                     half_spread_bp=float(np.median((uba - ubb) / umid * 1e4 / 2))))
R = pd.DataFrame(rows); pd.set_option("display.width", 200); print(R.round(4).to_string(index=False))
mk, vk = R.k.mean(), R.k.var(ddof=1); mA, vA = R.rate.mean(), R.rate.var(ddof=1)
sig = math.sqrt(math.pi / 2) * sb_m0
out = dict(usdc=usdc, days=R.day.tolist(), fl_k_alpha0=float(mk * mk / vk), fl_k_beta0=float(mk / vk), sk_A_alpha0=float(mA * mA / vA), sk_A_beta0=float(mA / vA),
           invk_ref=float(1 / mk), A_ref=float(mA), sk_gamma_s1=float(2 * mA * mk / (sig * sig * math.e)), half_spread_bp=float(R.half_spread_bp.median()))
print({k: (round(v, 5) if isinstance(v, float) else v) for k, v in out.items() if k != "days"})
json.dump(out, open(os.path.join(ROOT, "data", "research3", "uh_val", f"fv_priors_{usdc}.json"), "w"), indent=1)
