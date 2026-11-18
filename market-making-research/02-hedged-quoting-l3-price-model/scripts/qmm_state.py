"""research3 QMM-2: stay / cancel by the literature's state, on the traces of qmm_trace.py.
Pre-registration: docs/research3/qmm_prereg_2026-10-03.md (written before any result).

State of a resting order (Lehalle & Mounjid 2017 s3.1): Q_before, Q_after, Q_opp.
Grouping (Albers et al. 2025 s5, Table 1): near queue size (Q_before + Q_after) x opposite queue size, each in three quantile
bins (small / medium / large), x queue position QP = Q_before / (Q_before + Q_after) in [0,.1) [.1,.4) [.4,.75) [.75,1];
plus one cell "alone" (nobody else on our level).

A  table of the maker's markout by the state at the fill (orders never cancelled) - the KuCoin copy of Albers' Table 1.
B1 cell rule: stay only in the cells whose development-day net value (10 s markout + OUR_FEE rebate) is > 0 with >= 200 fills.
B2 regression rule: net ~ 1 + ln(1+Q_before) + ln(1+Q_after) + ln(1+Q_opp) fitted on development-day fills; stay while the
   prediction is > 0.
B3 dynamic rule (the main one): Lehalle-Mounjid's stay / cancel control as optimal stopping on the empirical chain of cells -
   a cell can be worth staying in although a fill there loses, because the queue may build behind us first (Albers s7).
All: the first event whose state says "leave" sends the cancel, effective TAU ms later, no re-posting.
The development day fixes the cut points, the stay set and the coefficients; the check day is read with them frozen.
usage: Python314/python.exe scripts/research3/qmm_state.py <dev day> <check day|-> [delay_ms=5]"""
import glob, gzip, json, math, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l3_mid as LM      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REBATE = OUR_FEE
TAUS = (5, 25)
QP_EDGES = (0.1, 0.4, 0.75)
QP_NAMES = ("0-0.1", "0.1-0.4", "0.4-0.75", "0.75-1")
SZ = ("small", "medium", "large")
MIN_N = 200
ALONE = ("alone",)


def load(day, delay):
    ps = sorted(glob.glob(os.path.join(ROOT, "data", "research3", "qmm", "trace_%s_d%g_p*.jsonl.gz" % (day, delay)))) or [
        os.path.join(ROOT, "data", "research3", "qmm", "trace_%s_d%g.jsonl.gz" % (day, delay))]
    out = []
    for p in ps:
        with gzip.open(p, "rt") as fh:
            for l in fh:
                r = json.loads(l)
                if r["tr"] and len(r["tr"][0]) >= 6:
                    out.append(r)
    # markouts recomputed against the L3 mid (l3_mid.py): the L2-based series used at collection time has holes (audit 2026-10-03)
    if str(day).isdigit():
        LM.fix_markouts(out, str(day), lambda r: None if r["f"] is None else r["t"] * 1_000_000 + r["f"] * 1000)
    return out


def state_at(tr, t_us):
    """Last trace row at or before t_us (rows are in time order) -> (Q_before, Q_after, Q_opp)."""
    row = tr[0]
    for x in tr:
        if x[0] > t_us:
            break
        row = x
    return row[2], row[3], row[5]


def fill_state(rec):
    """State just before the fill: the last row strictly before the filling trade (the trade's own row comes after it)."""
    return state_at(rec["tr"], rec["f"])


def cell(qb, qa, qo, cuts):
    near = qb + qa
    if near <= 0:
        return ALONE
    qp = qb / near
    return (int(np.searchsorted(cuts["near"], near, side="right")), int(np.searchsorted(cuts["opp"], qo, side="right")),
            int(np.searchsorted(QP_EDGES, qp, side="right")))


def cell_name(c):
    return "alone on the level" if c == ALONE else "%s near, %s opp, QP %s" % (SZ[c[0]], SZ[c[1]], QP_NAMES[c[2]])


