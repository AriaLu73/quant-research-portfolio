#!/usr/bin/env python3
"""research5 L-6: what does the price do around a funding settlement, as a function of the funding rate?

If nothing adjusts, a short that is open only across the settlement instant collects the rate F (longs pay when F > 0).
No-arbitrage says the price should step UP by about F at the settlement (buying just after avoids the payment), which
would cancel that gain. This measures the step on KuCoin's own 5-minute bars.

Inputs: data/research5/funding/<sym>.csv (ts_ms,rate) and data/research5/kline5/<sym>.csv (5-minute bars).
For each settlement at time T (all in bp):
  pre30  = ln(close of bar [T-5m,T) / close of bar [T-35m,T-30m))
  step   = ln(open of bar [T,T+5m) / close of bar [T-5m,T))
  post5  = ln(close of bar [T,T+5m) / close of bar [T-5m,T))
  post30 = ln(close of bar [T+25m,T+30m) / close of bar [T-5m,T))
  short_pnl_h = F - post_h   (short opened at the last pre-settlement close, closed h minutes later; before fees/spread)
Usage: python scripts/research5/funding_event_study.py [since_YYYY-MM-DD]
"""
import glob, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BAR = 300_000


def events_for(fund, bars):
    """fund: DataFrame(ts, rate); bars: DataFrame(ts, open, close) of 5-minute bars. One row per settlement with all bars present."""
    b = bars.set_index("ts")
    rows = []
    for T, F in zip(fund.ts.to_numpy(), fund.rate.to_numpy()):
        need = [T - 7 * BAR, T - BAR, T, T + 5 * BAR]
        if not all(t in b.index for t in need):
            continue
        c_pre = b.close[T - BAR]
        rows.append(dict(T=T, F=F * 1e4, pre30=np.log(c_pre / b.close[T - 7 * BAR]) * 1e4, step=np.log(b.open[T] / c_pre) * 1e4,
                         post5=np.log(b.close[T] / c_pre) * 1e4, post30=np.log(b.close[T + 5 * BAR] / c_pre) * 1e4))
    return pd.DataFrame(rows)


def main():
    since = sys.argv[1] if len(sys.argv) > 1 else "2026-08-01"
    t0 = pd.Timestamp(since, tz="UTC").value // 1_000_000
    parts = []
    for p in glob.glob(os.path.join(ROOT, "data", "research5", "funding", "*.csv")):
        s = os.path.basename(p)[:-4]
        kp = os.path.join(ROOT, "data", "research5", "kline5", s + ".csv")
        if os.path.getsize(p) == 0 or not os.path.exists(kp) or os.path.getsize(kp) == 0:
            continue
        f = pd.read_csv(p, header=None, names=["ts", "rate"])
        k = pd.read_csv(kp, header=None, names=["ts", "open", "high", "low", "close", "vol", "turnover"])
        e = events_for(f[f.ts >= t0], k[["ts", "open", "close"]])
        if len(e):
            parts.append(e.assign(sym=s))
    e = pd.concat(parts, ignore_index=True)
    e.to_parquet(os.path.join(ROOT, "data", "research5", "funding_events.parquet"))
    e["bucket"] = pd.cut(e.F, [-np.inf, -20, -10, -5, -2, 2, 5, 10, 20, np.inf])
    pd.set_option("display.width", 220)
    print("since", since, "settlements", len(e), "contracts", e.sym.nunique())
    g = e.groupby("bucket", observed=True).agg(n=("F", "size"), syms=("sym", "nunique"), F=("F", "mean"), pre30=("pre30", "mean"), step=("step", "mean"),
                                                post5=("post5", "mean"), post30=("post30", "mean"), sd_post5=("post5", "std"))
    g["short_pnl_5"] = g.F - g.post5
    g["short_pnl_30"] = g.F - g.post30
    g["se_post5"] = g.sd_post5 / np.sqrt(g.n)
    print(g.round(2).to_string())
    big = e[e.F.abs() >= 10]
    for col in ("step", "post5", "post30"):
        beta = np.polyfit(big.F, big[col], 1)[0] if len(big) > 20 else np.nan
        print(f"|F| >= 10 bp (n={len(big)}): slope of {col} on F = {beta:+.3f}   (no-arbitrage predicts +1, 'nothing adjusts' predicts 0)")
    print("events per month with |F| >= 10 / 20 bp:", round(len(big) / max(1, (e['T'].max() - e['T'].min()) / 2.592e9), 1), "/", round((e.F.abs() >= 20).sum() / max(1, (e['T'].max() - e['T'].min()) / 2.592e9), 1))


if __name__ == "__main__":
    main()
