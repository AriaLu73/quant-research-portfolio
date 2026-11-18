#!/usr/bin/env python3
"""research5 MF-5: fit the two pieces of the quote model on one day of Binance BTCUSDT trades, for use on the OTHER day.

  drift   E[Binance move over the next H ms | price change and signed volume over the last 50 ms]  (linear, through 0)
          -> fair value = last Binance price + drift (+ basis)      [Lehalle-Neuman 2019; Cartea-Jaimungal-Ricci 2014]
  buffer  q99 of |move over the next tau ms - drift| by activity (trades in the last 100 ms): the distance a quote needs
          so that the price does not get through it before our cancel is effective          [Moallemi-Saglam 2013; Budish et al. 2015]
Sampled once per millisecond with trades (see bn_reaction_stats.py). Output data/research5/maker_families/mf5_fit_<day>.json
Usage: .venv/Scripts/python.exe scripts/research5/mf5_fit.py 20261001 20261002
"""
import json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bn_reaction_stats as B

MS = 10**6
H_MS, TAUS = 26.5, (6.5, 26.5, 50.0)
BUCKETS = (0, 3, 10, 30, 100, 300, 10**9)          # trades in the last 100 ms
SV_CAP = 50.0                                       # BTC: signed volume is clipped (a few huge prints would set the slope)


def features(day):
    T, P, SV, N = B.per_ms(*B.load(day))
    at = lambda x: P[np.clip(np.searchsorted(T, x, side="right") - 1, 0, len(P) - 1)]
    csv, cn = np.r_[0, np.cumsum(SV)], np.r_[0, np.cumsum(N)]
    a50, b = np.searchsorted(T, T - 50 * MS, side="right"), np.arange(1, len(T) + 1)
    a100 = np.searchsorted(T, T - 100 * MS, side="right")
    chg50 = (P - at(T - 50 * MS)) / P * 1e4
    sv50 = np.clip(csv[b] - csv[a50], -SV_CAP, SV_CAP)
    n100 = cn[b] - cn[a100]
    fut = {L: (at(T + int(L * MS)) - P) / P * 1e4 for L in set(TAUS) | {H_MS}}
    return chg50, sv50, n100, fut


def main():
    for day in sys.argv[1:] or ["20261001", "20261002"]:
        chg50, sv50, n100, fut = features(day)
        X = np.c_[chg50, sv50]
        beta, *_ = np.linalg.lstsq(X, fut[H_MS], rcond=None)
        pred = X @ beta
        r2 = 1 - ((fut[H_MS] - pred) ** 2).sum() / (fut[H_MS] ** 2).sum()
        out = dict(day=day, h_ms=H_MS, beta_chg50=float(beta[0]), beta_sv50=float(beta[1]), sv_cap=SV_CAP, r2=float(r2),
                   buckets=list(BUCKETS[:-1]), buffer={})
        print(f"{day}: drift over {H_MS} ms = {beta[0]:+.3f} x (price change last 50 ms, bp) {beta[1]:+.4f} x (signed volume last 50 ms, BTC);  R2 {r2:.3f}; "
              f"rank IC {B.rank_ic(pred, fut[H_MS]):.3f}")
        print("   trades in last 100 ms | share | q99 |move - drift| over tau (bp):  " + "  ".join(f"tau {t:g}" for t in TAUS) + "   | without the drift term (tau 6.5)")
        for lo, hi in zip(BUCKETS[:-1], BUCKETS[1:]):
            m = (n100 >= lo) & (n100 < hi)
            if m.sum() < 200:
                continue
            scale = {t: t / H_MS if t < H_MS else 1.0 for t in TAUS}          # the drift accrues over H; a shorter tau sees part of it
            q = {t: float(np.percentile(np.abs(fut[t][m] - pred[m] * scale[t]), 99)) for t in TAUS}
            out["buffer"][str(lo)] = q
            print(f"   {lo:5d}-{hi if hi < 10**9 else 'max':>5} | {m.mean():6.1%} | " + "  ".join(f"{q[t]:8.2f}" for t in TAUS) + f"   | {np.percentile(np.abs(fut[6.5][m]), 99):.2f}")
        json.dump(out, open(os.path.join("data", "research5", "maker_families", f"mf5_fit_{day}.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
