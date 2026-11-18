#!/usr/bin/env python3
"""research5: one row per KuCoin crypto USDT perp - what a resting quote at the touch actually earned, and how big the contract is.

Sources (all read-only):
  data/research3/longtail_scan.csv   per (contract, day) on the purchased September days 10 / 18 / 21 / 24: real taker flow with
                                     self-trades removed, and the gross markout of the REAL resting side when a real taker order
                                     hit the displayed touch (no queue assumption). Written by scripts/research3/longtail_scan.py.
  KuCoin public REST (now)           24 h reported turnover, open interest, funding, best bid / ask
  Binance public REST (now)          24 h futures turnover of the same coin, as a size reference only (rough symbol match)
Columns of data/research5/alt_usdt_universe.csv
  real_usd_day   real taker $ per day (self-trades and inside-the-spread prints removed), mean of the scanned days
  at_usd_day     the part of it that hit the displayed best price
  pair_share     share of reported taker $ that is self-trading
  half_bp        median half-spread, bp;  tick_bp  tick size, bp
  thru_share     share of at-touch $ that traded through the first level
  net5 / net300  maker markout after 5 s / 5 min incl. the OUR_FEE rebate, bp, weighted over the days
  cash_bp        cash-settled result of "always at the touch, <= $1,000 per taker order, inventory +-$3,000", bp of volume
  days_pos       scanned days with net300 > 0 / scanned days
  ku_24h, oi_usd, spread_now_bp, funding_bp   live snapshot;  bn_24h  Binance futures 24 h turnover (0 = no match)
Usage: python scripts/research5/alt_usdt_universe.py        (Python314)
"""
import json, os, time, urllib.request
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REBATE = OUR_FEE


def get(url):
    return json.load(urllib.request.urlopen(url, timeout=30))


def per_contract(scan):
    """Aggregate the per-day scan rows of one contract class into one row per contract."""
    rows = []
    for sym, g in scan.groupby("sym"):
        w = g.at_f.clip(lower=0)
        wavg = lambda c: float((g[c] * w).sum() / w.sum()) if w.sum() > 0 and g[c].notna().any() else np.nan
        n300 = g.e300 + REBATE
        rows.append(dict(sym=sym, days=len(g), real_usd_day=g.real_usd.mean(), at_usd_day=g.at_usd.mean(), pair_share=g.pair_share.mean(),
                         half_bp=g.half_bp.median(), tick_bp=g.tick_bp.median(), thru_share=g.thru_share.mean(),
                         net5=wavg("e5") + REBATE, net300=wavg("e300") + REBATE,
                         cash_bp=g.net1000.sum() / g.vol1000.sum() * 1e4 if g.vol1000.sum() > 0 else np.nan,
                         days_pos=f"{int((n300 > 0).sum())}/{len(g)}"))
    return pd.DataFrame(rows)


def main():
    scan = pd.read_csv(os.path.join(ROOT, "data", "research3", "longtail_scan.csv"))
    scan = scan[(scan.cls == "CRYPTO") & scan.sym.str.endswith("USDTM")]
    d = per_contract(scan)
    act = {x["symbol"]: x for x in get("https://api-futures.kucoin.com/api/v1/contracts/active")["data"]}
    tick = {x["symbol"]: x for x in get("https://api-futures.kucoin.com/api/v1/allTickers")["data"]}
    bn = {x["symbol"]: float(x["quoteVolume"]) for x in get("https://fapi.binance.com/fapi/v1/ticker/24hr")}
    live = []
    for s in d.sym:
        a, t = act.get(s), tick.get(s)
        if a is None:
            live.append(dict(sym=s, listed=False))
            continue
        bb, ba = (float(t["bestBidPrice"]), float(t["bestAskPrice"])) if t else (np.nan, np.nan)
        mid = (bb + ba) / 2
        base = s[:-5]
        cand = ["BTCUSDT" if base == "XBT" else base + "USDT", "1000" + base + "USDT"]      # Binance quotes some small-price coins per 1000
        live.append(dict(sym=s, listed=True, ku_24h=float(a.get("turnoverOf24h") or 0), oi_usd=float(a.get("openInterest") or 0) * abs(float(a["multiplier"])) * mid,
                         spread_now_bp=(ba - bb) / mid * 1e4 if mid > 0 else np.nan, funding_bp=float(a.get("fundingFeeRate") or 0) * 1e4,
                         bn_24h=max(bn.get(c, 0.0) for c in cand)))
    d = d.merge(pd.DataFrame(live), on="sym", how="left").sort_values("real_usd_day", ascending=False).reset_index(drop=True)
    d.insert(0, "rank", np.arange(1, len(d) + 1))
    d.to_csv(os.path.join(ROOT, "data", "research5", "alt_usdt_universe.csv"), index=False)
    print(time.strftime("%F %T UTC", time.gmtime()), "contracts", len(d), "| still listed", int(d.listed.fillna(False).sum()))
    q = d.real_usd_day.quantile([0.5, 0.8, 0.9, 0.95, 0.99]).round(0).tolist()
    print("real taker $/day quantiles 50/80/90/95/99:", q)
    for lo, hi, name in ((2e7, 1e12, "majors  > $20M/day"), (2e6, 2e7, "mid     $2M-$20M"), (3e5, 2e6, "small   $0.3M-$2M"), (0, 3e5, "tail    < $0.3M")):
        g = d[(d.real_usd_day >= lo) & (d.real_usd_day < hi)]
        w = g.at_usd_day
        print(f"{name:22s} n {len(g):4d}  real $/day total {g.real_usd_day.sum():14,.0f}  self-trade share {g.pair_share.mean():.0%}  half-spread {g.half_bp.median():5.2f} bp"
              f"  net5 {np.average(g.net5.fillna(0), weights=w):+.2f}  net300 {np.average(g.net300.fillna(0), weights=w):+.2f}  contracts with net300 > 0: {int((g.net300 > 0).sum())}")


if __name__ == "__main__":
    main()