def stats(v):
    v = np.asarray(v, float)
    v = v[~np.isnan(v)]
    n = len(v)
    if n < 2:
        return n, float("nan"), float("nan")
    return n, float(v.mean()), float(v.std(ddof=1) / math.sqrt(n))


def table(recs, cuts, title):
    """Albers Table 1 on our fills. -> {cell: (n, mean 10 s net, se)}"""
    g = {}
    for r in recs:
        if r["f"] is None:
            continue
        g.setdefault(cell(*fill_state(r), cuts), []).append(r["m"])
    print("\n%s" % title)
    print("  %-40s %7s %9s %9s %9s %16s" % ("state at the fill", "fills", "1 s bp", "5 s bp", "10 s bp", "10 s + rebate"))
    res = {}
    keys = sorted((k for k in g if k != ALONE), key=lambda k: (-k[0], k[1], k[2])) + ([ALONE] if ALONE in g else [])
    for k in keys:
        m = np.array(g[k], float)
        n, m10, se = stats(m[:, 2])
        res[k] = (n, m10 + REBATE, se)
        print("  %-40s %7d %+9.3f %+9.3f %+9.3f %+9.3f (se %.3f)" % (cell_name(k), n, np.nanmean(m[:, 0]), np.nanmean(m[:, 1]), m10, m10 + REBATE, se))
    allm = np.array([r["m"] for r in recs if r["f"] is not None], float)
    n, m10, se = stats(allm[:, 2])
    print("  %-40s %7d %+9.3f %+9.3f %+9.3f %+9.3f (se %.3f)" % ("all fills", n, np.nanmean(allm[:, 0]), np.nanmean(allm[:, 1]), m10, m10 + REBATE, se))
    return res


def marginals(recs, cuts):
    """The two monotonicities Albers states: adverse selection falls with the liquidity behind, rises with the opposite queue."""
    rows = [(fill_state(r), r["m"][2]) for r in recs if r["f"] is not None and r["m"][2] == r["m"][2]]
    qa = np.array([s[1] for s, _ in rows])
    qo = np.array([s[2] for s, _ in rows])
    qb = np.array([s[0] for s, _ in rows])
    m = np.array([x for _, x in rows]) + REBATE
    print("\n  10 s net value by quintile of one variable at the fill (lowest -> highest):")
    for name, v in (("liquidity behind (Q_after)", qa), ("opposite queue (Q_opp)", qo), ("liquidity ahead (Q_before)", qb)):
        e = np.quantile(v, [.2, .4, .6, .8])
        b = np.searchsorted(e, v, side="right")
        print("    %-28s " % name + "  ".join("%+.2f (n %d)" % (m[b == i].mean(), (b == i).sum()) if (b == i).any() else "   -   " for i in range(5))
              + "   cut points " + "/".join("%.0f" % x for x in e))


def fit(recs):
    X, y = [], []
    for r in recs:
        if r["f"] is None or r["m"][2] != r["m"][2]:
            continue
        qb, qa, qo = fill_state(r)
        X.append([1.0, math.log1p(qb), math.log1p(qa), math.log1p(qo)])
        y.append(r["m"][2] + REBATE)
    X, y = np.array(X), np.array(y)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    cov = np.linalg.inv(X.T @ X) * (resid @ resid) / (len(y) - 4)
    return beta, np.sqrt(np.diag(cov)), 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))


def cancel_time(rec, stay):
    """Microseconds since arrival of the first trace row whose state says leave (inf when it never does)."""
    for x in rec["tr"]:
        if not stay(x[2], x[3], x[5]):
            return float(x[0])
    return float("inf")


