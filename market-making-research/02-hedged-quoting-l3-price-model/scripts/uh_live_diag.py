"""Diagnosis of a live MM-UH run from the WAL extract (scripts on the server: wal_extract.py).
Questions: where did our quotes rest relative to the public BTC-USDC touch; which public trades could have filled us;
what happened after each fill; how the hedge behaved.
usage: uh_live_diag.py <extract.jsonl.gz>"""
import bisect, gzip, json, statistics as st, sys
from collections import defaultdict

rows = [json.loads(l) for l in gzip.open(sys.argv[1], "rt", encoding="utf-8")]
QS, HS = "BTC-USDC", "BTC-USDT"

# ---------------------------------------------------------------- our orders: life on the exchange
new, rep, fills, creq = {}, defaultdict(list), [], {}
for r in rows:
    k = r[0]
    if k == "N":
        new[r[2]] = {"t_req": r[1], "sym": r[3], "side": r[4], "px": r[5], "qty": r[6], "type": r[7], "tif": r[8]}
    elif k == "R":
        rep[r[3]].append((r[1], r[2], r[5], r[6], r[7]))          # pub, ts, status, filled, msg
    elif k == "F":
        fills.append({"pub": r[1], "ts": r[2], "oid": r[3], "sym": r[4], "side": r[5], "px": r[6], "qty": r[7], "maker": r[8], "fee": r[9]})
    elif k == "C":
        creq.setdefault(r[2], r[1])
orders = []
for oid, o in new.items():
    rs = rep.get(oid, [])
    push = [x for x in rs if abs(x[0] - x[1]) >= 200_000 and x[1] > 10 ** 18]   # reports built from exchange pushes carry exchange time
    opens = [x[1] for x in push if x[2] in ("submitted", "partially_filled")]
    ends = [x[1] for x in push if x[2] in ("cancelled", "filled")]
    if not opens and not ends:
        continue
    o.update(oid=oid, t_open=min(opens) if opens else min(ends), t_end=min(ends) if ends else None,
             end=next((x[2] for x in sorted(push, key=lambda x: x[1]) if x[2] in ("cancelled", "filled")), None),
             filled=max((x[3] for x in rs), default=0.0), t_cancel_req=creq.get(oid))
    orders.append(o)
quotes = [o for o in orders if o["sym"] == QS]
hedges = [o for o in orders if o["sym"] == HS]
t0 = min(o["t_open"] for o in quotes)
t1 = max(o["t_end"] or o["t_open"] for o in quotes)
print("run: %.1f min, quote orders %d, hedge orders %d, fills %d" % ((t1 - t0) / 6e10, len(quotes), len(hedges), len(fills)))

# ---------------------------------------------------------------- market state
dq = [(r[1], r[4], r[5]) for r in rows if r[0] == "D" and r[3] == QS]             # pub_ns, bids, asks (5 levels)
dh = [(r[1], r[4][0][0], r[5][0][0]) for r in rows if r[0] == "D" and r[3] == HS]
tq = [x[0] for x in dq]
th = [x[0] for x in dh]
trades = [(r[2], r[4], r[5], r[6]) for r in rows if r[0] == "T" and r[3] == QS and t0 <= r[2] <= t1]


def book_at(t):
    i = bisect.bisect_right(tq, t) - 1
    return dq[i] if i >= 0 else None


def hmid_at(t):
    i = bisect.bisect_right(th, t) - 1
    return (dh[i][1] + dh[i][2]) / 2 if i >= 0 else None


def qmid_at(t):
    b = book_at(t)
    return (b[1][0][0] + b[2][0][0]) / 2 if b else None


# our resting quotes at time t: list of (side, px, qty_left)
ev = []
for o in quotes:
    ev.append((o["t_open"], 1, o))
    if o["t_end"] is not None:
        ev.append((o["t_end"], -1, o))
ev.sort(key=lambda x: (x[0], x[1]))
ev_t = [e[0] for e in ev]


def resting_at(t):
    live = {}
    for tt, sgn, o in ev[: bisect.bisect_right(ev_t, t)]:
        if sgn > 0:
            live[o["oid"]] = o
        else:
            live.pop(o["oid"], None)
    return list(live.values())


