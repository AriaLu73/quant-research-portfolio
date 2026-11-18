#!/usr/bin/env python3
"""research5 (closed-hours liquidity provision): pull KuCoin public history for the TradFi-linked contracts.

Read-only public REST, no key:
  funding   GET /api/v1/contract/funding-rates?symbol=&from=&to=      (<=100 rows per call, newest first)
  klines    GET /api/v1/kline/query?symbol=&granularity=5&from=&to=   (<=200 rows per call)
Output (data/research5/):
  funding/<symbol>.csv   ts_ms,rate          (ascending)
  kline5/<symbol>.csv    ts_ms,open,high,low,close,volume_contracts,turnover_usd   (ascending, 5-minute bars)
Usage: python scripts/research5/fetch_public.py funding|kline5 [start_YYYYMMDD]
"""
import json, os, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(ROOT, "data", "research4", "tradfi_contracts_20261001.json")
OUT = os.path.join(ROOT, "data", "research5")
BASE = "https://api-futures.kucoin.com"
MIN_GAP_S = 0.05
_lock, _next, _pause = threading.Lock(), [0.0], [0.0]


def throttle():
    with _lock:
        now = time.time()
        t = max(now, _next[0], _pause[0])
        _next[0] = t + MIN_GAP_S
    if t > now:
        time.sleep(t - now)


def get(path):
    last = None
    for attempt in range(8):
        throttle()
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": "research5-public"})
            with urllib.request.urlopen(req, timeout=20) as r:
                rem = r.headers.get("gw-ratelimit-remaining")
                if rem is not None and int(rem) < 150:
                    _pause[0] = time.time() + 5
                d = json.loads(r.read())
            if d.get("code") == "200000":
                return d.get("data") or []
            if d.get("code") == "429000":
                _pause[0] = time.time() + 10
                continue
            raise RuntimeError(str(d)[:200])
        except Exception as e:  # noqa: BLE001
            last = e
            _pause[0] = time.time() + 2 + 2 * attempt
    raise last


def windows(start_ms, end_ms, step_ms):
    """Half-open windows [a, b) covering [start_ms, end_ms)."""
    a = start_ms
    while a < end_ms:
        yield a, min(a + step_ms, end_ms)
        a += step_ms


def fetch_funding(sym, start_ms, end_ms):
    rows = {}
    for a, b in windows(start_ms, end_ms, 25 * 86_400_000):  # 4h funding -> 150 rows in 25 d; paged below
        lo = a
        while lo < b:
            page = get(f"/api/v1/contract/funding-rates?symbol={sym}&from={lo}&to={b}")
            if not page:
                break
            for x in page:
                rows[int(x["timepoint"])] = float(x["fundingRate"])
            oldest = min(int(x["timepoint"]) for x in page)
            if len(page) < 100 or oldest <= lo:
                break
            b = oldest - 1
    return sorted(rows.items())


def fetch_kline5(sym, start_ms, end_ms):
    rows = {}
    for a, b in windows(start_ms, end_ms, 200 * 300_000):
        for x in get(f"/api/v1/kline/query?symbol={sym}&granularity=5&from={a}&to={b}"):
            rows[int(x[0])] = x[1:7]
    return [(t, *v) for t, v in sorted(rows.items())]


def job(args):
    kind, sym, start_ms, end_ms = args
    d = os.path.join(OUT, kind)
    path = os.path.join(d, sym + ".csv")
    if os.path.exists(path):
        return sym, -1
    try:
        rows = fetch_funding(sym, start_ms, end_ms) if kind == "funding" else fetch_kline5(sym, start_ms, end_ms)
    except Exception as e:  # noqa: BLE001
        print("ERR", sym, repr(e)[:160], flush=True)
        return sym, -2
    with open(path + ".part", "w") as fh:
        for r in rows:
            fh.write(",".join(str(v) for v in r) + "\n")
    os.replace(path + ".part", path)
    return sym, len(rows)


def main():
    kind = sys.argv[1]
    start = sys.argv[2] if len(sys.argv) > 2 else "20260301"
    start_ms = int(datetime(int(start[:4]), int(start[4:6]), int(start[6:]), tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(time.time() * 1000)
    syms = [x["sym"] for x in json.load(open(SPEC, encoding="utf-8"))]
    os.makedirs(os.path.join(OUT, kind), exist_ok=True)
    with ThreadPoolExecutor(12) as ex:
        for k, (s, n) in enumerate(ex.map(job, [(kind, s, start_ms, end_ms) for s in syms])):
            if n != -1 and (k % 10 == 0 or n < 0):
                print(time.strftime("%H:%M:%S"), k + 1, "/", len(syms), s, n, flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
