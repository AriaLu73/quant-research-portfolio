"""research3 QMM-2: cancel rules for an early order on a new BTC-USDT touch level, evaluated on the traces of qmm_trace.py.
A rule turns what the order can see on its own price level into the moment it asks to be cancelled; the cancel takes effect
TAU ms later (5 = median, 25 = slow end measured live). The order is filled only if its no-cancel fill comes earlier.
Per order: filled -> 10 s markout + OUR_FEE rebate, not filled -> 0. Reported per rule: fills per hour, bp per fill (se),
bp x fills per hour (what an hour is worth for a unit size), share of hours above zero.

Atomic rules (stated before the search; times in ms since our arrival, sizes in contracts of 0.001 BTC):
  T(x)       leave x ms after arrival                                      x in 5, 10, 20, 50, 100, 200, 500, 1000
  DEP(q)     leave when the real size on our level has fallen to q x its largest value so far      q in 0, .25, .5, .75
  BEH(n, y)  from y ms after arrival: leave when at most n contracts stand behind us       n in 0, 5, 20;  y in 0, 2, 5, 10
  TRD(v)     leave when v contracts have traded on our level since we arrived              v in 1, 10, 50
  BET        leave when somebody posts a better price on our side
A combined rule leaves at the earliest of its parts. Search: every single rule, then every combination of one T, one of
(DEP | BEH | none), one of (TRD | none) and (BET | none). The development day picks; the check day is only read for the
rules named in advance by the development day (best single, best combination, and "T(20)" as the plain copy of what the
real first arrivals do: their median resting time is 20 ms).
usage: Python314/python.exe scripts/research3/qmm_rules.py <dev day> [check day] [delay_ms=2]"""
import gzip, itertools, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INF = float("inf")
REBATE = OUR_FEE
TAUS = (5, 25)


def load(day, delay):
    p = os.path.join(ROOT, "data", "research3", "qmm", "trace_%s_d%g.jsonl.gz" % (day, delay))
    return [json.loads(l) for l in gzip.open(p, "rt")]


def atoms(rec):
    """Trigger time (us since arrival) of every atomic rule for one order."""
    tr = rec["tr"]
    a = {}
    for x in (5, 10, 20, 50, 100, 200, 500, 1000):
        a["T%d" % x] = x * 1000.0
    for q in (0.0, 0.25, 0.5, 0.75):
        peak, t = 0.0, INF
        for dt, real, ahead, behind, traded in tr:
            peak = max(peak, real)
            if peak > 0 and real <= q * peak:
                t = dt
                break
        a["DEP%g" % q] = t
    for n in (0, 5, 20):
        for y in (0, 2, 5, 10):
            t, cur = INF, None
            for dt, real, ahead, behind, traded in tr:
                if dt <= y * 1000:
                    cur = behind
                    continue
                if cur is not None and cur <= n and t == INF:
                    t = y * 1000.0                       # already too few behind us when the grace period ends
                    break
                cur = behind
                if behind <= n:
                    t = dt
                    break
            if t == INF and cur is not None and cur <= n and (not tr or tr[-1][0] <= y * 1000):
                t = y * 1000.0
            a["BEH%d_%d" % (n, y)] = t
    for v in (1, 10, 50):
        t = INF
        for dt, real, ahead, behind, traded in tr:
            if traded >= v:
                t = dt
                break
        a["TRD%d" % v] = t
    a["BET"] = INF if rec["b"] is None else float(rec["b"])
    return a


def evaluate(recs, A, parts, tau_ms):
    """-> (fills, mean net bp per fill, se, sum of net bp per hour dict)."""
    tau = tau_ms * 1000.0
    nets, by_hour = [], {}
    for rec, a in zip(recs, A):
        f = rec["f"]
        if f is None:
            continue
        c = min(a[p] for p in parts) if parts else INF
        if f < c + tau:
            m = rec["m"][2]
            if m == m:
                nets.append(m + REBATE)
                by_hour[rec["h"]] = by_hour.get(rec["h"], 0.0) + m + REBATE
    n = len(nets)
    if n < 2:
        return n, float("nan"), float("nan"), by_hour
    mean = sum(nets) / n
    se = math.sqrt(sum((x - mean) ** 2 for x in nets) / (n - 1) / n)
    return n, mean, se, by_hour


