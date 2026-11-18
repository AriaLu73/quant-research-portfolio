#!/usr/bin/env python3
"""research5 L-2: realised volatility and reported volume of the TradFi contracts by session (weekday vs weekend).

Input: data/research5/kline5/<symbol>.csv (ts_ms,open,high,low,close,volume_contracts,turnover_usd; 5-minute bars from
KuCoin's public kline endpoint). Reported volume includes the paired prints (~94% of it), so it is NOT real flow.
Sessions (UTC):
  WEEKEND   Fri 21:00 .. Sun 22:00      US cash, index futures and most commodity futures closed
  US_RTH    Mon-Fri 13:30 .. 20:00
  OTHER     the rest of the week
Output: printed table by asset class; data/research5/session_vol.csv (one row per contract).
Usage: python scripts/research5/session_vol.py [since_YYYY-MM-DD]
"""
import glob, json, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def session(ts):
    """Session label for each UTC timestamp in a DatetimeIndex."""
    dow, h = ts.dayofweek.to_numpy(), (ts.hour + ts.minute / 60).to_numpy()
    wk = ((dow == 4) & (h >= 21)) | (dow == 5) | ((dow == 6) & (h < 22))
    rth = (dow <= 4) & (h >= 13.5) & (h < 20) & ~wk
    return np.where(wk, "WEEKEND", np.where(rth, "US_RTH", "OTHER"))


def per_contract(d):
    """5-minute close-to-close log returns -> annualisation-free stats per session: bp per sqrt(hour), bars, $ per hour."""
    d = d.sort_values("ts")
    r = np.log(d.close / d.close.shift(1)) * 1e4
    gap = d.ts.diff() != 300_000                       # do not count returns across missing bars
    r[gap] = np.nan
    s = session(pd.DatetimeIndex(pd.to_datetime(d.ts.to_numpy(), unit="ms", utc=True)))
    r, d = r.reset_index(drop=True), d.reset_index(drop=True)
    out = {}
    for name in ("WEEKEND", "US_RTH", "OTHER"):
        m = s == name
        x = r[m].dropna()
        out[f"sig_{name}"] = float(np.sqrt((x ** 2).mean() * 12)) if len(x) > 200 else np.nan     # bp per sqrt(hour)
        out[f"usd_h_{name}"] = float(d.turnover[m].sum() / (m.sum() / 12)) if m.sum() else np.nan
        out[f"zero_{name}"] = float((x == 0).mean()) if len(x) > 200 else np.nan
    return out


def main():
    since = sys.argv[1] if len(sys.argv) > 1 else "2026-08-01"
    spec = {x["sym"]: x for x in json.load(open(os.path.join(ROOT, "data", "research4", "tradfi_contracts_20261001.json"), encoding="utf-8"))}
    rows = []
    for p in glob.glob(os.path.join(ROOT, "data", "research5", "kline5", "*.csv")):
        s = os.path.basename(p)[:-4]
        if os.path.getsize(p) == 0:
            continue
        d = pd.read_csv(p, header=None, names=["ts", "open", "high", "low", "close", "vol", "turnover"])
        d = d[d.ts >= pd.Timestamp(since, tz="UTC").value // 1_000_000]
        if len(d) < 2000:
            continue
        rows.append(dict(sym=s, cls=spec[s]["cls"], sub=spec[s]["sub"] or "", **per_contract(d)))
    f = pd.DataFrame(rows)
    f["sig_ratio_wk_rth"] = f.sig_WEEKEND / f.sig_US_RTH
    f["usd_ratio_wk_rth"] = f.usd_h_WEEKEND / f.usd_h_US_RTH
    f.to_csv(os.path.join(ROOT, "data", "research5", "session_vol.csv"), index=False)
    pd.set_option("display.width", 220)
    print("since", since, "contracts", len(f), "(sig = bp per sqrt(hour); usd_h = reported $ per hour incl. paired prints)")
    print(f.groupby(["cls", "sub"])[["sig_US_RTH", "sig_OTHER", "sig_WEEKEND", "sig_ratio_wk_rth", "zero_WEEKEND", "usd_h_US_RTH", "usd_h_OTHER", "usd_h_WEEKEND", "usd_ratio_wk_rth"]].median().round(2))


if __name__ == "__main__":
    main()
