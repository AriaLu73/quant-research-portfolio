"""research3: can speed put an order at the front of the BTC-USDT touch queue? (first live run recording, 2026-10-02 16:17-17:27 UTC)
A touch price is 'born' when the best bid moves UP to a new price (or the best ask DOWN): the level did not exist as the touch
before and starts with whatever was posted first. We measure how much size is already there x ms after the birth, and how old
the level was when our own hedge orders joined it. Times are our feed's publish times (old pipeline: median lag 0.5 ms, p90 15 ms).
usage: uh_queue_birth.py <extract.jsonl.gz>"""
import bisect, gzip, json, statistics as st, sys
from collections import defaultdict
rows = [json.loads(l) for l in gzip.open(sys.argv[1], "rt", encoding="utf-8")]
d = [(r[1], r[4][0][0], r[4][0][1], r[5][0][0], r[5][0][1]) for r in rows if r[0] == "D" and r[3] == "BTC-USDT"]   # t, bid, bsz, ask, asz
t = [x[0] for x in d]


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))]


HOR = (0, 1, 2, 5, 10, 50, 200)
grow = {h: [] for h in HOR}
life = []
births = []          # (t, side, px)
for side, ip, isz, up in (("bid", 1, 2, 1), ("ask", 3, 4, -1)):
    i = 1
    while i < len(d):
        if up * (d[i][ip] - d[i - 1][ip]) > 1e-9:               # price improved: a new touch level
            t0, px = d[i][0], d[i][ip]
            births.append((t0, side, px))
            j = i
            while j < len(d) and abs(d[j][ip] - px) < 1e-9:
                j += 1
            life.append((d[min(j, len(d) - 1)][0] - t0) / 1e6)
            for h in HOR:
                k = bisect.bisect_right(t, t0 + h * 1_000_000) - 1
                if k < j:                                        # the level is still the touch h ms later
                    grow[h].append(d[k][isz])
            i = j
        else:
            i += 1
births.sort()
print("new touch levels (price improved): %d in 69 min (%.0f per minute); a new level stays the touch for: p10 %.0f ms, median %.0f ms, p90 %.0f ms" % (
    len(births), len(births) / 69, q(life, .1), st.median(life), q(life, .9)))
print("size resting on a new level x ms after it appeared (levels that still exist then):")
for h in HOR:
    v = grow[h]
    print("  %4d ms: still the touch %5.1f%% | size BTC p25 %.3f  median %.3f  p75 %.3f" % (h, 100 * len(v) / len(births), q(v, .25), st.median(v), q(v, .75)))

# our hedge orders: how old was the level they joined
new, rep = {}, defaultdict(list)
for r in rows:
    if r[0] == "N" and r[3] == "BTC-USDT" and r[5] is not None:
        new[r[2]] = (r[1], r[4], r[5], r[6])
ages = []
for oid, (t_req, side, px, qty) in sorted(new.items(), key=lambda x: x[1][0]):
    i = bisect.bisect_right(t, t_req) - 1
    ip = 1 if side == "buy" else 3
    j = i
    while j > 0 and abs(d[j - 1][ip] - d[i][ip]) < 1e-9:
        j -= 1
    ages.append((t_req - d[j][0]) / 1e6)
print("our %d hedge orders: age of the touch level when our order was sent: median %.0f ms, p25 %.0f, p75 %.0f, min %.0f" % (
    len(ages), st.median(ages), q(ages, .25), q(ages, .75), min(ages)))
