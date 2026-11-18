#!/usr/bin/env python3
"""research5 L-1a: does the real maker at the touch do better when the contract's OWN cash market is closed?

Input (read-only, produced by research4/stock_touch_stage1.py): data/research4/stock_anatomy_<day>.parquet, one row per real
taker order that hit the displayed touch; e5/e30/e300 = maker gross markout in bp, f = min($1,000, order size) weight.
Regimes are defined on the UTC time of the fill and the listing region of the underlying (see docs/research5/experiments.md).
Output: printed table + data/research5/session_markout.csv. Net = gross + OUR_FEE rebate.
Usage: python scripts/research5/session_markout.py 20260910,20260918,20260921,20260924
"""
import json, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REBATE = OUR_FEE
KR_HOLIDAYS = {"20260924"}  # ASSUMPTION: Chuseok 2026 (24-26 Sep), KRX closed


def in_any(h, spans):
    return any(a <= h < b for a, b in spans)


def regime(sub, hour_utc, day):
    """Regime label for a fill at fractional UTC hour `hour_utc` on `day` for an underlying listed in region `sub`."""
    if sub == "US.STOCK":
        if 13.5 <= hour_utc < 20.0:
            return "RTH"
        return "EXT" if (8.0 <= hour_utc < 13.5 or hour_utc >= 20.0) else "NIGHT"
    if sub == "HK.STOCK":
        return "OPEN" if in_any(hour_utc, [(1.5, 4.0), (5.0, 8.0)]) else "CLOSED"
    if sub == "KR.STOCK":
        if day in KR_HOLIDAYS:
            return "CLOSED"
        return "OPEN" if hour_utc < 6.5 else "CLOSED"
    if sub == "JP.STOCK":
        return "OPEN" if in_any(hour_utc, [(0.0, 2.5), (3.5, 6.5)]) else "CLOSED"
    return "NA"


def wmean(x, col):
    w = x["f"].values
    return float((x[col].values * w).sum() / w.sum()) if w.sum() > 0 else np.nan


def block_ci(x, col, n=2000, seed=11):
    """95% CI of the f-weighted mean of `col`, resampling contract-day blocks."""
    g = x.groupby(["sym", "day"]).apply(lambda b: pd.Series({"s": (b[col] * b["f"]).sum(), "w": b["f"].sum()}), include_groups=False)
    if len(g) < 5:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n, len(g)))
    m = g["s"].values[idx].sum(1) / g["w"].values[idx].sum(1)
    return tuple(np.percentile(m, [2.5, 97.5]).round(2))


def table(a, keys, ndays):
    rows = []
    for k, x in a.groupby(keys):
        k = k if isinstance(k, tuple) else (k,)
        v = x[x.v300]
        lo, hi = block_ci(v, "e300")
        rows.append(dict(zip(keys, k)) | dict(n=len(x), contracts=x.sym.nunique(), usd_day=x.f.sum() / ndays, half_bp=wmean(x, "half_bp"),
                                              net5=wmean(x, "e5") + REBATE, net30=wmean(x[x.v30], "e30") + REBATE,
                                              net300=wmean(v, "e300") + REBATE, lo300=lo + REBATE, hi300=hi + REBATE))
    return pd.DataFrame(rows)


def main():
    days = sys.argv[1].split(",")
    spec = {x["sym"]: x for x in json.load(open(os.path.join(ROOT, "data", "research4", "tradfi_contracts_20261001.json"), encoding="utf-8"))}
    a = pd.concat([pd.read_parquet(os.path.join(ROOT, "data", "research4", f"stock_anatomy_{d}.parquet")) for d in days], ignore_index=True)
    a = a[(a.cat == "at") & ~a.pair].copy()
    a["day"] = a.day.astype(str)
    a["sub"] = a.sym.map(lambda s: spec.get(s, {}).get("sub"))
    a["stage"] = a.sym.map(lambda s: spec.get(s, {}).get("stage"))
    hour = (a.ts // 1_000_000 % 86400) / 3600.0
    a["reg"] = [regime(s, h, d) for s, h, d in zip(a["sub"], hour, a["day"])]
    a["grp"] = np.where(a["sub"] == "US.STOCK", "US", "ASIA")
    a.loc[a.stage == "PRE_MARKET", "grp"] = "PREIPO"
    a.loc[a.stage == "PRE_MARKET", "reg"] = "NOSPOT"
    pd.set_option("display.width", 250)
    out = []
    for keys in (["grp", "reg"], ["sub", "reg"], ["sub", "reg", "day"]):
        t = table(a, keys, len(days) if "day" not in keys else 1)
        print("\n== by", keys)
        print(t.round(2).to_string(index=False))
        t.insert(0, "by", "+".join(keys))
        out.append(t)
    pd.concat(out).to_csv(os.path.join(ROOT, "data", "research5", "session_markout.csv"), index=False)


if __name__ == "__main__":
    main()
