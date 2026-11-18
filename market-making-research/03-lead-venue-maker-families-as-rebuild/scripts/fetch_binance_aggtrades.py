#!/usr/bin/env python3
"""research5 L-3: pull Binance USD-M futures aggregated trades for the TradFi perps that KuCoin's own index is built from.

Public REST, read-only, no key: GET https://fapi.binance.com/fapi/v1/aggTrades (weight 20, <=1000 rows; the server only
serves the most recent ~2 days). We page forward by aggregate trade id from the first trade at/after `start`.
Output: data/research5/binance_agg/<BINANCE_SYMBOL>_<start_ms>.csv.gz with rows  T_ms,price,qty,buyer_is_maker(1/0)
(buyer_is_maker=1 means the taker SOLD). A finished file is never re-fetched; a partial file resumes from its last id.
The Binance clock (T) is the matching-engine trade time in ms.
Usage: python scripts/research5/fetch_binance_aggtrades.py <start 'YYYY-MM-DDTHH:MM' UTC> <end ...> SYM1,SYM2,...
"""
import gzip, json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research5", "binance_agg")
BASE = "https://fapi.binance.com/fapi/v1/aggTrades"
WEIGHT_SOFT_CAP = 1800  # of 2400 per minute


def utc_ms(s):
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc).timestamp() * 1000)


def get(url):
    """One request with back-off. Returns (rows, used_weight_1m)."""
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research5-public"}), timeout=20) as r:
                return json.loads(r.read()), int(r.headers.get("X-MBX-USED-WEIGHT-1M") or 0)
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                time.sleep(float(e.headers.get("Retry-After") or 30) + 1)
                continue
            if attempt == 7:
                raise
            time.sleep(2 + 2 * attempt)
        except Exception:  # noqa: BLE001
            if attempt == 7:
                raise
            time.sleep(2 + 2 * attempt)
    raise RuntimeError("unreachable")


def next_url(sym, start_ms, last_id):
    """First page is addressed by time, later pages by the id after the last one we hold."""
    if last_id is None:
        return f"{BASE}?symbol={sym}&startTime={start_ms}&limit=1000"
    return f"{BASE}?symbol={sym}&fromId={last_id + 1}&limit=1000"


def fetch(sym, start_ms, end_ms):
    path = os.path.join(OUT, f"{sym}_{start_ms}.csv.gz")
    done = path + ".done"
    if os.path.exists(done):
        return -1
    last_id, n = None, 0
    idp = path + ".lastid"
    if os.path.exists(idp) and os.path.exists(path):
        last_id = int(open(idp).read().strip())
    with gzip.open(path, "at") as fh:
        while True:
            rows, used = get(next_url(sym, start_ms, last_id))
            if not rows:
                break
            keep = [x for x in rows if x["T"] <= end_ms]
            for x in keep:
                fh.write(f"{x['T']},{x['p']},{x['q']},{1 if x['m'] else 0}\n")
            n += len(keep)
            last_id = rows[-1]["a"]
            fh.flush()
            with open(idp, "w") as f:
                f.write(str(last_id))
            if len(keep) < len(rows) or len(rows) < 1000:
                break
            if used > WEIGHT_SOFT_CAP:
                time.sleep(15)
    open(done, "w").close()
    return n


def main():
    start_ms, end_ms = utc_ms(sys.argv[1]), utc_ms(sys.argv[2])
    os.makedirs(OUT, exist_ok=True)
    for sym in sys.argv[3].split(","):
        try:
            n = fetch(sym, start_ms, end_ms)
        except Exception as e:  # noqa: BLE001
            print(time.strftime("%H:%M:%S"), sym, "ERR", repr(e)[:200], flush=True)
            continue
        print(time.strftime("%H:%M:%S"), sym, "skip (done)" if n < 0 else n, flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
