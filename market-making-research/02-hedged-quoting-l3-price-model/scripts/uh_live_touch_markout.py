"""research3: is the BTC-USDC flow that trades at the public touch worth making? (live recording 2026-10-02, 16:17-17:27 UTC)

Stated before computing (H-T1):
  universe  public BTC-USDC prints at or through the public touch that prevailed just before the print (our own resting orders
            removed from the book), our own fills excluded. Prints strictly inside the spread are counted separately
            (paired prints: not flow a resting quote can take).
  fair      F(t) = USDT mid(t) x (1 + b), b = median over the previous 60 s of (public USDC mid / USDT mid - 1), 1 s samples
            (the strategy's own fair value), b frozen at the print.
  edge      e(h) = g x (F(t + h) - px) / px in bp, g = +1 when the maker bought (taker sold). e(0) is the spread captured
            against fair, e(h) what is left after the reference has moved for h seconds.
  net       taker hedge at once:      e(0.05 s) + 1.2 (USDC rebate) - 1.8 (USDT taker fee) - USDT half spread
            passive hedge by 5 s:     e(5 s)    + 1.2 + 0.7 (USDT rebate)                [optimistic: filled at mid]
  verdict   touch quoting is worth building only if the size-weighted mean net with the passive hedge is above 0 by more
            than twice its standard error; if even that optimistic figure is not, the touch flow does not pay at our fees.
  also      the same two nets for prints that reach at least d bp beyond fair, d = 0.5 ... 3 (where a deeper quote would fill).
One evening, one regime: an indication, not a validation.
usage: uh_live_touch_markout.py <extract.jsonl.gz>"""
import bisect, gzip, json, math, statistics as st, sys
from collections import defaultdict

rows = [json.loads(l) for l in gzip.open(sys.argv[1], "rt", encoding="utf-8")]
QS, HS = "BTC-USDC", "BTC-USDT"
REB_Q, REB_H, FEE_H = OUR_FEE, 0.7, 1.8

# our resting quotes (to remove them from the book) and our fills (to exclude)
new, rep = {}, defaultdict(list)
for r in rows:
    if r[0] == "N" and r[3] == QS:
        new[r[2]] = {"side": r[4], "px": r[5], "qty": r[6]}
    elif r[0] == "R":
        rep[r[3]].append((r[1], r[2], r[5]))
ev = []
for oid, o in new.items():
    push = [x for x in rep.get(oid, []) if abs(x[0] - x[1]) >= 200_000 and x[1] > 10 ** 18]
    opens = [x[0] for x in push if x[2] in ("submitted", "partially_filled")]       # publish time: same clock as the book rows
    ends = [x[0] for x in push if x[2] in ("cancelled", "filled")]
    if opens or ends:
        ev.append((min(opens) if opens else min(ends), 1, oid))
        if ends:
            ev.append((min(ends), -1, oid))
ev.sort()
own_fill_keys = {(round(r[6], 1), round(r[7], 6)) for r in rows if r[0] == "F" and r[4] == QS}

# reference mid over time
dh = [(r[1], (r[4][0][0] + r[5][0][0]) / 2, (r[5][0][0] - r[4][0][0]) / 2) for r in rows if r[0] == "D" and r[3] == HS]
th = [x[0] for x in dh]


def href(t):
    i = bisect.bisect_right(th, t) - 1
    return dh[i] if i >= 0 else None


def public_touch(levels, own):
    for px, sz in levels:
        if sz - own.get(px, 0.0) > 1e-9:
            return px
    return None