def rules():
    T = ["T%d" % x for x in (5, 10, 20, 50, 100, 200, 500, 1000)]
    S2 = [None] + ["DEP%g" % q for q in (0.0, 0.25, 0.5, 0.75)] + ["BEH%d_%d" % (n, y) for n in (0, 5, 20) for y in (0, 2, 5, 10)]
    S3 = [None, "TRD1", "TRD10", "TRD50"]
    S4 = [None, "BET"]
    singles = [(x,) for x in T + S2[1:] + S3[1:] + ["BET"]]
    combos = [tuple(p for p in c if p) for c in itertools.product(T, S2, S3, S4)]
    return singles, [c for c in combos if len(c) > 1]


def show(name, recs, A, parts, hours):
    out = []
    for tau in TAUS:
        n, mean, se, bh = evaluate(recs, A, parts, tau)
        pos = sum(v > 0 for v in bh.values())
        out.append("tau %2d ms: %6.1f fills/h  %+5.2f bp (se %.2f)  %+7.1f bp-fills/h  hours > 0: %d/%d" % (
            tau, n / hours, mean, se, (mean * n / hours) if n else 0.0, pos, hours))
    print("  %-28s %s" % (name, " | ".join(out)))


def main():
    dev = sys.argv[1]
    chk = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    recs = load(dev, delay)
    hours = len({r["h"] for r in recs})
    A = [atoms(r) for r in recs]
    nf = sum(r["f"] is not None for r in recs)
    print("development day %s: %d hours, %d virtual orders (arrival %g ms after the birth), %d would be filled without any cancel" % (dev, hours, len(recs), delay, nf))
    print("no cancel at all (5 s limit):")
    show("-", recs, A, (), hours)
    singles, combos = rules()
    print("single rules:")
    rows = []
    for parts in singles:
        n, mean, se, bh = evaluate(recs, A, parts, 25)
        rows.append((mean * n / hours if n else -1e9, parts))
        show("+".join(parts), recs, A, parts, hours)
    best_single = max(rows)[1]
    rows = []
    for parts in combos:
        n, mean, se, bh = evaluate(recs, A, parts, 25)
        if n / hours >= 50 and n >= 2:
            rows.append((mean * n / hours, mean / se if se > 0 else 0.0, parts))
    rows.sort(reverse=True)
    print("combined rules: %d tried; the ten with the most bp-fills per hour at tau 25 ms (at least 50 fills per hour):" % len(combos))
    for _, _, parts in rows[:10]:
        show("+".join(parts), recs, A, parts, hours)
    best_combo = rows[0][2] if rows else None
    n_pos = sum(r[0] > 0 for r in rows)
    print("combined rules with a positive hour at tau 25 ms: %d of %d that reach 50 fills per hour" % (n_pos, len(rows)))
    named = [("best single", best_single), ("best combination", best_combo), ("T20 (what the first arrivals do)", ("T20",))]
    json.dump({"dev": dev, "named": [(a, list(b) if b else None) for a, b in named]},
              open(os.path.join(ROOT, "data", "research3", "qmm", "rules_named_%s.json" % dev), "w"))
    if chk:
        rc = load(chk, delay)
        hc = len({r["h"] for r in rc})
        Ac = [atoms(r) for r in rc]
        print("\ncheck day %s: %d hours, %d virtual orders - only the rules named by the development day:" % (chk, hc, len(rc)))
        show("no cancel", rc, Ac, (), hc)
        for name, parts in named:
            if parts:
                show(name + " = " + "+".join(parts), rc, Ac, parts, hc)


if __name__ == "__main__":
    main()