def path(rec, cuts):
    """The order's walk through the cells of the dynamic rule: [(microseconds since arrival, cell + (improved,))], consecutive
    repeats dropped. improved = somebody has posted a better price on our side (we are not the touch any more)."""
    b = rec["b"]
    end = rec["f"] if rec["f"] is not None else float("inf")
    out, prev = [], None
    for x in rec["tr"]:
        if x[0] > end:
            break
        if b is not None and prev is not None and prev[-1] == 0 and b < x[0]:
            c = prev[:-1] + (1,)                              # the better price came between two rows of our own level
            out.append((float(b), c))
            prev = c
        c = cell(x[2], x[3], x[5], cuts) + (1 if (b is not None and x[0] >= b) else 0,)
        if c != prev:
            out.append((float(x[0]), c))
            prev = c
    if b is not None and prev is not None and prev[-1] == 0 and b < end:
        out.append((float(b), prev[:-1] + (1,)))
    return out


def solve(recs, cuts):
    """Lehalle-Mounjid stay / cancel as optimal stopping on the empirical chain of cells:
    V(s) = max(0, [sum_s' N(s->s') V(s') + sum of net fill values out of s] / N(s)); cells visited < MIN_N times count as leave.
    -> (set of cells to stay in, {cell: (visits, continuation value)})"""
    N, T, F = {}, {}, {}
    for r in recs:
        p = [c for _, c in path(r, cuts)]
        for i, c in enumerate(p):
            N[c] = N.get(c, 0) + 1
            if i + 1 < len(p):
                T.setdefault(c, {})
                T[c][p[i + 1]] = T[c].get(p[i + 1], 0) + 1
        if r["f"] is not None and p and r["m"][2] == r["m"][2]:
            F[p[-1]] = F.get(p[-1], 0.0) + r["m"][2] + REBATE
    V = {c: 0.0 for c in N}
    cont = {}
    for _ in range(10000):
        worst = 0.0
        for c in N:
            q = (sum(n * V[s2] for s2, n in T.get(c, {}).items()) + F.get(c, 0.0)) / N[c] if N[c] >= MIN_N else -1.0
            cont[c] = q
            v = max(q, 0.0)
            worst = max(worst, abs(v - V[c]))
            V[c] = v
        if worst < 1e-9:
            break
    return {c for c in N if cont[c] > 0}, {c: (N[c], cont[c]) for c in N}


def cancel_time_path(rec, cuts, S):
    for t, c in path(rec, cuts):
        if c not in S:
            return t
    return float("inf")


def evaluate(recs, stay, hours, name, C=None):
    C = C if C is not None else [cancel_time(r, stay) for r in recs]
    posted = sum(c > 0 for c in C)
    out = {}
    for tau in TAUS:
        nets, bh = [], {}
        for r, c in zip(recs, C):
            f = r["f"]
            if f is None or f >= c + tau * 1000.0:
                continue
            m = r["m"][2]
            if m == m:
                nets.append(m + REBATE)
                bh[r["h"]] = bh.get(r["h"], 0.0) + m + REBATE
        n, mean, se = stats(nets)
        pos = sum(v > 0 for v in bh.values())
        out[tau] = (n, mean, se, pos)
        print("  %-22s tau %2d ms: %6.1f fills/h  net %+6.3f bp (se %.3f, t %+5.2f)  hours > 0: %d/%d  | still resting after the first event: %d of %d orders" % (
            name, tau, n / hours, mean, se, mean / se if se and se == se else float("nan"), pos, hours, posted, len(recs)))
    return out


def verdict(res, hours):
    n, mean, se, pos = res[25]
    ok1 = n >= 2 and mean > 0 and mean / se >= 2
    ok2 = n / hours >= 50
    ok3 = pos / hours >= 0.6
    return "PASSED" if ok1 and ok2 and ok3 else "NOT_PASSED (net>0 & t>=2: %s, >=50 fills/h: %s, >=60%% hours positive: %s)" % (ok1, ok2, ok3)


