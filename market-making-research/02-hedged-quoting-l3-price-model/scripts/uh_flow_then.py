"""research3: the same flow measures as uh_live_touch_markout.py, on the purchased September hours the backtest used.
Purpose: is the BTC-USDC flow the strategy lives on (taker orders reaching d bp beyond fair value) still there on 2026-10-02?
Same definitions: touch = public touch just before the print; fair = USDT mid x (1 + median basis of the last 60 s, 1 s samples);
depth = g x (fair - px) / px in bp (how far beyond fair the taker paid); nets with our fees (USDC rebate 1.2, USDT rebate 0.7, taker 1.8).
Read-only. usage: uh_flow_then.py <runs tag> [every_nth_hour=1]"""
import bisect, gzip, json, math, os, statistics as st, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tag = sys.argv[1]; step = int(sys.argv[2]) if len(sys.argv) > 2 else 1
R = [x for x in json.load(open(os.path.join(ROOT, "data", "research5", "runs", tag + ".json"), encoding="utf-8")) if "net" in x][::step]
REB_Q, REB_H, FEE_H = OUR_FEE, 0.7, 1.8


def touch_series(path):
    B, A, bb, ba, out = {}, {}, None, None, []
    with gzip.open(path, "rt") as f:
        for l in f:
            o = json.loads(l)
            if o.get("snapshot"):
                B.clear(); A.clear(); bb = ba = None
            for px, q in o["bids"]:
                p = float(px)
                if float(q) == 0:
                    if B.pop(p, None) is not None and p == bb:
                        bb = None
                else:
                    B[p] = 1
                    if bb is not None and p > bb:
                        bb = p
            for px, q in o["asks"]:
                p = float(px)
                if float(q) == 0:
                    if A.pop(p, None) is not None and p == ba:
                        ba = None
                else:
                    A[p] = 1
                    if ba is not None and p < ba:
                        ba = p
            if B and A:
                if bb is None:
                    bb = max(B)
                if ba is None:
                    ba = min(A)
                if ba > bb and (not out or out[-1][1] != bb or out[-1][2] != ba):
                    out.append((o["ts_ns"], bb, ba))
    return out


def wmean(v, w):
    return sum(a * b for a, b in zip(v, w)) / sum(w)


tot = {"hours": 0, "touch": 0, "inside": 0, "usd_touch": 0.0, "usd_inside": 0.0}
P = []            # (depth0, e5, e005, hs, usd)
print("hour          prints/h touch  inside | reaching >=0.25 / >=1 / >=2 bp beyond fair | spread median bp | backtest quote fills")
for r in R:
    feed, day = r["feed"], r["feed"].split("/")[1].split("_")[0]
    base = os.path.join(ROOT, "data", "oos", feed, "kucoin", "swap")
    q = touch_series(os.path.join(base, "BTC-USDC", "feed_raw", f"depth_deltas-{day}.jsonl.gz"))
    h = touch_series(os.path.join(base, "BTC-USDT", "feed_raw", f"depth_deltas-{day}.jsonl.gz"))
    tq = [x[0] for x in q]; thh = [x[0] for x in h]

    def at(series, ts, t):
        i = bisect.bisect_right(ts, t) - 1
        return series[i] if i >= 0 else None
    # 1 s basis samples
    t0 = max(tq[0], thh[0]); t1 = min(tq[-1], thh[-1])
    grid = range(t0, t1, 1_000_000_000)
    bs = []
    for t in grid:
        a, b = at(q, tq, t), at(h, thh, t)
        bs.append(((a[1] + a[2]) / 2) / ((b[1] + b[2]) / 2) - 1)
    sp = sorted((a[2] - a[1]) / a[1] * 1e4 for a in (at(q, tq, t) for t in grid))
    n_t = n_i = 0; d025 = d1 = d2 = 0
    with gzip.open(os.path.join(base, "BTC-USDC", "feed_raw", f"ticks-{day}.jsonl.gz"), "rt") as f:
        for l in f:
            o = json.loads(l)
            t = o["ts_ns"]
            k = (t - t0) // 1_000_000_000
            if k < 60 or t + 30_000_000_000 > t1:
                continue
            book = at(q, tq, t - 1)
            ref = at(h, thh, t)
            px, sz, g = float(o["price"]), float(o["size"]), (1 if o["side"] == "sell" else -1)
            if g > 0:
                kind = "touch" if px <= book[1] + 1e-9 else "inside" if px < book[2] - 1e-9 else "other"
            else:
                kind = "touch" if px >= book[2] - 1e-9 else "inside" if px > book[1] + 1e-9 else "other"
            if kind == "inside":
                n_i += 1; tot["usd_inside"] += px * sz
                continue
            if kind != "touch":
                continue
            n_t += 1; tot["usd_touch"] += px * sz
            b = st.median(bs[k - 60:k])
            mid = (ref[1] + ref[2]) / 2

            def e(dt):
                x = at(h, thh, t + int(dt * 1e9))
                return g * ((x[1] + x[2]) / 2 * (1 + b) - px) / px * 1e4
            d0 = g * (mid * (1 + b) - px) / px * 1e4
            P.append((d0, e(5), e(0.05), (ref[2] - ref[1]) / 2 / mid * 1e4, px * sz))
            d025 += d0 >= 0.25; d1 += d0 >= 1.0; d2 += d0 >= 2.0
    tot["hours"] += 1; tot["touch"] += n_t; tot["inside"] += n_i
    print("%s   %6d %7d   | %6d / %4d / %4d                          | %5.2f            | %d" % (
        r["feed"][-11:], n_t, n_i, d025, d1, d2, sp[len(sp) // 2], r["usdc_fills"]))
H = tot["hours"]
print("\nper hour: touch prints %.0f ($%.0f), inside prints %.0f ($%.0f)" % (tot["touch"] / H, tot["usd_touch"] / H, tot["inside"] / H, tot["usd_inside"] / H))
dep = sorted(p[0] for p in P)
print("depth of touch prints beyond fair bp: p10 %.2f  median %.2f  p90 %.2f" % (dep[int(.1 * len(dep))], st.median(dep), dep[int(.9 * len(dep))]))
for name, sel in [("all touch prints", P)] + [("depth >= %.2f bp" % d, [p for p in P if p[0] >= d]) for d in (0.25, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)]:
    if len(sel) < 5:
        print("%-22s n=%d (too few)" % (name, len(sel))); continue
    w = [p[4] for p in sel]
    print("%-22s per hour %6.1f prints $%-7.0f | edge vs fair at 0 / 5 s: %+5.2f %+5.2f | net taker-hedged %+5.2f | net passive-hedged %+5.2f" % (
        name, len(sel) / H, sum(w) / H, wmean([p[0] for p in sel], w), wmean([p[1] for p in sel], w),
        wmean([p[2] + REB_Q - FEE_H - p[3] for p in sel], w), wmean([p[1] + REB_Q + REB_H for p in sel], w)))
