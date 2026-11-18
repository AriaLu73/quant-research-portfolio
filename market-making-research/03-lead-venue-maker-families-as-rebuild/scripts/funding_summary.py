#!/usr/bin/env python3
"""research5 L-3: funding-rate history of the TradFi-linked contracts (level, sign persistence, weekend vs weekday).

Input: data/research5/funding/<symbol>.csv (ts_ms,rate) from fetch_public.py. Output: data/research5/funding_summary.csv + printed tables.
Usage: python scripts/research5/funding_summary.py [since_YYYY-MM-DD]
"""
import glob, json, os, sys
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def is_weekend_settlement(t):
    """Funding settled on Sat/Sun (UTC), or at Mon 00:00 UTC: the accrual window lay inside the US-equity weekend."""
    return (t.dt.dayofweek >= 5) | ((t.dt.dayofweek == 0) & (t.dt.hour == 0))


def summarize(d, per_day):
    wk = d[is_weekend_settlement(d.t)]
    wd = d.drop(wk.index)
    return dict(n=len(d), per_day=per_day, mean_bp=d.bp.mean(), med_bp=d.bp.median(), sd_bp=d.bp.std(), pos=(d.bp > 0).mean(),
                zero=(d.bp == 0).mean(), p05=d.bp.quantile(.05), p95=d.bp.quantile(.95), mn=d.bp.min(), mx=d.bp.max(),
                daily_bp=d.bp.mean() * per_day, wk_bp=wk.bp.mean(), wd_bp=wd.bp.mean(), ac1=d.bp.autocorr(1))


def main():
    since = sys.argv[1] if len(sys.argv) > 1 else "2026-08-01"
    spec = {x["sym"]: x for x in json.load(open(os.path.join(ROOT, "data", "research4", "tradfi_contracts_20261001.json"), encoding="utf-8"))}
    rows = []
    for p in glob.glob(os.path.join(ROOT, "data", "research5", "funding", "*.csv")):
        s = os.path.basename(p)[:-4]
        if os.path.getsize(p) == 0:
            continue
        d = pd.read_csv(p, header=None, names=["ts", "r"])
        d["t"] = pd.to_datetime(d.ts, unit="ms", utc=True)
        d = d[d.t >= since]
        if len(d) < 30:
            continue
        d["bp"] = d.r * 1e4
        rows.append(dict(sym=s, cls=spec[s]["cls"], sub=spec[s]["sub"], **summarize(d, 24 / spec[s]["fg"])))
    f = pd.DataFrame(rows)
    f.to_csv(os.path.join(ROOT, "data", "research5", "funding_summary.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print("since", since, "contracts:", len(f))
    print(f.groupby("cls")[["mean_bp", "med_bp", "sd_bp", "pos", "zero", "daily_bp", "wk_bp", "wd_bp", "ac1"]].mean().round(3))
    print("\n|mean per settlement| across contracts:", f.mean_bp.abs().describe().round(3).to_dict())
    cols = ["sym", "cls", "n", "mean_bp", "sd_bp", "pos", "zero", "p05", "p95", "mn", "mx", "daily_bp", "wk_bp", "wd_bp", "ac1"]
    print("\nTop 15 by |daily_bp|:")
    print(f.reindex(f.daily_bp.abs().sort_values(ascending=False).index).head(15)[cols].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