# faster: sweep once over sample times
def sweep(times):
    out, live, j = [], {}, 0
    for t in times:
        while j < len(ev) and ev[j][0] <= t:
            _, sgn, o = ev[j]
            if sgn > 0:
                live[o["oid"]] = o
            else:
                live.pop(o["oid"], None)
            j += 1
        out.append(list(live.values()))
    return out


def public_touch(levels, own):
    for px, sz in levels:
        if sz - own.get(px, 0.0) > 1e-9:
            return px
    return None


# ---------------------------------------------------------------- A. where our near quotes rested (sampled every 100 ms)
times = list(range(t0 + 90_000_000_000, t1, 100_000_000))
rest = sweep(times)
dist = {"buy": [], "sell": []}
state = {"buy": defaultdict(int), "sell": defaultdict(int)}
pub_spread, our_spread, n_no_quote = [], [], 0
for t, live in zip(times, rest):
    b = book_at(t)
    if b is None:
        continue
    own_b = defaultdict(float); own_a = defaultdict(float)
    for o in live:
        (own_b if o["side"] == "buy" else own_a)[o["px"]] += o["qty"]
    pb, pa = public_touch(b[1], own_b), public_touch(b[2], own_a)
    if pb is None or pa is None:
        continue
    mid = (pb + pa) / 2
    pub_spread.append((pa - pb) / mid * 1e4)
    nb = max((o["px"] for o in live if o["side"] == "buy"), default=None)
    na = min((o["px"] for o in live if o["side"] == "sell"), default=None)
    if nb is None and na is None:
        n_no_quote += 1
    if nb is not None and na is not None:
        our_spread.append((na - nb) / mid * 1e4)
    for side, ours, pub, sign in (("buy", nb, pb, 1), ("sell", na, pa, -1)):
        if ours is None:
            state[side]["no quote"] += 1
            continue
        d = sign * (pub - ours) / mid * 1e4               # > 0: we rest behind the public touch; < 0: we improve it
        dist[side].append(d)
        state[side]["improving the touch" if d < -1e-9 else "joined at the touch" if abs(d) <= 1e-9 else "behind the touch"] += 1


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))]


print("\nA. near quote versus the public touch (100 ms samples, own orders removed from the book)")
print("   public spread bp: p10 %.2f  median %.2f  p90 %.2f | our near bid-ask spread bp: p10 %.2f  median %.2f  p90 %.2f" % (
    q(pub_spread, .1), st.median(pub_spread), q(pub_spread, .9), q(our_spread, .1), st.median(our_spread), q(our_spread, .9)))
for side in ("buy", "sell"):
    n = sum(state[side].values())
    print("   %-4s " % side + "  ".join("%s %.1f%%" % (k, 100 * v / n) for k, v in sorted(state[side].items(), key=lambda x: -x[1])))
    v = dist[side]
    print("        distance behind the touch bp: p10 %.2f  p25 %.2f  median %.2f  p75 %.2f  p90 %.2f" % (q(v, .1), q(v, .25), st.median(v), q(v, .75), q(v, .9)))

# ---------------------------------------------------------------- B. public trades versus our quotes
print("\nB. public BTC-USDC trades during the run: %d, notional $%.0f" % (len(trades), sum(p * s for _, _, p, s in trades)))
tt = [x[0] for x in trades]
rest_tr = sweep(tt) if tt == sorted(tt) else [resting_at(t) for t in tt]
own_tids = {(f["px"], round(f["qty"], 6)) for f in fills if f["sym"] == QS}
cat = defaultdict(lambda: [0, 0.0])
sizes = []
for (t, side, px, sz), live in zip(trades, rest_tr):
    sizes.append(px * sz)
    # a taker SELL hits bids; a taker BUY lifts asks
    ours = [o["px"] for o in live if o["side"] == ("buy" if side == "sell" else "sell")]
    if not ours:
        k = "no quote of ours on that side"
    else:
        best = max(ours) if side == "sell" else min(ours)
        better = px > best if side == "sell" else px < best        # trade happened at a better price than our quote
        if better:
            k = "at a better price than our quote (we were behind)"
        elif px == best:
            k = "at our price"
        else:
            k = "through our price"
    cat[k][0] += 1; cat[k][1] += px * sz
