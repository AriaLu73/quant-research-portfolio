#!/usr/bin/env python3
"""research5 FL-1: is mechanical (TWAP-like) taker flow on KuCoin mid-cap perps benign for a resting quote?

Pre-registration: docs/research5/experiments.md, card FL-1. Literature: Barone & Lillo 2026 (visible TWAPs carry little
information), Zhai 2026 (adverse selection is concentrated in a tail of takers) - docs/research5/lit_active_mm_alt_B.md.
A TWAP-like run = taker orders of one contract and one direction with the same size (within 2 %) arriving at regular
intervals (each gap within 20 % of the run's median gap, gaps between 1 s and 600 s). A child is "anticipated" from the
fifth member of a run on: the first four could have been observed before it arrived.
Measurement as in B-1: a queue-front quote of $1,000 resting at the touch 2 ms before the taker order; net = mark-out to the
KuCoin mid after 1 / 5 / 300 s + OUR_FEE rebate.
Usage: Python314/python.exe scripts/research5/flow_types.py 20261002
"""
import glob, json, os, sys
from dataclasses import replace

import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import active_mm_study as A
import stale_take_replay as S

SIZE_TOL = 0.02
GAP_TOL = 0.20
GAP_MIN_MS, GAP_MAX_MS = 1_000, 600_000
RUN_MIN = 5
MIN_USD = 20.0


def twap_run_index(t_ms, usd):
    """For the orders of one contract and one direction (time-ordered): position of each order inside a TWAP-like run
    (1 = no run or the first member). Orders below MIN_USD are never members."""
    out = np.ones(len(t_ms), dtype=np.int64)
    runs = {}                                                       # size bucket -> (count, last time, gaps)
    for i, (t, u) in enumerate(zip(t_ms, usd)):
        if not (u >= MIN_USD):
            continue
        key = int(round(np.log(u) / np.log(1.0 + SIZE_TOL)))
        best = None
        for k in (key - 1, key, key + 1):                           # the same size may fall on either side of a bucket edge
            r = runs.get(k)
            if r is not None and abs(u / r[3] - 1.0) <= SIZE_TOL and (best is None or r[1] > best[1][1]):
                best = (k, r)
        cnt, gaps = 1, []
        if best is not None:
            _, (c0, t0, g0, _) = best
            gap = t - t0
            if GAP_MIN_MS <= gap <= GAP_MAX_MS and (not g0 or abs(gap / np.median(g0) - 1.0) <= GAP_TOL):
                cnt, gaps = c0 + 1, g0 + [gap]
            runs.pop(best[0], None)
        runs[key] = (cnt, t, gaps, u)
        out[i] = cnt
    return out


def main():
    day = sys.argv[1]
    spec = {x["symbol"]: x for x in json.load(open(os.path.join(A.ROOT, "data", "research4", "contracts_active_20261001.json"), encoding="utf-8"))["data"]}
    bn = A.load_binance(day)
    syms = sorted({os.path.basename(f).split("_")[1] for f in glob.glob(os.path.join(A.KU, day, "*_l2.jsonl.gz"))})
    parts = []
    for sym in syms:
        b = bn.get(A.binance_symbol(sym))
        if sym not in spec or b is None:
            continue
        bbo = A.build_bbo(day, sym)
        if len(bbo) < 1000:
            continue
        tick, mult = float(spec[sym]["tickSize"]), float(spec[sym]["multiplier"])
        real, _ = A.load_orders(day, sym, mult)
        real = real.reset_index(drop=True)
        real["run"] = 1
        for sgn in (1, -1):
            m = (real.sgn == sgn).to_numpy()
            real.loc[m, "run"] = twap_run_index(real.t.to_numpy(np.int64)[m], real.usd.to_numpy(float)[m])
        mk = S.Market(bbo, b[0], b[1], A.BASE, tick, mult)
        d = A.protection_rows({"S600": mk}, real, A.BASE.clip_usd, A.BASE.order_lat_ms)
        d = d.merge(real[["t", "sgn", "usd", "run"]].rename(columns={"usd": "order_usd"}).drop_duplicates(["t", "sgn"]), on=["t", "sgn"], how="left")
        parts.append(d.assign(sym=sym))
        print("  done", sym, len(d), "fills,", int((d.run >= RUN_MIN).sum()), "anticipated TWAP children", flush=True)
    d = pd.concat(parts, ignore_index=True)
    d.to_parquet(os.path.join(A.CACHE, f"flow_types_{day}.parquet"))
    hours = (d.t.max() - d.t.min()) / 3.6e6
    w = lambda x, c: float((x[c] * x.usd).sum() / x.usd.sum()) if len(x) else np.nan
    print(f"\nFL-1 {day}: {len(d)} fills, {hours:.1f} h; net = mark-out to the KuCoin mid + OUR_FEE rebate, usd-weighted bp")
    print("group | fills | $/day | share of $ | net 1 s | 5 s [95 %] | 300 s [95 %] | contracts>0 at 5 s")
    for name, x in (("anticipated TWAP child (5th+ of a run)", d[d.run >= RUN_MIN]), ("early member of a run (2nd-4th)", d[(d.run >= 2) & (d.run < RUN_MIN)]),
                    ("everything else", d[d.run < 2]), ("all", d)):
        if not len(x):
            print(f"{name}: none")
            continue
        lo5, hi5 = A.protect_ci(x, "net_5000")
        lo3, hi3 = A.protect_ci(x, "net_300000")
        per = x.assign(p=x.net_5000 * x.usd).groupby("sym").agg(n=("p", "size"), p=("p", "sum"))
        big = per[per.n >= 20]
        print(f"{name:40s} | {len(x):6d} | {x.usd.sum() / hours * 24:12,.0f} | {x.usd.sum() / d.usd.sum():6.1%} | {w(x, 'net_1000'):+6.2f} | {w(x, 'net_5000'):+6.2f} [{lo5:+.2f}, {hi5:+.2f}]"
              f" | {w(x, 'net_300000'):+6.2f} [{lo3:+.2f}, {hi3:+.2f}] | {int((big.p > 0).sum())}/{len(big)}")
    tw = d[d.run >= RUN_MIN]
    if len(tw):
        g = tw.groupby("sym").agg(fills=("usd", "size"), usd=("usd", "sum"), order_usd=("order_usd", "median"))
        g["net5"] = tw.assign(p=tw.net_5000 * tw.usd).groupby("sym").p.sum() / g.usd
        print("\nanticipated TWAP children by contract")
        print(g.sort_values("usd", ascending=False).round(2).head(15).to_string())


if __name__ == "__main__":
    main()
