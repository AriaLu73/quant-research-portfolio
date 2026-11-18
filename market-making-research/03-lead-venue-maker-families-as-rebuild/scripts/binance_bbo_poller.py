#!/usr/bin/env python3
"""research5: record Binance USD-M best bid/ask for the TradFi perps (public REST, read-only, no key).

Why: L-4b showed that Binance's LAST TRADE price is too noisy a reference (after a 'stale quote' signal Binance itself
reverted ~5 bp within 5 s). A quote-based reference needs the best bid/ask, which has no public history.
One call per second to GET /fapi/v1/ticker/bookTicker (all symbols, weight 5); a row is written only when a symbol's
bid or ask changed. Output: data/research5/binance_bbo/<YYYYMMDD>.csv.gz rows
  recv_ms,symbol,exch_time_ms,bid,bid_qty,ask,ask_qty
Stop: create data/research5/binance_bbo/STOP, or let --hours run out.
Usage: python scripts/research5/binance_bbo_poller.py --hours 192
"""
import argparse, gzip, json, os, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research5", "binance_bbo")
URL = "https://fapi.binance.com/fapi/v1/ticker/bookTicker"


def tradfi_symbols():
    """Binance symbols that share a name with a KuCoin TradFi contract (KuCoin name minus the trailing M)."""
    spec = json.load(open(os.path.join(ROOT, "data", "research4", "tradfi_contracts_20261001.json"), encoding="utf-8"))
    return {x["sym"][:-1] for x in spec}


def changed(last, row):
    """True when this symbol's bid/ask (price or size) differs from the last row we wrote for it."""
    key = (row["bidPrice"], row["bidQty"], row["askPrice"], row["askQty"])
    if last.get(row["symbol"]) == key:
        return False
    last[row["symbol"]] = key
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=192)
    ap.add_argument("--interval", type=float, default=1.0)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    want, last, t_end, n, err = tradfi_symbols(), {}, time.time() + a.hours * 3600, 0, 0
    while time.time() < t_end and not os.path.exists(os.path.join(OUT, "STOP")):
        t0 = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "research5-public"}), timeout=10) as r:
                data = json.loads(r.read())
            recv = int(time.time() * 1000)
            rows = [x for x in data if x["symbol"] in want and changed(last, x)]
            if rows:
                with gzip.open(os.path.join(OUT, time.strftime("%Y%m%d", time.gmtime()) + ".csv.gz"), "at") as fh:  # one gzip member per write
                    for x in rows:
                        fh.write(f"{recv},{x['symbol']},{x['time']},{x['bidPrice']},{x['bidQty']},{x['askPrice']},{x['askQty']}\n")
            n += 1
        except Exception:  # noqa: BLE001
            err += 1
            time.sleep(2)
        if n % 300 == 1:
            with open(os.path.join(OUT, "status.txt"), "w") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()) + f" polls={n} errors={err}\n")
        time.sleep(max(0.0, a.interval - (time.time() - t0)))


if __name__ == "__main__":
    main()