for k, (n, usd) in sorted(cat.items(), key=lambda x: -x[1][0]):
    print("   %-52s %5d trades  $%9.0f" % (k, n, usd))
print("   trade size $: median %.0f  p90 %.0f  max %.0f" % (st.median(sizes), q(sizes, .9), max(sizes)))
by_min = defaultdict(int)
for t, *_ in trades:
    by_min[(t - t0) // 60_000_000_000] += 1
v = [by_min.get(m, 0) for m in range(int((t1 - t0) // 60_000_000_000))]
print("   trades per minute: median %d  mean %.1f  minutes with none: %d of %d" % (st.median(v), st.mean(v), sum(x == 0 for x in v), len(v)))

# ---------------------------------------------------------------- C. our fills and what followed
print("\nC. fills")
for f in sorted(fills, key=lambda x: x["ts"]):
    t = f["ts"]
    o = new.get(f["oid"], {})
    sign = 1 if f["side"] == "buy" else -1
    ref = hmid_at if f["sym"] == QS else hmid_at
    m0 = hmid_at(t)
    mo = {h: sign * (hmid_at(t + int(h * 1e9)) / m0 - 1) * 1e4 for h in (1, 5, 30, 60)} if m0 else {}
    pre = {h: sign * (m0 / hmid_at(t - int(h * 1e9)) - 1) * 1e4 for h in (0.05, 0.5, 5)} if m0 else {}
    cr = creq.get(f["oid"])
    print("   %+7.1f min %s %-4s %.4f @ %.1f %s | USDT mid move before (50ms / 0.5s / 5s): %s bp | after, in our favour (1s / 5s / 30s / 60s): %s bp | cancel sent %s" % (
        (t - t0) / 6e10, f["sym"], f["side"], f["qty"], f["px"], "maker" if f["maker"] else "taker",
        " / ".join("%+.1f" % pre[h] for h in (0.05, 0.5, 5)), " / ".join("%+.1f" % mo[h] for h in (1, 5, 30, 60)),
        "%.0f ms before the fill" % ((t - cr) / 1e6) if cr else "no"))

# ---------------------------------------------------------------- D. hedge orders
print("\nD. hedge orders (BTC-USDT): %d, filled %d" % (len(hedges), sum(o["filled"] > 0 for o in hedges)))
life = [(o["t_end"] - o["t_open"]) / 1e9 for o in hedges if o["t_end"]]
if life:
    print("   resting time s: median %.2f  p90 %.2f  max %.2f" % (st.median(life), q(life, .9), max(life)))
qf = [f for f in fills if f["sym"] == QS]
for f in qf:
    later = [h for h in fills if h["sym"] == HS and h["ts"] > f["ts"]]
    if later:
        h = min(later, key=lambda x: x["ts"])
        m0 = hmid_at(f["ts"])
        sign = 1 if h["side"] == "buy" else -1
        print("   quote fill at %+.1f min -> hedge filled %.1f s later at %.1f; USDT mid at the quote fill %.1f -> hedge price worse by %.1f bp" % (
            (f["ts"] - t0) / 6e10, (h["ts"] - f["ts"]) / 1e9, h["px"], m0, sign * (h["px"] / m0 - 1) * 1e4))

# ---------------------------------------------------------------- E. quote lifetime and cancel reasons seen from outside
lifeq = [(o["t_end"] - o["t_open"]) / 1e9 for o in quotes if o["t_end"]]
print("\nE. quote orders: lifetime s median %.2f  p10 %.2f  p90 %.2f | per hour %.0f" % (st.median(lifeq), q(lifeq, .1), q(lifeq, .9), len(quotes) / ((t1 - t0) / 3.6e12)))
# time with all four quotes resting / none
cnt = defaultdict(int)
for live in rest:
    cnt[len(live)] += 1
n = sum(cnt.values())
print("   number of our quotes resting (share of time): " + "  ".join("%d: %.1f%%" % (k, 100 * v / n) for k, v in sorted(cnt.items())))
