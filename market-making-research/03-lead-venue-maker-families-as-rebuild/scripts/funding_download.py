#!/usr/bin/env python3
"""research5 F-1: public funding-rate history and hourly klines of USDT perpetuals on KuCoin, Binance, Bybit and OKX.

Public REST only (no key, no orders, nothing paid). Universe = every open KuCoin USDT perpetual; the other venues are
downloaded only for coins KuCoin also lists. Resumable: one JSON line per (venue, kind, symbol) is appended to
data/research5/funding/raw_<venue>_<kind>.jsonl and symbols already there are skipped.
  funding rows: [time_ms, rate]            klines rows: [bar_open_ms, open, high, low, close, turnover_usd]
Usage: python scripts/detach.py --log logs/r5_funding_download.log -- .venv/Scripts/python.exe scripts/research5/funding_download.py
"""
import argparse, datetime as dt, glob, json, os, re, threading, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research5", "funding")
START_MS = int(dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
HOUR_MS = 3_600_000
PAUSE_S = {("binance", "funding"): 0.65, ("binance", "klines"): 0.3, ("kucoin", "funding"): 0.12, ("kucoin", "klines"): 0.12,
           ("bybit", "funding"): 0.1, ("bybit", "klines"): 0.1, ("okx", "funding"): 0.22, ("okx", "klines"): 0.12}


def norm_base(base):
    """Venue-independent coin key: XBT -> BTC; multiplier prefixes / suffixes (1000PEPE, 1MBABYDOGE, SHIB1000) are dropped.
    The price scale between venues is checked later from the prices themselves, not from the name."""
    b = base.upper()
    b = {"XBT": "BTC"}.get(b, b)
    b = re.sub(r"^(1000000|100000|10000|1000|1M)(?=[A-Z])", "", b)
    b = re.sub(r"(?<=[A-Z])1000$", "", b)
    return b


def get(url, tries=6):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                raise
            time.sleep(min(60, 5 * (k + 1)) if e.code in (418, 429, 403) else 2 * (k + 1))
        except Exception:  # noqa: BLE001 - network hiccup: retry
            time.sleep(2 * (k + 1))
    raise RuntimeError("giving up on " + url)


def get_bybit(url, tries=8):
    """Bybit answers a rate-limit hit with HTTP 200 and retCode != 0: wait and ask again."""
    for k in range(tries):
        r = get(url)
        if r.get("retCode") == 0:
            return r
        time.sleep(2 * (k + 1))
    raise RuntimeError("bybit retCode " + str(r.get("retCode")) + " " + url)


# ------------------------------------------------------------------ universes: key -> venue symbol
def universe_kucoin():
    c = get("https://api-futures.kucoin.com/api/v1/contracts/active")["data"]
    out = {}
    for x in c:
        if x.get("settleCurrency") == "USDT" and x.get("type") == "FFWCSX" and x.get("status") == "Open":
            out[norm_base(x["baseCurrency"])] = dict(sym=x["symbol"], interval_h=x["fundingRateGranularity"] / HOUR_MS,
                                                     turnover24h=x.get("turnoverOf24h"), cap=x.get("fundingRateCap"), first_open=x.get("firstOpenDate"))
    return out


def universe_binance():
    info = {x["symbol"]: x for x in get("https://fapi.binance.com/fapi/v1/fundingInfo")}
    out = {}
    for x in get("https://fapi.binance.com/fapi/v1/exchangeInfo")["symbols"]:
        if x["contractType"] == "PERPETUAL" and x["quoteAsset"] == "USDT" and x["status"] == "TRADING":
            out[norm_base(x["baseAsset"])] = dict(sym=x["symbol"], interval_h=info.get(x["symbol"], {}).get("fundingIntervalHours", 8))
    return out


def universe_bybit():
    out, cursor = {}, ""
    while True:
        r = get("https://api.bybit.com/v5/market/instruments-info?category=linear&limit=1000" + (f"&cursor={cursor}" if cursor else ""))["result"]
        for x in r["list"]:
            if x["quoteCoin"] == "USDT" and x["contractType"] == "LinearPerpetual" and x["status"] == "Trading":
                out[norm_base(x["baseCoin"])] = dict(sym=x["symbol"], interval_h=x["fundingInterval"] / 60)
        cursor = r.get("nextPageCursor") or ""
        if not cursor:
            return out


def universe_okx():
    out = {}
    for x in get("https://www.okx.com/api/v5/public/instruments?instType=SWAP")["data"]:
        if x["settleCcy"] == "USDT" and x["state"] == "live" and x["instId"].endswith("-USDT-SWAP"):
            out[norm_base(x["instId"].split("-")[0])] = dict(sym=x["instId"], interval_h=None)
    return out


# ------------------------------------------------------------------ per-symbol fetchers; all return rows sorted by time
def funding_kucoin(sym, pause, now):
    rows, to = {}, now
    while to > START_MS:
        d = get(f"https://api-futures.kucoin.com/api/v1/contract/funding-rates?symbol={sym}&from={START_MS}&to={to}").get("data") or []
        time.sleep(pause)
        for x in d:
            rows[x["timepoint"]] = float(x["fundingRate"])
        if len(d) < 100:
            break
        to = min(x["timepoint"] for x in d) - 1
    return sorted(rows.items())


def funding_binance(sym, pause, now):
    rows, st = {}, START_MS
    while True:
        d = get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&startTime={st}&limit=1000")
        time.sleep(pause)
        for x in d:
            rows[x["fundingTime"]] = float(x["fundingRate"])
        if len(d) < 1000:
            break
        st = max(x["fundingTime"] for x in d) + 1
    return sorted(rows.items())


def funding_bybit(sym, pause, now):
    rows, end = {}, now
    while end > START_MS:
        d = get_bybit(f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={sym}&endTime={end}&limit=200")["result"]["list"]
        time.sleep(pause)
        for x in d:
            rows[int(x["fundingRateTimestamp"])] = float(x["fundingRate"])
        if len(d) < 200:
            break
        end = min(int(x["fundingRateTimestamp"]) for x in d) - 1
    return sorted((t, r) for t, r in rows.items() if t >= START_MS)


def funding_okx(sym, pause, now):
    rows, after = {}, ""
    while True:
        d = get(f"https://www.okx.com/api/v5/public/funding-rate-history?instId={sym}&limit=100" + (f"&after={after}" if after else "")).get("data") or []
        time.sleep(pause)
        for x in d:
            rows[int(x["fundingTime"])] = float(x["realizedRate"] or x["fundingRate"])
        if len(d) < 100 or min(int(x["fundingTime"]) for x in d) < START_MS:
            break
        after = str(min(int(x["fundingTime"]) for x in d))
    return sorted((t, r) for t, r in rows.items() if t >= START_MS)


def klines_kucoin(sym, pause, now):
    rows, st = {}, START_MS
    while st < now:
        d = get(f"https://api-futures.kucoin.com/api/v1/kline/query?symbol={sym}&granularity=60&from={st}&to={now}").get("data") or []
        time.sleep(pause)
        for x in d:
            rows[int(x[0])] = [float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[6]) if len(x) > 6 else None]
        if len(d) < 200:
            break
        st = max(int(x[0]) for x in d) + HOUR_MS
    return [[t] + v for t, v in sorted(rows.items())]


def klines_binance(sym, pause, now):
    rows, st = {}, START_MS
    while st < now:
        d = get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1h&startTime={st}&limit=1500")
        time.sleep(pause)
        for x in d:
            rows[int(x[0])] = [float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[7])]
        if len(d) < 1500:
            break
        st = max(int(x[0]) for x in d) + HOUR_MS
    return [[t] + v for t, v in sorted(rows.items())]


