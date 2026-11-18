#!/usr/bin/env python3
"""research5: per-contract microstructure facts from the two-venue recordings (descriptive; no strategy).

tick size in bp, spread in ticks, share of time at a one-tick spread, displayed size at the touch, real (non-paired) taker
flow, share of paired prints, and eta = continuations / (2 x alternations) of successive trade-price changes
(Robert & Rosenbaum's measure: eta < 1/2 = prices bounce at the tick level, the tick is large for this asset).
Usage: Python314/python.exe scripts/research5/contract_landscape.py 20261002
"""
import glob, json, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import active_mm_study as A
import kucoin_trades as KT


def eta(px):
    """continuations / (2 x alternations) over the non-zero changes of a price series; NaN without alternations."""
    d = np.sign(np.diff(px))
    d = d[d != 0]
    if len(d) < 3:
        return np.nan
    same = d[1:] == d[:-1]
    na, nc = int((~same).sum()), int(same.sum())
    return nc / (2 * na) if na else np.nan


def time_weighted(t, x):
    w = np.diff(t).astype(float)
    return float(np.sum(x[:-1] * w) / w.sum()) if w.sum() > 0 else np.nan


def main():
    day = sys.argv[1]
    spec = {x["symbol"]: x for x in json.load(open(os.path.join(A.ROOT, "data", "research4", "contracts_active_20261001.json"), encoding="utf-8"))["data"]}
    syms = sorted({os.path.basename(f).split("_")[1] for f in glob.glob(os.path.join(A.KU, day, "*_l2.jsonl.gz"))})
    rows = []
    for sym in syms:
        if sym not in spec:
            continue
        tick, mult = float(spec[sym]["tickSize"]), float(spec[sym]["multiplier"])
        bbo = A.build_bbo(day, sym)
        real, prints = A.load_orders(day, sym, mult)
        if prints is None or len(bbo) < 1000:
            continue
        t = bbo.t.to_numpy(np.int64)
        mid = ((bbo.bb + bbo.ba) / 2).to_numpy(float)
        spread_ticks = np.round((bbo.ba - bbo.bb) / tick).to_numpy(float)
        hours = (t[-1] - t[0]) / 3.6e6
        o = KT.to_orders(prints, {sym: mult})
        nonpair = prints[~((prints.age_ms <= KT.PAIR_AGE_MS) & ~prints.liq)].sort_values("ts")
        rows.append(dict(sym=sym[:-5], tick_bp=tick / np.median(mid) * 1e4, spread_ticks=time_weighted(t, spread_ticks),
                         one_tick_share=time_weighted(t, (spread_ticks <= 1).astype(float)),
                         half_spread_bp=time_weighted(t, (bbo.ba - bbo.bb).to_numpy(float) / mid / 2 * 1e4),
                         touch_usd=time_weighted(t, ((bbo.bq * bbo.bb + bbo.aq * bbo.ba) / 2).to_numpy(float) * mult),
                         real_usd_day=o.usd[~o.pair].sum() / hours * 24, pair_share=o.usd[o.pair].sum() / o.usd.sum(),
                         order_usd_median=o.usd[~o.pair].median(), eta_trades=eta(nonpair.px.to_numpy(float)),
                         eta_mid=eta(mid), mid_changes_per_min=(np.diff(mid) != 0).sum() / hours / 60))
    d = pd.DataFrame(rows).sort_values("tick_bp", ascending=False)
    pd.set_option("display.width", 250)
    print(d.round(2).to_string(index=False))
    d.to_csv(os.path.join(A.CACHE, f"landscape_{day}.csv"), index=False)


if __name__ == "__main__":
    main()
