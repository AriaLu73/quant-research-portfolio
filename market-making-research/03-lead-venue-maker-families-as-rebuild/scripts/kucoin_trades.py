#!/usr/bin/env python3
"""research5: turn our public KuCoin trade recordings into one row per taker order.

Input: data/research4/trades_ws/<YYYYMMDD>/*.jsonl.gz (lines "<recv_ns>\t<json>", topic /contractMarket/execution, written by
research4/tradfi_trades_recorder.py). Public data, read-only.
Paired print (a participant trading with its own just-posted order): maker order age = (takerOrderId - makerOrderId) >> 22
milliseconds <= 20 and not a liquidation id (same rule as research4 EXP-1).
Output: data/research5/ku_orders_<day>.parquet with columns
  sym, ts (ns, exchange time of the first print), sgn (+1 taker buy / -1 taker sell), px_first, px_last, px_vwap, usd, n, pair, liq
Usage: python scripts/research5/kucoin_trades.py 20261001
"""
import glob, gzip, json, os, sys
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAIR_AGE_MS = 20
LIQ_ID_MIN = 6 * 10**17


def maker_age_ms(taker_id, maker_id):
    """Age of the maker order when the taker order arrived, from the snowflake-style order ids (ms in the high bits)."""
    return (int(taker_id) - int(maker_id)) >> 22


def parse_line(line):
    """One recorder line -> (sym, ts_ns, sgn, px, size, taker_id, age_ms, liq) or None."""
    i = line.find("\t")
    if i <= 0:
        return None
    try:
        m = json.loads(line[i + 1:])
    except ValueError:
        return None
    d = m.get("data")
    if not d or m.get("subject") != "match" or not d.get("makerOrderId") or not d.get("takerOrderId"):
        return None
    px = float(d["price"])
    if px <= 0:
        return None
    tid = int(d["takerOrderId"])
    return (d["symbol"], int(d["ts"]), 1 if d["side"] == "buy" else -1, px, float(d["size"]), tid,
            maker_age_ms(tid, d["makerOrderId"]), tid > LIQ_ID_MIN)


def to_orders(prints, mult):
    """Prints DataFrame (sym, ts, sgn, px, size, tid, age_ms, liq) -> one row per taker order.
    A taker order is paired only if every one of its prints is a paired print."""
    p = prints.drop_duplicates(["sym", "ts", "tid", "px", "size", "age_ms"]).copy()
    p["usd"] = p.px * p["size"] * p.sym.map(mult)
    p["pair_print"] = (p.age_ms <= PAIR_AGE_MS) & ~p.liq
    p["pxusd"] = p.px * p.usd
    p = p.sort_values(["sym", "tid", "ts"])
    g = p.groupby(["sym", "tid"], sort=False)
    o = g.agg(ts=("ts", "first"), sgn=("sgn", "first"), px_first=("px", "first"), px_last=("px", "last"), usd=("usd", "sum"),
              pxusd=("pxusd", "sum"), n=("px", "size"), pair=("pair_print", "all"), liq=("liq", "any")).reset_index()
    o["px_vwap"] = o.pxusd / o.usd
    return o.drop(columns=["pxusd", "tid"]).sort_values(["sym", "ts"]).reset_index(drop=True)


def load_prints(day):
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "research4", "trades_ws", day, "*.jsonl.gz"))):
        try:
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    r = parse_line(line)
                    if r:
                        rows.append(r)
        except EOFError:  # the file for the current hour is still being written
            continue
    return pd.DataFrame(rows, columns=["sym", "ts", "sgn", "px", "size", "tid", "age_ms", "liq"])


def main():
    day = sys.argv[1]
    spec = json.load(open(os.path.join(ROOT, "data", "research4", "contracts_active_20261001.json"), encoding="utf-8"))["data"]
    mult = {x["symbol"]: float(x["multiplier"]) for x in spec}
    o = to_orders(load_prints(day), mult)
    os.makedirs(os.path.join(ROOT, "data", "research5"), exist_ok=True)
    o.to_parquet(os.path.join(ROOT, "data", "research5", f"ku_orders_{day}.parquet"))
    hours = (o.ts.max() - o.ts.min()) / 3.6e12
    real = o[~o.pair]
    s = real.groupby("sym").agg(real_usd=("usd", "sum"), n=("usd", "size")).sort_values("real_usd", ascending=False)
    print(f"{day}: {len(o)} taker orders over {hours:.1f} h; paired share of $ {o.usd[o.pair].sum() / o.usd.sum():.3f}; real $ {real.usd.sum():,.0f}")
    print(s.head(40).round(0).to_string())


if __name__ == "__main__":
    main()
