#!/usr/bin/env python3
"""research3 PX-5 (evaluation): orders at the back of the BTC-USDT touch queue with the frozen PX-3 shield, real queue position.
Pre-registration: docs/research3/px5_join_touch_2026-10-03.md. No free parameter: model ridge_v2 on the 2 ms L3 grid, horizon 1 s,
threshold 0.087 bp (frozen in PX-3), TTL 10 s, cancel also when a better price appears on our side.
usage: Python314/python.exe scripts/research3/px5_eval.py [days=20261001,20261002]"""
import glob, gzip, json, math, os, sys, warnings
import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_cancel as C      # noqa: E402
import l3_mid as LM         # noqa: E402

PX5 = os.path.join(C.ROOT, "data", "research3", "px", "px5")
THETA = 0.08672896772623062
H = "1s"
MS = 1_000_000
ARRIVE_NS = 5 * MS            # the decision to post is taken 5 ms before the order is in the book
TAUS = (5, 25)


def load(day):
    recs = []
    for p in sorted(glob.glob(os.path.join(PX5, "join_%s_??.jsonl.gz" % day))):
        with gzip.open(p, "rt") as fh:
            recs += [json.loads(l) for l in fh]
    # markouts recomputed against the L3 mid (l3_mid.py): the L2-based series used at collection time has holes (audit 2026-10-03)
    LM.fix_markouts(recs, day, lambda r: None if r["f"] is None else r["t"] + r["f"] * 1000)
    return recs


def simulate(recs, pred, tau_ms, shield=True):
    """-> list of (hour, posted, filled, net, (size ahead at arrival, traded through) or None)."""
    T, p = pred["t"], pred[H]
    tau = tau_ms * MS
    out = []
    for r in recs:
        sg, t0 = r["s"], r["t"]
        if shield:
            i = np.searchsorted(T, t0 - ARRIVE_NS - C.SEE_NS, side="right") - 1
            if i < 0 or not (p[i] == p[i]) or sg * p[i] <= -THETA:
                out.append((r["h"], False, False, None, None))             # adverse or unknown prediction: not posted
                continue
        fill = None if r["f"] is None else t0 + r["f"] * 1000
        c = math.inf
        if r["b"] is not None:                                             # somebody posted a better price on our side
            c = t0 + r["b"] * 1000 + C.SEE_NS + tau
        if shield:
            end = fill if fill is not None else t0 + 10_000 * MS
            j0 = np.searchsorted(T, t0 - ARRIVE_NS - C.SEE_NS, side="right")
            j1 = np.searchsorted(T, end - C.SEE_NS, side="right")
            bad = np.nonzero(sg * p[j0:j1] <= -THETA)[0]
            if len(bad):
                c = min(c, T[j0 + bad[0]] + C.SEE_NS + tau)
        filled = fill is not None and fill < c and r["m"][2] == r["m"][2]
        out.append((r["h"], True, filled, (r["m"][2] + C.REBATE) if filled else None, (r["a0"], bool(r.get("thru"))) if filled else None))
    return out


def summary(out, name):
    hours = sorted({o[0] for o in out})
    bh = {h: [] for h in hours}
    for o in out:
        if o[2]:
            bh[o[0]].append(o[3])
    sums = np.array([sum(v) for v in bh.values()])
    n = sum(len(v) for v in bh.values())
    posted = sum(o[1] for o in out)
    mean = sums.sum() / n if n else float("nan")
    t = sums.mean() / (sums.std(ddof=1) / math.sqrt(len(sums))) if len(sums) > 1 and sums.std() > 0 else float("nan")
    print("  %-26s posted %6d  fills/h %7.1f  fill rate %5.1f%%  net/fill %+.3f  t(hour) %+5.2f  hours > 0: %d/%d  median hour %+.1f" % (
        name, posted, n / len(hours), 100 * n / max(posted, 1), mean, t, (sums > 0).sum(), len(hours), np.median(sums)), flush=True)
    return dict(n=n, per_h=n / len(hours), mean=mean, t=t, pos=int((sums > 0).sum()), hours=len(hours))


def by_queue(out):
    """Fills by how the fill happened and by the queue we joined behind (contracts of 0.001 BTC)."""
    f = [(o[4][0], o[4][1], o[3]) for o in out if o[2]]
    if not f:
        return
    a0 = np.array([x[0] for x in f])
    thru = np.array([x[1] for x in f])
    net = np.array([x[2] for x in f])
    parts = ["hit at our price: n %d net %+.2f" % ((~thru).sum(), net[~thru].mean() if (~thru).any() else float("nan")),
             "level traded through: n %d net %+.2f" % (thru.sum(), net[thru].mean() if thru.any() else float("nan"))]
    for lo, hi, nm in ((-1, 100, "joined behind <= 0.1 BTC"), (100, 500, "0.1-0.5 BTC"), (500, 1e12, "> 0.5 BTC")):
        m = (a0 > lo) & (a0 <= hi)
        if m.any():
            parts.append("%s: n %d net %+.2f" % (nm, m.sum(), net[m].mean()))
    print("      " + " | ".join(parts), flush=True)


def main():
    days = (sys.argv[1] if len(sys.argv) > 1 else "20261001,20261002").split(",")
    verdicts = {}
    for day in days:
        print("\n%s" % day, flush=True)
        recs = load(day)
        pred = C.predictions(day, C.CFG["v2"])
        print("  orders %d, filled within 10 s without any cancel %d" % (len(recs), sum(r["f"] is not None for r in recs)), flush=True)
        for tau in TAUS:
            o0 = simulate(recs, pred, tau, shield=False)
            summary(o0, "no shield, tau %d ms" % tau)
            o1 = simulate(recs, pred, tau, shield=True)
            s = summary(o1, "shield, tau %d ms" % tau)
            by_queue(o1)
            if tau == 25:
                verdicts[day] = s["mean"] > 0 and s["t"] >= 2 and s["pos"] / s["hours"] >= 0.6 and s["per_h"] >= 50
        for tau in (0, 2, 10, 50):
            summary(simulate(recs, pred, tau, shield=True), "(sensitivity) tau %d ms" % tau)
        del pred
    print("\nverdict at tau 25 ms (both days must pass): %s -> %s" % (verdicts, "PASSED (provisional)" if verdicts and all(verdicts.values()) else "NOT_PASSED"), flush=True)
    print("PX5_EVAL_DONE", flush=True)


if __name__ == "__main__":
    main()