def main():
    dev = sys.argv[1]
    chk = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
    recs = load(dev, delay)
    hours = len({r["h"] for r in recs})
    fs = [fill_state(r) for r in recs if r["f"] is not None]
    near = np.array([a + b for a, b, _ in fs])
    cuts = {"near": [float(x) for x in np.quantile(near[near > 0], [1 / 3, 2 / 3])], "opp": [float(x) for x in np.quantile([c for _, _, c in fs], [1 / 3, 2 / 3])]}
    print("development day %s, arrival %g ms after the birth of the level: %d hours, %d virtual orders, %d filled without any cancel" % (dev, delay, hours, len(recs), len(fs)))
    print("queue size cut points (contracts of 0.001 BTC, terciles at the fill): near %.0f / %.0f, opposite %.0f / %.0f" % (*cuts["near"], *cuts["opp"]))
    res = table(recs, cuts, "A. markout of the maker by the state at the fill, no cancel (Albers et al. 2025, Table 1, on KuCoin BTC-USDT)")
    marginals(recs, cuts)
    S = sorted((k for k, (n, net, se) in res.items() if n >= MIN_N and net > 0), key=str)
    print("\nB1 stay set (development day: net > 0 and >= %d fills): %s" % (MIN_N, "; ".join(cell_name(k) for k in S) if S else "EMPTY"))
    beta, bse, r2 = fit(recs)
    print("B2 regression of the 10 s net value at the fill: const %+.3f (se %.3f)  ln(1+Q_before) %+.3f (%.3f)  ln(1+Q_after) %+.3f (%.3f)  ln(1+Q_opp) %+.3f (%.3f)   R2 %.4f" % (
        beta[0], bse[0], beta[1], bse[1], beta[2], bse[2], beta[3], bse[3], r2))
    Sset = set(S)
    stay1 = lambda qb, qa, qo: cell(qb, qa, qo, cuts) in Sset
    stay2 = lambda qb, qa, qo: beta[0] + beta[1] * math.log1p(qb) + beta[2] * math.log1p(qa) + beta[3] * math.log1p(qo) > 0
    S3, info = solve(recs, cuts)
    print("B3 optimal stopping on the empirical chain of cells (Lehalle-Mounjid): %d cells seen, stay in %d. Continuation value, bp per visit:" % (len(info), len(S3)))
    for c in sorted(info, key=lambda c: -info[c][1]):
        if info[c][0] >= MIN_N:
            print("    %-40s %-12s visits %7d  value %+.4f  %s" % (cell_name(c[:-1]), "not the touch" if c[-1] else "at the touch", info[c][0], info[c][1], "STAY" if c in S3 else "leave"))
    print("\ndevelopment day (in sample):")
    evaluate(recs, lambda *a: True, hours, "no cancel")
    evaluate(recs, stay1, hours, "B1 cell rule")
    evaluate(recs, stay2, hours, "B2 regression rule")
    evaluate(recs, None, hours, "B3 dynamic rule", [cancel_time_path(r, cuts, S3) for r in recs])
    json.dump({"dev": dev, "delay_ms": delay, "cuts": cuts, "stay": [list(k) for k in S], "beta": [float(b) for b in beta], "stay_dynamic": [list(k) for k in sorted(S3, key=str)]},
              open(os.path.join(ROOT, "data", "research3", "qmm", "state_rule_%s_d%g.json" % (dev, delay)), "w"), indent=1)
    if chk:
        rc = load(chk, delay)
        hc = len({r["h"] for r in rc})
        print("\ncheck day %s: %d hours, %d virtual orders, %d filled without any cancel - cut points, stay set and coefficients frozen" % (
            chk, hc, len(rc), sum(r["f"] is not None for r in rc)))
        table(rc, cuts, "A (check day).")
        marginals(rc, cuts)
        print()
        evaluate(rc, lambda *a: True, hc, "no cancel")
        r1 = evaluate(rc, stay1, hc, "B1 cell rule")
        r2_ = evaluate(rc, stay2, hc, "B2 regression rule")
        r3 = evaluate(rc, None, hc, "B3 dynamic rule", [cancel_time_path(r, cuts, S3) for r in rc])
        print("\nverdict at tau 25 ms:  B1 %s\n                       B2 %s\n                       B3 %s" % (verdict(r1, hc), verdict(r2_, hc), verdict(r3, hc)))


if __name__ == "__main__":
    main()
