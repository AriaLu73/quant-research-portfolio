import sys, json, glob, os, numpy as np, pandas as pd
from dataclasses import replace
sys.path.insert(0, "scripts/research5")
import active_mm_study as A
spec = {x["symbol"]: x for x in json.load(open("data/research4/contracts_active_20261001.json", encoding="utf-8"))["data"]}
day = sys.argv[1]
bn = A.load_binance(day)
syms = sorted({os.path.basename(f).split("_")[1] for f in glob.glob(os.path.join(A.KU, day, "*_l2.jsonl.gz"))})
cases = [(0, 1), (1, 1), (0, 2), (1, 2), (2, 2), (3, 2), (5, 2), (10, 2), (50, 2), (1000, 2)]
parts = {c: [] for c in cases}
for sym in syms:
    b = bn.get(A.binance_symbol(sym))
    bbo = A.build_bbo(day, sym)
    if b is None or len(bbo) < 1000 or sym not in spec:
        continue
    real, _ = A.load_orders(day, sym, float(spec[sym]["multiplier"]))
    tick, mult = float(spec[sym]["tickSize"]), float(spec[sym]["multiplier"])
    for c in cases:
        mk = A.JumpMarket(bbo, b[0], b[1], replace(A.BASE, ref_lag_ms=c[0]), tick, mult, 20)
        d = A.protection_rows({"J20": mk}, real, 1000.0, c[1], quote_lead_ms=1)
        if len(d):
            parts[c].append(d.assign(sym=sym))
w = lambda x, c: float((x[c] * x.usd).sum() / x.usd.sum()) if len(x) else float("nan")
print(f"{day}: touch quote kept only while its margin to the jump fair value (W = 20 ms) is >= 0; net incl. OUR_FEE rebate, usd-weighted bp")
print("Binance age ms | cancel lead ms | total | flagged | flagged net 1 s | kept: 1 s | 5 s [lower] | 300 s [lo, hi] | kept $/day | contracts>0 at 300 s")
for c in cases:
    d = pd.concat(parts[c], ignore_index=True)
    hours = (d.t.max() - d.t.min()) / 3.6e6
    g = d.g_J20
    k, cut = d[g >= 0], d[g < 0]
    lo5, _ = A.protect_ci(k, "net_5000")
    lo, hi = A.protect_ci(k, "net_300000")
    per = k.assign(p=k.net_300000 * k.usd).groupby("sym").agg(n=("p", "size"), p=("p", "sum"))
    big = per[per.n >= 20]
    print(f"{c[0]:14d} | {c[1]:14d} | {c[0] + c[1]:5d} | all 1 s {w(d, 'net_1000'):+.2f} n {len(d)} | {cut.usd.sum() / d.usd.sum():6.1%} | {w(cut, 'net_1000'):+15.2f} | {w(k, 'net_1000'):+9.2f} | {w(k, 'net_5000'):+5.2f} [{lo5:+.2f}] | {w(k, 'net_300000'):+5.2f} [{lo:+.2f}, {hi:+.2f}]"
          f" | {k.usd.sum() / hours * 24:12,.0f} | {int((big.p > 0).sum())}/{len(big)}")
