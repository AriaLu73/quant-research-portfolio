#!/usr/bin/env python3
"""research5 MF-4a: what do the fills of the large "#01|20" sessions earn if each is hedged on Binance? (description)

User 2026-10-03: hedging on another venue may be explored; the fee there will be discussed later -> the hedge fee is a
free parameter here. For every maker fill on KuCoin BTC-USDT (10-01 13 h .. 10-02 21 h, order-by-order data):
  fair(t)  = Binance BTCUSDT last trade price at t + basis(t), basis = median of (KuCoin mid - Binance price) over the
             previous 5 minutes on a 1 s grid (known before t);
  edge(L)  = maker-signed (fill price - (Binance price at fill time + L + basis)) in bp: what is locked in when the hedge
             trades on Binance L ms after the fill at the then last price (Binance spread 0.1 = 0.01 bp, ignored);
  net      = edge + KuCoin rebate 0.7 - hedge fee f (bp of the hedged notional).
Binance quotes are not available for these days (only trades), the two exchange clocks are not aligned to better than a
few ms, and the unwinding of the two legs is not modelled: this is the entry edge, not a full strategy result.
Usage: Python314/python.exe scripts/research5/mf4_hedged_edge.py
"""
import os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mf3_sessions as S

BIG = [1790852294, 1790788917, 1790841366, 1790838170]
LAGS = (0, 5, 20, 100, 1000)
REBATE = OUR_FEE
MS = 10**6


class Fair:
    def __init__(self, day):
        b = np.load(os.path.join(S.OUT, f"binance_BTCUSDT_{day}.npz"))
        self.t, self.p = b["t"], b["p"]
        mid = S.Mid(day)
        g = np.arange(self.t[0] // 10**9 + 1, self.t[-1] // 10**9) * 10**9
        d = pd.Series(mid.at(g) - self.bn(g))
        self.g = g
        self.basis = d.rolling(300, min_periods=60).median().shift(1).to_numpy()     # known before the grid second

    def bn(self, t):
        return self.p[np.clip(np.searchsorted(self.t, np.asarray(t, np.int64), side="right") - 1, 0, len(self.p) - 1)]

    def basis_at(self, t):
        i = np.clip(np.searchsorted(self.g, np.asarray(t, np.int64), side="right") - 1, 0, len(self.g) - 1)
        return self.basis[i]


def table(f, title):
    w = lambda c, m=None: np.average(f[c][np.isfinite(f[c])], weights=f.notional[np.isfinite(f[c])])
    print(f"\n{title}: fills {len(f):,}, ${f.notional.sum() / 1e6:.1f}M")
    print("   hedge delay ms      " + "".join(f"{l:>9d}" for l in LAGS))
    print("   edge vs fair (bp)   " + "".join(f"{w('e%d' % l):9.2f}" for l in LAGS))
    hv = f.groupby("hour").apply(lambda x: np.average(x.e20, weights=x.notional))
    print(f"   at 20 ms: hours with edge > 0 {np.mean(hv > 0):.0%} of {len(hv)}; per fill share > 0 {np.mean(f.e20 > 0):.0%}; "
          f"median {f.e20.median():+.2f}, p10 {f.e20.quantile(.1):+.2f}, p90 {f.e20.quantile(.9):+.2f}")
    e = w("e20")
    print("   net per fill at 20 ms = edge + OUR_FEE rebate - hedge fee:  " + "  ".join(f"fee {x:g}: {e + REBATE - x:+.2f}" for x in (0, 1, 1.8, 2.5, 4, 5)) + f"   (break-even fee {e + REBATE:.2f} bp)")


def main():
    R, F, hours = S.load(["20261001", "20261002"])
    F = F[(F.self == 0)].copy()
    F["day"] = F.hour.str[:8]
    parts = []
    for day, f in F.groupby("day"):
        fair = Fair(day)
        px = f.tick / 10.0
        sg = np.where(f.side == 0, 1.0, -1.0)                      # the maker bought (+1): it sells the hedge on Binance
        bs = fair.basis_at(f.ts.to_numpy())
        f = f.copy()
        f["basis"] = bs / px * 1e4
        for l in LAGS:
            f["e%d" % l] = sg * (fair.bn(f.ts.to_numpy() + l * MS) + bs - px) / px * 1e4
        parts.append(f)
    F = pd.concat(parts)
    F = F[np.isfinite(F.e0)]
    big = F[F.sess.isin(BIG)]
    print(f"basis KuCoin - Binance (bp): median {F.basis.median():+.2f}, p5 {F.basis.quantile(.05):+.2f}, p95 {F.basis.quantile(.95):+.2f}")
    table(big, "the four large sessions, all fills")
    for lo, hi in ((-99, 0.5), (0.5, 1.5), (1.5, 3), (3, 99)):
        table(big[(big.m0 >= lo) & (big.m0 < hi)], f"the four large sessions, fills {lo:g}..{hi:g} bp from the KuCoin mid")
    for s in BIG:
        table(big[big.sess == s], f"session {s}")
    table(F[~F.sess.isin(BIG)], "all other sessions of the pattern")
    # how much of the flow nets out before it has to be hedged
    b = big.sort_values("ts")
    for win in (1, 10, 60, 600):
        k = b.ts // (win * 10**9)
        net = b.q.groupby(k).sum().abs().sum()
        print(f"netting window {win:4d} s: hedge volume = {net / b.q.abs().sum():.0%} of the gross fill volume")
    big.to_parquet(os.path.join(S.OUT, "mf4_big_fills.parquet"), index=False)


if __name__ == "__main__":
    main()