def klines_bybit(sym, pause, now):
    rows, st = {}, START_MS
    while st < now:
        d = get_bybit(f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval=60&start={st}&end={st + 999 * HOUR_MS}&limit=1000")["result"]["list"]
        time.sleep(pause)
        for x in d:
            rows[int(x[0])] = [float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[6])]
        st += 1000 * HOUR_MS
    return [[t] + v for t, v in sorted(rows.items())]


def klines_okx(sym, pause, now):
    rows, after = {}, str(now)
    while True:
        d = get(f"https://www.okx.com/api/v5/market/history-candles?instId={sym}&bar=1H&limit=100&after={after}").get("data") or []
        time.sleep(pause)
        for x in d:
            rows[int(x[0])] = [float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[7])]
        if len(d) < 100 or min(int(x[0]) for x in d) < START_MS:
            break
        after = str(min(int(x[0]) for x in d))
    return [[t] + v for t, v in sorted(rows.items()) if t >= START_MS]


FETCH = {("kucoin", "funding"): funding_kucoin, ("binance", "funding"): funding_binance, ("bybit", "funding"): funding_bybit, ("okx", "funding"): funding_okx,
         ("kucoin", "klines"): klines_kucoin, ("binance", "klines"): klines_binance, ("bybit", "klines"): klines_bybit, ("okx", "klines"): klines_okx}


