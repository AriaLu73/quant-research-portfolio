#!/usr/bin/env python3
"""research3 PX-6 (audit fix): the same orders and the same frozen shield as PX-3 / PX-5, but evaluated as a STRATEGY that has
at most one live order per side, instead of as a population of overlapping orders.

Why (audit 2026-10-03): the earlier evaluations placed a new virtual order every second (PX-5, 10 s life) or at every new touch
level (QMM / PX-2 / PX-3, 5 s life) and averaged over all of them. Orders on the same side overlap in time, and one small taker
order fills every live virtual order above its price at once - no KuCoin taker order in our recording trades at more than one
price - so one adverse move was counted up to ten times and the per-fill average was dominated by bursts. A strategy with one
order per side is filled at most once by that move.
Rule here: per side, walk through the candidate orders in time; take a candidate only if our previous order on that side has
ended (filled, cancel effective, or expired). Everything else is unchanged (model ridge_v2 on the 2 ms L3 grid, horizon 1 s,
threshold 0.087 bp, see 1.5 ms, markout 10 s against the L3 mid + OUR_FEE).
usage: Python314/python.exe scripts/research3/px6_single.py [days=20261001,20261002]"""
import math, os, sys, warnings
import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_cancel as C      # noqa: E402
import px5_eval as E       # noqa: E402
import l3_mid as LM        # noqa: E402

MS = 1_000_000
THETA, H = E.THETA, "1s"


def plan(cands, pred, tau_ms, shield, life_ns, arrive_ns):
    """cands: (hour, side, t0 ns, fill ns or None, net or None, better-price ns or None), any order.
    -> per candidate (hour, side, t0, posted, end ns, filled, net) under the cancel rule, each evaluated on its own."""
    T, p = pred["t"], pred[H]
    tau = tau_ms * MS
    out = []
    for hr, sg, t0, fill, net, better in cands:
        if shield:
            i = np.searchsorted(T, t0 - arrive_ns - C.SEE_NS, side="right") - 1
            if i < 0 or not (p[i] == p[i]) or sg * p[i] <= -THETA:
                out.append((hr, sg, t0, False, t0, False, None))
                continue
        c = t0 + life_ns
        if better is not None:
            c = min(c, better + C.SEE_NS + tau)
        if shield:
            end = fill if fill is not None else t0 + life_ns
            j0 = np.searchsorted(T, t0 - arrive_ns - C.SEE_NS, side="right")
            j1 = np.searchsorted(T, end - C.SEE_NS, side="right")
            bad = np.nonzero(sg * p[j0:j1] <= -THETA)[0]
            if len(bad):
                c = min(c, T[j0 + bad[0]] + C.SEE_NS + tau)
        filled = fill is not None and fill < c and net is not None
        out.append((hr, sg, t0, True, fill if filled else c, filled, net if filled else None))
    return out


def single(plans, arrive_ns):
    """Keep, per side, only candidates that start after our previous order on that side has ended (+ the time to get a new
    order into the book)."""
    keep = []
    for sg in (1, -1):
        free = -1
        for o in sorted((o for o in plans if o[1] == sg), key=lambda o: o[2]):
            if o[2] < free:
                continue
            keep.append(o)
            if o[3]:
                free = o[4] + arrive_ns
    return keep


def report(name, orders):
    hours = sorted({o[0] for o in orders})
    sums = {h: 0.0 for h in hours}
    n = 0
    nets = []
    for o in orders:
        if o[5]:
            sums[o[0]] += o[6]
            nets.append(o[6])
            n += 1
    s = np.array(list(sums.values()))
    posted = sum(o[3] for o in orders)
    t = s.mean() / (s.std(ddof=1) / math.sqrt(len(s))) if len(s) > 1 and s.std() > 0 else float("nan")
    nets = np.array(nets)
    print("  %-34s posted %6d  fills/h %7.1f  net/fill %+.3f (sd %.2f)  t(hour) %+5.2f  hours > 0: %2d/%d  median hour %+7.1f" % (
        name, posted, n / len(hours), nets.mean() if n else float("nan"), nets.std() if n else float("nan"), t, (s > 0).sum(), len(hours), np.median(s)), flush=True)


def main():
    days = (sys.argv[1] if len(sys.argv) > 1 else "20261001,20261002").split(",")
    for day in days:
        print("\n%s" % day, flush=True)
        pred = C.predictions(day, C.CFG["v2"])
        # population 1: orders joining the back of the touch queue every second (PX-5), 10 s life
        j = E.load(day)
        cj = [(r["h"], r["s"], r["t"], None if r["f"] is None else r["t"] + r["f"] * 1000,
               (r["m"][2] + C.REBATE) if r["f"] is not None and r["m"][2] == r["m"][2] else None,
               None if r["b"] is None else r["t"] + r["b"] * 1000) for r in j]
        # population 2: orders posted 5 ms after the birth of a new touch level (QMM), 5 s life
        q = C.load_traces(day)
        cq = [(hr, sg, t0, fill, net, None) for hr, sg, t0, fill, net in q]
        for nm, cands, life in (("join the back of the touch", cj, 10_000 * MS), ("new level, 5 ms after its birth", cq, 5_000 * MS)):
            print(" %s (%d candidates)" % (nm, len(cands)), flush=True)
            for shield in (False, True):
                for tau in ((25,) if not shield else (5, 25)):
                    pl = plan(cands, pred, tau, shield, life, E.ARRIVE_NS)
                    tag = ("shield" if shield else "no shield") + ", tau %d ms" % tau
                    report("all overlapping orders, " + tag, pl)
                    report("ONE order per side,     " + tag, single(pl, E.ARRIVE_NS))
        del pred
    print("PX6_DONE", flush=True)


if __name__ == "__main__":
    main()
