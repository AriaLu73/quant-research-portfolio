"""research3: where our live orders stood in the book (first live run, 2026-10-02 16:17-17:27 UTC, from the WAL extract).
  quotes (BTC-USDC): how many public price levels and how much size were in front of our near quote (top 5 levels recorded)
  hedge  (BTC-USDT): size already resting at the touch price when our passive hedge order joined it, and how it ended
usage: uh_live_queue.py <extract.jsonl.gz>"""
import bisect, gzip, json, statistics as st, sys
from collections import defaultdict

rows = [json.loads(l) for l in gzip.open(sys.argv[1], "rt", encoding="utf-8")]
QS, HS = "BTC-USDC", "BTC-USDT"
new, rep, fills = {}, defaultdict(list), defaultdict(float)
for r in rows:
    if r[0] == "N":
        new[r[2]] = {"sym": r[3], "side": r[4], "px": r[5], "qty": r[6], "t_req": r[1]}
    elif r[0] == "R":
        rep[r[3]].append((r[1], r[2], r[5], r[6]))
    elif r[0] == "F":
        fills[r[3]] += r[7]
orders = []
for oid, o in new.items():
    push = [x for x in rep.get(oid, []) if abs(x[0] - x[1]) >= 200_000 and x[1] > 10 ** 18]
    opens = [x[0] for x in push if x[2] in ("submitted", "partially_filled")]
    ends = [x[0] for x in push if x[2] in ("cancelled", "filled")]
    if opens:
        o.update(oid=oid, t_open=min(opens), t_end=min(ends) if ends else None, filled=fills.get(oid, 0.0))
        orders.append(o)
dq = [(r[1], r[4], r[5]) for r in rows if r[0] == "D" and r[3] == QS]
dh = [(r[1], r[4][0], r[5][0]) for r in rows if r[0] == "D" and r[3] == HS]
tq, th = [x[0] for x in dq], [x[0] for x in dh]


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))]


# ---------------------------------------------------------------- near quotes
near = [o for o in orders if o["sym"] == QS and o["qty"] < 0.01]
ev = sorted([(o["t_open"], 1, o) for o in near] + [(o["t_end"], -1, o) for o in near if o["t_end"]], key=lambda x: (x[0], x[1]))
t0, t1 = min(o["t_open"] for o in near), max(o["t_end"] or o["t_open"] for o in near)
live, j = {}, 0
rank, ahead_btc, ahead_usd, alone, beyond, n = defaultdict(int), [], [], 0, 0, 0
for t in range(t0 + 90_000_000_000, t1, 100_000_000):
    while j < len(ev) and ev[j][0] <= t:
        if ev[j][1] > 0:
            live[ev[j][2]["oid"]] = ev[j][2]
        else:
            live.pop(ev[j][2]["oid"], None)
        j += 1
    i = bisect.bisect_right(tq, t) - 1
    if i < 0:
        continue
    for o in live.values():
        lv = dq[i][1] if o["side"] == "buy" else dq[i][2]
        better = [(p, s) for p, s in lv if (p > o["px"] + 1e-9 if o["side"] == "buy" else p < o["px"] - 1e-9)]
        same = [s for p, s in lv if abs(p - o["px"]) < 1e-9]
        n += 1
        if not same and len(better) >= 5:
            beyond += 1                                   # our price is worse than all five recorded levels
            rank["6th or deeper"] += 1
            ahead_btc.append(sum(s for _, s in better))
            continue
        rank["%d" % (len(better) + 1)] += 1
        ahead_btc.append(sum(s for _, s in better))
        ahead_usd.append(sum(p * s for p, s in better))
        if same and same[0] - o["qty"] < 1e-9:
            alone += 1
print("near quotes (BTC-USDC, v7): %d samples of a resting near quote" % n)
print("  price level we stood on (1 = best price): " + "  ".join("%s: %.1f%%" % (k, 100 * v / n) for k, v in sorted(rank.items())))
print("  size resting at better prices than ours, BTC: median %.4f  p25 %.4f  p75 %.4f (our quote: 0.0044)%s" % (
    st.median(ahead_btc), q(ahead_btc, .25), q(ahead_btc, .75), " - a lower bound when we were beyond the 5 recorded levels" if beyond else ""))
print("  in $: median %.0f | alone at our own price level %.0f%% of the time" % (st.median(ahead_usd) if ahead_usd else float("nan"), 100 * alone / max(n - beyond, 1)))

# ---------------------------------------------------------------- hedge orders
hedge = [o for o in orders if o["sym"] == HS and o["px"] is not None]
print("\nhedge orders (BTC-USDT, passive at the touch): %d" % len(hedge))
ahead, life = [], []
for o in sorted(hedge, key=lambda x: x["t_open"]):
    i = bisect.bisect_right(th, o["t_req"]) - 1
    b, a = dh[i][1], dh[i][2]
    lvl = b if o["side"] == "buy" else a
    at_touch = abs(lvl[0] - o["px"]) < 1e-9
    sz = lvl[1] if at_touch else float("nan")
    dur = (o["t_end"] - o["t_open"]) / 1e9 if o["t_end"] else float("nan")
    ahead.append(sz); life.append(dur)
    print("  %s %.3f @ %.1f | size already at that price %.3f BTC ($%.0f) = %.0f x our order | rested %.2f s | %s" % (
        o["side"], o["qty"], o["px"], sz, sz * o["px"], sz / o["qty"] if o["qty"] else 0, dur, "FILLED %.3f" % o["filled"] if o["filled"] > 0 else "cancelled (re-pegged)"))
v = [x for x in ahead if x == x]
print("  size in front of us when we joined: median %.2f BTC ($%.0f), min %.2f, max %.2f" % (st.median(v), st.median(v) * 85000, min(v), max(v)))
