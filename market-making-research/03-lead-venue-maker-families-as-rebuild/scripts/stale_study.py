#!/usr/bin/env python3
"""research5: gaps in the reference (USDT contract) book feed on the training days, and how far the mid moved across them.

Questions for the stale-reference threshold (anchor_stale_ms, still U15's fixed 2 s):
  1. phi-accrual thresholds: the gap exceeded once a day / once an hour / once a minute in normal operation
     (Hayashibara phi detector with the empirical survival function; docs/research2/lit_stale_quote.md s3.3).
  2. Is a gap dangerous? |mid move across the gap| by gap length, against sigma_ref x sqrt(gap) (what a diffusion would do).
Input: data/research2/events/book_<SYM>_<day>.parquet (ts microseconds; every L1 book event of the USDT contract).
Usage: python scripts/research5/stale_study.py BTC_B       (Python314; reads only)
"""
import os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAYS = ["20260901", "20260902", "20260903", "20260910", "20260911", "20260914", "20260917", "20260918"]


def gap_threshold(gaps_s, seconds, per_day):
    """Gap length exceeded `per_day` times a day on average: the (1 - per_day x days / n) quantile of the gaps."""
    k = per_day * seconds / 86400.0
    n = len(gaps_s)
    return float(np.quantile(gaps_s, max(0.0, 1.0 - k / n))) if n else float("nan")


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTC_B"
    rows, allg, allm, secs = [], [], [], 0.0
    for d in DAYS:
        b = pd.read_parquet(os.path.join(ROOT, "data", "research2", "events", f"book_{sym}_{d}.parquet"), columns=["ts", "bb", "ba"])
        ts = b.ts.to_numpy().astype(np.int64)
        mid = (b.bb.to_numpy() + b.ba.to_numpy()) / 2.0
        g = np.diff(ts) / 1e6
        mv = np.abs(mid[1:] / mid[:-1] - 1) * 1e4
        s = (ts[-1] - ts[0]) / 1e6
        rows.append((d, len(g), gap_threshold(g, s, 1), gap_threshold(g, s, 24), gap_threshold(g, s, 1440), int((g > 2).sum()), int((g > 10).sum())))
        allg.append(g); allm.append(mv); secs += s
    print("day       events   once/day  once/hour  once/min   gaps>2s  gaps>10s")
    for r in rows:
        print(f"{r[0]}  {r[1]:8d}  {r[2]:7.2f}s  {r[3]:7.2f}s  {r[4]:7.2f}s  {r[5]:7d}  {r[6]:7d}")
    g, mv = np.concatenate(allg), np.concatenate(allm)
    print(f"pooled ({secs / 86400:.1f} days): once/day {gap_threshold(g, secs, 1):.2f} s, once/hour {gap_threshold(g, secs, 24):.2f} s, once/minute {gap_threshold(g, secs, 1440):.2f} s; "
          f"median over days once/day {np.median([r[2] for r in rows]):.2f} s, once/hour {np.median([r[3] for r in rows]):.2f} s")
    print("\n|mid move| across a gap, bp (sigma_ref 0.268 bp/sqrt(s))")
    print("gap bucket      n    mean|move|   p90     p99     max    diffusion E|move| = 0.214*sqrt(gap)")
    for lo, hi in ((0.5, 1), (1, 2), (2, 5), (5, 10), (10, 1e9)):
        m = (g >= lo) & (g < hi)
        if m.sum():
            x = mv[m]
            print(f"{lo:>4}-{hi if hi < 1e8 else 'inf':<5} {int(m.sum()):6d}   {x.mean():8.3f}  {np.quantile(x, .9):6.2f}  {np.quantile(x, .99):6.2f}  {x.max():6.2f}    {0.214 * np.sqrt(np.median(g[m])):.3f}")


if __name__ == "__main__":
    main()
