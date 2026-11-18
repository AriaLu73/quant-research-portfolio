"""research3: public BTC-USDC spread on the backtest hours (purchased September data) versus the live run of 2026-10-02.
Read-only. usage: uh_spread_then_now.py <runs tag> [symbol]"""
import gzip, json, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tag = sys.argv[1]; sym = sys.argv[2] if len(sys.argv) > 2 else "BTC-USDC"
R = [x for x in json.load(open(os.path.join(ROOT, "data", "research5", "runs", tag + ".json"), encoding="utf-8")) if "net" in x]
allsp = []
print("hour         spread bp p10 / median / p90   share of time spread <= 1 bp   quote fills in the backtest")
for r in R:
    feed, day = r["feed"], r["feed"].split("/")[1].split("_")[0]
    p = os.path.join(ROOT, "data", "oos", feed, "kucoin", "swap", sym, "feed_raw", f"depth_deltas-{day}.jsonl.gz")
    B, A, ts, sp = {}, {}, [], []
    with gzip.open(p, "rt") as f:
        for l in f:
            o = json.loads(l)
            if o.get("snapshot"):
                B.clear(); A.clear()
            for side, book in (("bids", B), ("asks", A)):
                for px, q in o[side]:
                    if float(q) == 0:
                        book.pop(float(px), None)
                    else:
                        book[float(px)] = 1
            if B and A:
                b, a = max(B), min(A)
                if a > b:
                    ts.append(o["ts_ns"]); sp.append((a - b) / ((a + b) / 2) * 1e4)
    ts, sp = np.array(ts), np.array(sp)
    g = np.arange(ts[0] + 60_000_000_000, ts[-1], 1_000_000_000)
    s = sp[np.clip(np.searchsorted(ts, g, "right") - 1, 0, len(ts) - 1)]
    allsp.append(s)
    print("%s   %5.2f / %5.2f / %5.2f              %5.1f%%                        %d" % (
        r["feed"][-11:], np.quantile(s, .1), np.median(s), np.quantile(s, .9), 100 * (s <= 1.0).mean(), r["usdc_fills"]))
s = np.concatenate(allsp)
print("all hours    %5.2f / %5.2f / %5.2f              %5.1f%%" % (np.quantile(s, .1), np.median(s), np.quantile(s, .9), 100 * (s <= 1.0).mean()))
