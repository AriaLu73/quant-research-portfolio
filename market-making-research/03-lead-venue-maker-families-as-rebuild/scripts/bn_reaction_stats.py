#!/usr/bin/env python3
"""research5 MF-5: what the Binance price does over OUR reaction time, and what predicts it (Binance BTCUSDT aggTrades).

Sampled once per millisecond that has trades (the state after all trades of that millisecond; trades inside one
millisecond cannot be ordered against our clock and would leak the rest of a sweep into the "future").
  1. |move| of the Binance price over the next L ms, overall and by activity (trades in the previous 100 ms):
     the quote distance has to cover this, because that is what happens before our cancel is effective.
  2. rank IC of flow / momentum features with the signed move over the next L ms (continuation after a move).
Usage: .venv/Scripts/python.exe scripts/research5/bn_reaction_stats.py 20261001 20261002
"""
import sys
import numpy as np

MS = 10**6
LS = (6.5, 26.5, 50, 100, 1000)


def load(day):
    z = np.load(f"data/research5/maker_families/binance_BTCUSDT_{day}.npz")
    return z["t"], z["p"], z["q"], np.where(z["bm"], -1.0, 1.0)      # buyer is maker -> the seller was aggressive


def rank_ic(x, y):
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    return np.corrcoef(np.argsort(np.argsort(x)), np.argsort(np.argsort(y)))[0, 1]


def per_ms(t, p, q, s):
    """-> per millisecond with trades: time, last price, signed volume, trade count, cumulative sums for windows."""
    last = np.r_[t[1:] != t[:-1], True]
    first = np.r_[True, t[1:] != t[:-1]]
    idx = np.cumsum(first) - 1
    sv = np.bincount(idx, weights=q * s)
    n = np.bincount(idx)
    return t[last], p[last], sv, n


def main():
    for day in sys.argv[1:] or ["20261001", "20261002"]:
        T, P, SV, N = per_ms(*load(day))
        at = lambda x: P[np.clip(np.searchsorted(T, x, side="right") - 1, 0, len(P) - 1)]
        csv, cn = np.r_[0, np.cumsum(SV)], np.r_[0, np.cumsum(N)]

        def win(x, w):                                          # signed volume, trades in (x - w, x]
            a, b = np.searchsorted(T, x - w, side="right"), np.searchsorted(T, x, side="right")
            return csv[b] - csv[a], cn[b] - cn[a]

        print(f"\n{day}: milliseconds with trades {len(T):,}")
        print("  |move| of the Binance price over the next L ms (bp): p50 / p90 / p99 / share >= 0.5 / >= 1 / >= 2 bp")
        fut = {}
        for L in LS:
            fut[L] = (at(T + int(L * MS)) - P) / P * 1e4
            d = np.abs(fut[L])
            print(f"    L {L:6g}: {np.percentile(d, 50):.2f} / {np.percentile(d, 90):.2f} / {np.percentile(d, 99):.2f} / {np.mean(d >= .5):.1%} / {np.mean(d >= 1):.1%} / {np.mean(d >= 2):.1%}")
        _, n100 = win(T, 100 * MS)
        step = (P - at(T - 1)) / P * 1e4                         # price change made in this millisecond
        print("  by trades in the previous 100 ms (incl. this ms): share | p90, p99 of |move| over 6.5 ms | over 50 ms")
        for lo, hi in ((0, 3), (3, 10), (10, 30), (30, 100), (100, 10**9)):
            m = (n100 >= lo) & (n100 < hi)
            if m.sum() > 200:
                a, b = np.abs(fut[6.5][m]), np.abs(fut[50][m])
                print(f"    {lo:3d}-{hi if hi < 10**9 else 'max':>3}: {m.mean():6.1%} | {np.percentile(a, 90):.2f} {np.percentile(a, 99):.2f} | {np.percentile(b, 90):.2f} {np.percentile(b, 99):.2f}")
        print("  by the size of the price change made in this millisecond: share | p90, p99 of |move| over the next 6.5 ms | 50 ms | mean further move in the same direction 6.5 / 50 / 1000 ms")
        for lo, hi in ((0, 0.05), (0.05, 0.25), (0.25, 0.5), (0.5, 1), (1, 2), (2, 99)):
            m = (np.abs(step) >= lo) & (np.abs(step) < hi)
            if m.sum() > 200:
                a, b = np.abs(fut[6.5][m]), np.abs(fut[50][m])
                sg = np.sign(step[m])
                print(f"    {lo:4g}-{hi:<4g} bp: {m.mean():6.1%} | {np.percentile(a, 90):.2f} {np.percentile(a, 99):.2f} | {np.percentile(b, 90):.2f} {np.percentile(b, 99):.2f} | "
                      f"{np.mean(sg * fut[6.5][m]):+.3f} / {np.mean(sg * fut[50][m]):+.3f} / {np.mean(sg * fut[1000][m]):+.3f}")
        feats = {"step this ms": step, "price chg 10 ms": (P - at(T - 10 * MS)) / P * 1e4, "50 ms": (P - at(T - 50 * MS)) / P * 1e4, "200 ms": (P - at(T - 200 * MS)) / P * 1e4,
                 "signed vol this ms": SV, "10 ms": win(T, 10 * MS)[0], "50 ms ": win(T, 50 * MS)[0], "200 ms ": win(T, 200 * MS)[0], "1 s": win(T, 1000 * MS)[0]}
        print("  rank IC with the signed move over the next L ms:")
        for L in LS:
            print(f"    L {L:6g}: " + ", ".join(f"{k} {rank_ic(v, fut[L]):+.3f}" for k, v in feats.items()))


if __name__ == "__main__":
    main()
