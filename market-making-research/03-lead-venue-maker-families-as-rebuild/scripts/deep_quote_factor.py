#!/usr/bin/env python3
"""research5 D-2: deep quotes on mid-cap USDT perps, split by whether the rest of the KuCoin market moved with the sweep.

Pre-registered in docs/research5/experiments.md (card D-2). Same orders, fills, validity rules and grid as
deep_quote_curve.py (D-1 v2); the only addition is a label per taker order:
  M      median over the OTHER contracts of their mid return over the last second, read on a 100 ms grid at the last
         grid point at or before (order time - 1.8 ms)  -> only information older than our reaction time
  z      taker direction x M / sigma_M;  sigma_M = sqrt(pi/2) x mean|M| on the training days (one number)
  group  with (z >= 1), flat (|z| < 1), against (z <= -1)
Usage: python scripts/research5/deep_quote_factor.py        (Python314)
"""
import json, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deep_quote_curve as D

GRID_US = 100_000
WIN_STEPS = 10            # 1 s on the 100 ms grid
GROUPS = ("with", "flat", "against")


def grid_mids(ts_book, mid, g):
    """Mid at each grid time (last book event at or before it); NaN before the first event."""
    j = np.searchsorted(ts_book, g, side="right") - 1
    out = mid[np.clip(j, 0, None)].astype(np.float32)
    out[j < 0] = np.nan
    return out


def market_move_bp(R, col, rows):
    """Median over all columns except `col` of the returns matrix R (grid x contracts, bp) at the given grid rows."""
    return np.nanmedian(np.delete(R[rows], col, axis=1), axis=1)


def group_of(z):
    return np.where(z >= 1.0, "with", np.where(z <= -1.0, "against", "flat"))


def day_returns(uni, day):
    """(grid start, R): 1 s returns in bp of every contract on the 100 ms grid of the day."""
    t0 = t1 = None
    books = {}
    for s in uni:
        b = pd.read_parquet(os.path.join(D.EV, f"book_{s}_{day}.parquet"), columns=["ts", "bb", "ba"])
        ts = b.ts.to_numpy().astype(np.int64)
        books[s] = (ts, (b.bb.to_numpy() + b.ba.to_numpy()) / 2.0)
        t0 = ts[0] if t0 is None else min(t0, ts[0])
        t1 = ts[-1] if t1 is None else max(t1, ts[-1])
    g = np.arange(t0 // GRID_US * GRID_US, t1, GRID_US, dtype=np.int64)
    R = np.full((len(g), len(uni)), np.nan, dtype=np.float32)
    for c, s in enumerate(uni):
        m = grid_mids(*books[s], g)
        R[WIN_STEPS:, c] = (m[WIN_STEPS:] / m[:-WIN_STEPS] - 1.0) * 1e4
    return g[0], R


def main():
    uni = pd.read_csv(os.path.join(D.ROOT, "data", "research5", "alt_usdt_universe.csv")).head(22).sym.tolist()
    invk = json.load(open(os.path.join(D.ROOT, "data", "research5", "deep_quote_invk_v2.json")))
    labels = [f"{m:g}x" for m in D.M_GRID]
    per_day, absM = {}, []
    for day in D.TRAIN + D.TEST:
        g0, R = day_returns(uni, day)
        per_day[day] = {}
        for c, s in enumerate(uni):
            o, pr = D.load_orders(s, day)
            rows = np.clip((o["ts"] - D.LAG_US - g0) // GRID_US, 0, len(R) - 1)
            M = market_move_bp(R, c, rows)
            per_day[day][s] = (o, pr, M)
            if day in D.TRAIN:
                absM.append(np.abs(M[np.isfinite(M)]))
        del R
        print(day, "loaded", flush=True)
    sigma = float(np.sqrt(np.pi / 2) * np.concatenate(absM).mean())
    print(f"sigma_M (1 s market move, training days) = {sigma:.3f} bp")
    rows = []
    for day in D.TRAIN + D.TEST:
        for s in uni:
            o, pr, M = per_day[day][s]
            grp = group_of(np.nan_to_num(o["sgn"] * M / sigma))
            for gname in GROUPS:
                o2 = dict(o, ok=o["ok"] & (grp == gname))
                for r in D.grid_rows(s, day, o2, pr, [m * invk[s] for m in D.M_GRID], gname, labels):
                    rows.append(r)
    df = pd.DataFrame(rows).fillna({"s5": 0, "u5": 0, "s30": 0, "u30": 0, "s300": 0, "u300": 0, "stk": 0})
    df.to_parquet(os.path.join(D.ROOT, "data", "research5", "deep_quote_factor.parquet"))
    for gname in GROUPS:
        D.table(df[df.kind == gname], D.TRAIN, f"TRAIN, group = {gname}")
    flat = df[df.kind == "flat"]
    tr = flat[flat.day.isin(D.TRAIN) & (flat.hour >= 0)]
    profit = tr.groupby("grid", sort=False).s300.sum() / 1e4
    m_star = profit.idxmax()
    print("\ntraining profit $ by m in the flat group:", profit.round(1).to_dict(), "-> m* =", m_star)
    for gname in GROUPS:
        D.table(df[df.kind == gname], D.TEST, f"TEST, group = {gname}")
    te = flat[flat.day.isin(D.TEST) & (flat.hour >= 0) & (flat.grid == m_star)]
    lo, hi = D.block_ci(te)
    per = te.groupby("sym").apply(lambda x: x.s300.sum() / x.u300.sum() if x.u300.sum() > 0 else np.nan, include_groups=False)
    c = flat[flat.day.isin(D.TEST) & (flat.hour < 0) & (flat.grid == m_star)]
    cash_bp = c.cash_net.sum() / c.cash_vol.sum() * 1e4
    share = (per > 0).sum() / per.notna().sum()
    byday = te.groupby("day").apply(lambda x: x.s300.sum() / x.u300.sum(), include_groups=False).round(2).to_dict()
    print(f"\nPRIMARY (test days, flat group, m* = {m_star}): net300 {D.pooled(te):+.2f} bp [{lo:+.2f}, {hi:+.2f}]; net5 {D.pooled(te, 5):+.2f}; cash-settled {cash_bp:+.2f} bp;"
          f" contracts positive {int((per > 0).sum())}/{per.notna().sum()}; fill $ per day {te.usd.sum() / len(D.TEST):,.0f}; by day {byday}")
    print("pass lines: (1) net300 > 0 and CI lower > 0:", bool(D.pooled(te) > 0 and lo > 0), "| (2) cash > 0:", bool(cash_bp > 0), "| (3) >= 60 % contracts positive:", bool(share >= 0.6))


if __name__ == "__main__":
    main()