def done_symbols(venue, kind):
    """Symbols already on disk in any shard file of this venue and kind."""
    out = set()
    for path in glob.glob(os.path.join(OUT, f"raw_{venue}_{kind}*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.add(json.loads(line)["sym"])
                except Exception:  # noqa: BLE001 - a line cut off by a kill: fetched again
                    pass
    return out


def worker(venue, syms, kinds, now, shard=""):
    for kind in kinds:
        path = os.path.join(OUT, f"raw_{venue}_{kind}{shard}.jsonl")
        done = done_symbols(venue, kind)
        todo = [(k, s) for k, s in syms if s not in done]
        print(time.strftime("%T"), venue, kind, "to fetch", len(todo), "already", len(done), flush=True)
        with open(path, "a", encoding="utf-8") as f:
            for n, (key, sym) in enumerate(todo, 1):
                try:
                    rows = FETCH[(venue, kind)](sym, PAUSE_S[(venue, kind)], now)
                except Exception as e:  # noqa: BLE001 - one bad symbol must not stop the venue
                    print(time.strftime("%T"), venue, kind, sym, "FAILED", repr(e)[:150], flush=True)
                    continue
                f.write(json.dumps(dict(key=key, sym=sym, rows=rows)) + "\n")
                f.flush()
                if n % 50 == 0:
                    print(time.strftime("%T"), venue, kind, n, "/", len(todo), flush=True)
        print(time.strftime("%T"), venue, kind, "done", flush=True)


def spreads_snapshot(uni):
    """One snapshot of best bid / ask of every contract on every venue (rough: a single moment)."""
    out = []
    a = {x["symbol"]: x for x in get("https://api-futures.kucoin.com/api/v1/allTickers")["data"]}
    b = {x["symbol"]: x for x in get("https://fapi.binance.com/fapi/v1/ticker/bookTicker")}
    y = {x["symbol"]: x for x in get("https://api.bybit.com/v5/market/tickers?category=linear")["result"]["list"]}
    o = {x["instId"]: x for x in get("https://www.okx.com/api/v5/market/tickers?instType=SWAP")["data"]}
    fields = {"kucoin": (a, "bestBidPrice", "bestAskPrice"), "binance": (b, "bidPrice", "askPrice"), "bybit": (y, "bid1Price", "ask1Price"), "okx": (o, "bidPx", "askPx")}
    for venue, m in uni.items():
        src, fb, fa = fields[venue]
        for key, v in m.items():
            x = src.get(v["sym"])
            if x and x.get(fb) and x.get(fa):
                out.append(dict(ts=int(time.time()), venue=venue, key=key, sym=v["sym"], bid=float(x[fb]), ask=float(x[fa])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--venues", default="kucoin,binance,bybit,okx")
    ap.add_argument("--kinds", default="funding,klines")
    ap.add_argument("--spreads-only", action="store_true")
    ap.add_argument("--shard", default="", help="i/n: only every n-th symbol starting at i, written to its own file (parallel runs)")
    ns = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    uni = dict(kucoin=universe_kucoin(), binance=universe_binance(), bybit=universe_bybit(), okx=universe_okx())
    keys = set(uni["kucoin"])
    for v in ("binance", "bybit", "okx"):
        uni[v] = {k: x for k, x in uni[v].items() if k in keys}
    with open(os.path.join(OUT, "universe.json"), "w", encoding="utf-8") as f:
        json.dump(uni, f)
    print("universe:", {v: len(m) for v, m in uni.items()}, flush=True)
    snap = spreads_snapshot(uni)
    with open(os.path.join(OUT, "spreads.jsonl"), "a", encoding="utf-8") as f:
        for r in snap:
            f.write(json.dumps(r) + "\n")
    print("spread snapshot rows", len(snap), flush=True)
    if ns.spreads_only:
        return
    now = int(time.time() * 1000) // HOUR_MS * HOUR_MS
    i, n = (int(x) for x in ns.shard.split("/")) if ns.shard else (0, 1)
    th = [threading.Thread(target=worker, args=(v, sorted((k, x["sym"]) for k, x in uni[v].items())[i::n], ns.kinds.split(","), now,
                                                f".s{i}" if ns.shard else ""))
          for v in ns.venues.split(",")]
    for t in th:
        t.start()
    for t in th:
        t.join()
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
