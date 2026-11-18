#!/usr/bin/env python3
"""research5 X-1: how much of the reported volume on KuCoin's USDC-margined perps is flow a resting quote can trade with?

Input (public, read-only): our own recordings data/kucoin_l3_btc/<day>/<HH>_<sym>_trades.jsonl.gz (XBTUSDCM, XBTUSDTM;
lines "<recv_ns>\t<json>", topic /contractMarket/execution) and, for the other USDC contracts, the last 100 public trades
from REST /api/v1/trade/history (snapshot only).
Paired print = maker order age (takerOrderId - makerOrderId) >> 22 <= 20 ms and not a liquidation id (kucoin_trades.py).
Output: printed table per contract: hours, reported $, paired share, real taker $ per hour, real taker orders per hour,
order-size quantiles of the real flow.
Usage: python scripts/research5/usdc_flow_anatomy.py 20260924 20260925
"""
import glob, gzip, json, os, sys, urllib.request
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kucoin_trades import parse_line, to_orders, maker_age_ms, LIQ_ID_MIN, PAIR_AGE_MS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REST = "https://api-futures.kucoin.com"


def load_recorded(days):
    rows = []
    for day in days:
        for f in sorted(glob.glob(os.path.join(ROOT, "data", "kucoin_l3_btc", day, "*_trades.jsonl.gz"))):
            try:
                with gzip.open(f, "rt") as fh:
                    for line in fh:
                        r = parse_line(line)
                        if r:
                            rows.append(r)
            except EOFError:
                continue
    return pd.DataFrame(rows, columns=["sym", "ts", "sgn", "px", "size", "tid", "age_ms", "liq"])


def rest_prints(sym):
    """Last 100 public trades of one contract in the same row layout as parse_line."""
    with urllib.request.urlopen(f"{REST}/api/v1/trade/history?symbol={sym}", timeout=15) as r:
        data = json.load(r)["data"]
    rows = []
    for d in data:
        tid = int(d["takerOrderId"])
        rows.append((sym, int(d["ts"]), 1 if d["side"] == "buy" else -1, float(d["price"]), float(d["size"]), tid,
                     maker_age_ms(tid, d["makerOrderId"]), tid > LIQ_ID_MIN))
    return pd.DataFrame(rows, columns=["sym", "ts", "sgn", "px", "size", "tid", "age_ms", "liq"])


def summary(o, prints):
    """One row per contract from taker orders `o` (kucoin_trades.to_orders) and their prints."""
    out = []
    for sym, g in o.groupby("sym"):
        hours = (g.ts.max() - g.ts.min()) / 3.6e12
        real = g[~g.pair & ~g.liq]
        q = real.usd.quantile([0.5, 0.9, 0.99]) if len(real) else pd.Series([float("nan")] * 3)
        out.append(dict(sym=sym, hours=round(hours, 2), prints=int((prints.sym == sym).sum()), orders=len(g), usd=g.usd.sum(),
                        pair_share=g.usd[g.pair].sum() / g.usd.sum(), real_usd_h=real.usd.sum() / hours if hours else float("nan"),
                        real_orders_h=len(real) / hours if hours else float("nan"), real_p50=q.iloc[0], real_p90=q.iloc[1],
                        real_p99=q.iloc[2], liq_usd=g.usd[g.liq].sum()))
    return pd.DataFrame(out)


def main():
    spec = json.load(open(os.path.join(ROOT, "data", "research4", "contracts_active_20261001.json"), encoding="utf-8"))["data"]
    mult = {x["symbol"]: float(x["multiplier"]) for x in spec}
    pd.set_option("display.width", 220)
    p = load_recorded(sys.argv[1:])
    if len(p):
        o = to_orders(p, mult)
        print("recorded", sys.argv[1:], f"(paired = maker order age <= {PAIR_AGE_MS} ms)")
        print(summary(o, p).round(3).to_string(index=False))
        o["hour"] = o.ts // 3_600_000_000_000
        h = o[(o.sym == "XBTUSDCM") & ~o.pair & ~o.liq].groupby("hour").usd.sum()
        print("XBTUSDCM real taker $ per hour: quantiles 10/50/90 =", h.quantile([0.1, 0.5, 0.9]).round(0).tolist(), "hours", len(h))
    snap = []
    for sym in ("XBTUSDCM", "ETHUSDCM", "SOLUSDCM", "XRPUSDCM", "SUIUSDCM"):
        try:
            snap.append(rest_prints(sym))
        except Exception as e:  # snapshot is best-effort
            print("rest", sym, e)
    if snap:
        s = pd.concat(snap, ignore_index=True)
        print("\nREST snapshot: last 100 prints per contract (hours = time those 100 prints span)")
        print(summary(to_orders(s, mult), s).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