live, j = {}, 0
book = None
basis_hist, last_obs = [], 0
prints = []          # (t, g, px, usd, b, kind)
t_first = None
for r in rows:
    t = r[1]
    while j < len(ev) and ev[j][0] <= t:
        if ev[j][1] > 0:
            live[ev[j][2]] = new[ev[j][2]]
        else:
            live.pop(ev[j][2], None)
        j += 1
    if r[0] == "D" and r[3] == QS:
        own_b, own_a = defaultdict(float), defaultdict(float)
        for o in live.values():
            (own_b if o["side"] == "buy" else own_a)[o["px"]] += o["qty"]
        pb, pa = public_touch(r[4], own_b), public_touch(r[5], own_a)
        if pb is not None and pa is not None and pa > pb:
            book = (pb, pa)
            h = href(t)
            if h and t - last_obs >= 1_000_000_000:
                last_obs = t
                basis_hist.append((t, (pb + pa) / 2 / h[1] - 1))
                while basis_hist and basis_hist[0][0] < t - 60_000_000_000:
                    basis_hist.pop(0)
    elif r[0] == "D" and r[3] == HS:
        if book is not None and t - last_obs >= 1_000_000_000:        # quiet USDC book: observe on the reference clock
            last_obs = t
            basis_hist.append((t, (book[0] + book[1]) / 2 / ((r[4][0][0] + r[5][0][0]) / 2) - 1))
            while basis_hist and basis_hist[0][0] < t - 60_000_000_000:
                basis_hist.pop(0)
    elif r[0] == "T" and r[3] == QS:
        if book is None or len(basis_hist) < 30:
            continue
        if t_first is None:
            t_first = t
        side, px, sz = r[4], r[5], r[6]
        if (round(px, 1), round(sz, 6)) in own_fill_keys:
            continue
        b = st.median(x[1] for x in basis_hist)
        pb, pa = book
        if side == "sell":
            kind = "touch" if px <= pb + 1e-9 else ("inside" if px < pa - 1e-9 else "other")
        else:
            kind = "touch" if px >= pa - 1e-9 else ("inside" if px > pb + 1e-9 else "other")
        prints.append((t, 1 if side == "sell" else -1, px, px * sz, b, kind))

t_last = prints[-1][0]
mins = (t_last - t_first) / 6e10
cnt = defaultdict(lambda: [0, 0.0])
for p in prints:
    cnt[p[5]][0] += 1; cnt[p[5]][1] += p[3]
print("window %.1f min; prints: " % mins + "; ".join("%s %d ($%.0f)" % (k, v[0], v[1]) for k, v in cnt.items()))


def edge(p, h):
    t, g, px, usd, b, _ = p
    x = href(t + int(h * 1e9))
    return g * (x[1] * (1 + b) - px) / px * 1e4, x[2] / x[1] * 1e4


def wstat(vals, w):
    sw = sum(w)
    m = sum(v * x for v, x in zip(vals, w)) / sw
    var = sum(x * (v - m) ** 2 for v, x in zip(vals, w)) / sw
    neff = sw ** 2 / sum(x * x for x in w)
    return m, math.sqrt(var / max(neff - 1, 1)), neff


def report(name, ps):
    if len(ps) < 5:
        print("%-34s n=%d (too few)" % (name, len(ps))); return
    w = [p[3] for p in ps]
    e = {h: [edge(p, h)[0] for p in ps] for h in (0.0, 0.05, 1, 5, 30)}
    hs = [edge(p, 0.05)[1] for p in ps]
    taker = [a + REB_Q - FEE_H - s for a, s in zip(e[0.05], hs)]
    passive = [a + REB_Q + REB_H for a in e[5]]
    mt, st_, _ = wstat(taker, w)
    mp, sp, neff = wstat(passive, w)
    print("%-34s n=%-5d $%-8.0f per hour %5.0f prints $%-7.0f | edge vs fair bp at 0 / 1 s / 5 s / 30 s: %+5.2f %+5.2f %+5.2f %+5.2f | net taker-hedged %+5.2f (se %.2f) | net passive-hedged %+5.2f (se %.2f, n_eff %.0f)" % (
        name, len(ps), sum(w), len(ps) / mins * 60, sum(w) / mins * 60,
        wstat(e[0.0], w)[0], wstat(e[1], w)[0], wstat(e[5], w)[0], wstat(e[30], w)[0], mt, st_, mp, sp, neff))


touch = [p for p in prints if p[5] == "touch"]
report("at / through the public touch", touch)
report("  maker bought (taker sold)", [p for p in touch if p[1] > 0])
report("  maker sold (taker bought)", [p for p in touch if p[1] < 0])
report("inside the spread (paired prints)", [p for p in prints if p[5] == "inside"])
print("prints by depth beyond fair value (a quote resting d bp from fair is filled by these):")
for d in (0.25, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
    report("  depth >= %.2f bp" % d, [p for p in touch if edge(p, 0.0)[0] >= d])
dep = sorted(edge(p, 0.0)[0] for p in touch)
print("depth of touch prints beyond fair bp: p10 %.2f  median %.2f  p90 %.2f  mean of the positive ones %.2f" % (
    dep[int(.1 * len(dep))], st.median(dep), dep[int(.9 * len(dep))], st.mean(x for x in dep if x > 0)))
