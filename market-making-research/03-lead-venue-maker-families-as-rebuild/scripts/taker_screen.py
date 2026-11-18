#!/usr/bin/env python3
"""research5 L-4a: fill-level screen of 'take KuCoin quotes that are stale against Binance, exit passively'.

Uses the rows written by lead_lag.py (one per real KuCoin taker order, with gap_L = the taker's edge against the
Binance-implied fair value taken L ms earlier) and our 5 s best-bid/ask samples for the exit-time half-spread.
Per dollar of entry notional, in bp (h = 60 or 300 s):
  g_h  = taker gross vs KuCoin's mid h seconds later            (= -k_h of lead_lag.py)
  x_tt = g_h - 1.8 - 1.8 - half-spread at exit                  (take in, take out: conservative bound)
  x_tm = g_h - 1.8 + 0.8                                        (take in, passive exit at the mid: optimistic bound)
Usage: python scripts/research5/taker_screen.py 20261001
"""
import os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lead_lag as LL  # noqa: E402

TAKER, REBATE = OUR_FEE, 0.8
THETAS = (3.0, 5.0, 8.0, 12.0)


def economics(g, hs_exit):
    """(x_tt, x_tm) from the taker's gross g (bp) and the exit-time half-spread hs_exit (bp)."""
    return g - TAKER - TAKER - hs_exit, g - TAKER + REBATE


def load_half_spread(day):
    """{sym: (recv_ms, half-spread in bp)} from the 5 s recorder; tolerant of the still-open gzip stream."""
    import gzip
    rows = []
    try:
        with gzip.open(os.path.join(LL.ROOT, "data", "research4", "bbo", f"{day}.csv.gz"), "rt") as fh:
            for line in fh:
                p = line.split(",")
                if len(p) >= 6:
                    rows.append((p[0], p[1], p[3], p[5]))
    except EOFError:
        pass
    b = pd.DataFrame(rows, columns=["t", "sym", "bid", "ask"])
    for c in ("t", "bid", "ask"):
        b[c] = pd.to_numeric(b[c], errors="coerce")
    b = b.dropna()
    b = b[(b.bid > 0) & (b.ask > b.bid)]
    b["hs"] = (b.ask - b.bid) / (b.ask + b.bid) * 1e4
    return {s: (x.t.to_numpy(np.int64), x.hs.to_numpy(float)) for s, x in b.sort_values("t").groupby("sym")}


def table(r, lag, hours):
    rows = []
    for th in THETAS:
        x = r[r[f"gap_{lag}"] > th]
        for h in (60, 300):
            y = x[np.isfinite(x[f"k_{h}"]) & np.isfinite(x[f"hs_{h}"])].copy()
            if len(y) < 30:
                continue
            y["x_tt"], y["x_tm"] = economics(-y[f"k_{h}"], y[f"hs_{h}"])
            by = y.groupby("sym").f.sum().sort_values(ascending=False)
            rows.append(dict(lag_ms=lag, theta=th, h=h, n=len(y), syms=y.sym.nunique(), usd_day=y.f.sum() / hours * 24, top3=by.head(3).sum() / by.sum(),
                             gap=LL.wmean(y, f"gap_{lag}"), g=-LL.wmean(y, f"k_{h}"), hs_exit=LL.wmean(y, f"hs_{h}"),
                             x_tt=LL.wmean(y, "x_tt"), tt_ci=LL.block_ci(y, "x_tt"), x_tm=LL.wmean(y, "x_tm"), tm_ci=LL.block_ci(y, "x_tm")))
    return pd.DataFrame(rows)


def main():
    day = sys.argv[1]
    r = pd.read_parquet(os.path.join(LL.D5, "lead_lag_rows.parquet"))
    hs = load_half_spread(day)
    for h in (60, 300):
        r[f"hs_{h}"] = np.nan
        for sym, idx in r.groupby("sym").groups.items():
            if sym in hs:
                r.loc[idx, f"hs_{h}"] = LL.next_value_at(*hs[sym], r.loc[idx, "t"].to_numpy() + h * 1000)
    hours = (r.t.max() - r.t.min()) / 3.6e6
    pd.set_option("display.width", 250)
    for lag in (20, 100):
        print(f"\n== entries: real taker fills whose quote was already > theta bp through the Binance-implied fair {lag} ms earlier ({hours:.1f} h, {r.sym.nunique()} contracts)")
        print(table(r, lag, hours).round(2).to_string(index=False))
    x = r[r.gap_20 > 5.0]
    print("\n== theta 5 bp, lag 20 ms: by contract (f-weighted)")
    g = x.groupby("sym").apply(lambda b: pd.Series({"n": len(b), "usd": b.f.sum(), "gap": LL.wmean(b, "gap_20"), "g60": -LL.wmean(LL.finite(b, "k_60"), "k_60"),
                                                     "g300": -LL.wmean(LL.finite(b, "k_300"), "k_300"), "hs300": LL.wmean(LL.finite(b, "hs_300"), "hs_300")}), include_groups=False)
    print(g.sort_values("usd", ascending=False).round(2).to_string())


if __name__ == "__main__":
    main()
