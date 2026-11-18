#!/usr/bin/env python3
"""research3 PX-4: static versus normalised / adaptive cancel signal, compared on 480 hours of September BTC-USDT L2.
Pre-registration: docs/research3/px4_adaptive_2026-10-03.md (written before any PX-4 result).
  S  fixed coefficients (ridge_v2.json, target = bp return over 1 s), cancel threshold fixed at 0.087 bp        (PX-3 frozen rule)
  N  same model, threshold = median of |prediction| over the past 5 minutes
  Z  fixed coefficients fitted on return / current volatility (training days), threshold = 5-minute median of |prediction|
  R  as Z, coefficients re-estimated every hour on the previous 24 hours (rolling ridge)
Fill proxy (queue front, an upper bound): a real taker order that trades at the displayed best counts as one maker fill there,
if we are "present": the prediction seen at t - 1.5 ms - tau is not adverse beyond the threshold. Net = 10 s markout + OUR_FEE.
usage: Python314/python.exe scripts/research3/px4_proxy.py stats i/n      (per-hour sufficient statistics, z target)
       Python314/python.exe scripts/research3/px4_proxy.py eval i/n       (needs all stats)
       Python314/python.exe scripts/research3/px4_proxy.py report"""
import glob, gzip, json, math, os, sys, warnings
import numpy as np, pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_ic as P      # noqa: E402

ROOT = P.ROOT
SYM, SRC = "BTC-USDT", "BTC-USDT-10ms"
GRID = os.path.join(P.PX, SRC)
OUT = os.path.join(P.PX, "px4")
TICKS = os.path.join(ROOT, "data", "oos", "ku_buyc")
REBATE, SEE_NS, TAUS = 0.7, 1_500_000, (5, 25)
THETA_S = 0.08672896772623062            # PX-3 frozen threshold, bp
LAM = 1e4
ROLL_HOURS = 24
MED_STEPS, MED_MIN = 30000, 3000         # 5 minutes of 10 ms steps
TICK = 0.1
R2 = json.load(open(os.path.join(P.PX, SYM, "ridge_v2.json")))
MU, SD = np.array(R2["mu"]), np.array(R2["sd"])
FEATS = R2["feats"]


def slots():
    return sorted(os.path.basename(f)[5:-8] for f in glob.glob(os.path.join(GRID, "grid_*.parquet")))


def frame(slot):
    day, hh = slot.split("_")
    X = P.day_frame(SYM, day, src=SRC, step_ms=10, min_files=1, hours=(hh,), v2=True)
    Z = X[FEATS].to_numpy()
    D = np.c_[np.ones(len(Z)), np.clip((Z - MU) / SD, -10, 10)]
    ok = X.ok.to_numpy() & np.isfinite(Z).all(1)
    return X, D, ok


def do_stats(slot):
    out = os.path.join(OUT, "stats_%s.npz" % slot)
    if os.path.exists(out):
        return
    X, D, ok = frame(slot)
    y = X["y_1s"].to_numpy() / X.vol.to_numpy()
    m = ok & np.isfinite(y)
    np.savez(out + ".tmp.npz", xtx=D[m].T @ D[m], xty=D[m].T @ y[m], n=int(m.sum()))
    os.replace(out + ".tmp.npz", out)


def beta_from(slot_list):
    A, b = LAM * np.eye(len(FEATS) + 1), np.zeros(len(FEATS) + 1)
    A[0, 0] = 0.0
    n = 0
    for s in slot_list:
        z = np.load(os.path.join(OUT, "stats_%s.npz" % s))
        A += z["xtx"]
        b += z["xty"]
        n += int(z["n"])
    return (np.linalg.solve(A, b) if n > 0 else None), n


def roll_median(a):
    return pd.Series(np.abs(a)).rolling(MED_STEPS, min_periods=MED_MIN).median().shift(1).to_numpy()


def maker_events(slot, T, bb, ba, ok, mid):
    """Real taker orders trading at the displayed best -> arrays (ts, maker side s, price, 10 s markout bp)."""
    f = glob.glob(os.path.join(TICKS, slot, "kucoin", "swap", SYM, "feed_raw", "ticks-*.jsonl.gz"))
    if not f:
        return None
    seen, rows = set(), []
    with gzip.open(f[0], "rt") as fh:
        for line in fh:
            m = json.loads(line)
            key = (m["ts_ns"], m["side"])
            if key in seen:
                continue
            seen.add(key)
            rows.append((int(m["ts_ns"]), -1 if m["side"] == "buy" else 1, float(m["price"])))
    if not rows:
        return None
    ts = np.array([r[0] for r in rows], np.int64)
    s = np.array([r[1] for r in rows])
    px = np.array([r[2] for r in rows])
    i = np.searchsorted(T, ts, side="right") - 1
    j = np.searchsorted(T, ts + 10_000_000_000, side="right") - 1
    good = (i >= 0) & (ts + 10_000_000_000 <= T[-1])
    i, j = np.clip(i, 0, len(T) - 1), np.clip(j, 0, len(T) - 1)
    touch = np.where(s > 0, bb[i], ba[i])
    good &= ok[i] & ok[j] & (np.abs(px - touch) < TICK / 2)
    mo = s * (mid[j] - px) / px * 1e4
    return ts[good], s[good], mo[good]


def do_eval(slot, order):
    out = os.path.join(OUT, "eval_%s.json" % slot)
    if os.path.exists(out):
        return
    k = order.index(slot)
    train_slots = [s for s in order if s[:8] in P.TRAIN]
    X, D, ok = frame(slot)
    g = pd.read_parquet(os.path.join(GRID, "grid_%s.parquet" % slot))
    T, bb, ba = g.t.to_numpy(np.int64), g.bb.to_numpy(), g.ba.to_numpy()
    mid = (bb + ba) / 2
    vol = X.vol.to_numpy()
    sig = {}
    p_bp = D @ np.array(R2["beta"]["1s"])
    p_bp[~ok] = np.nan
    sig["S"] = (p_bp, np.full(len(T), THETA_S))
    sig["N"] = (p_bp, roll_median(p_bp))
    bz, _ = beta_from(train_slots)
    pz = D @ bz
    pz[~ok] = np.nan
    sig["Z"] = (pz, roll_median(pz))
    br, nr = beta_from(order[max(0, k - ROLL_HOURS):k])
    if br is not None and k >= ROLL_HOURS:
        pr = D @ br
        pr[~ok] = np.nan
        sig["R"] = (pr, roll_median(pr))
    ev = maker_events(slot, T, bb, ba, ok, mid)
    res = {"slot": slot, "part": "train" if slot[:8] in P.TRAIN else "oos"}
    lm = np.log(np.where(ok, mid, np.nan))
    r1 = np.diff(lm[::100])
    r10 = np.diff(lm[::1000])
    res["vol"] = float(np.nanmean(vol))
    res["vr"] = float(np.nanvar(r10) / (10 * np.nanvar(r1))) if np.nanvar(r1) > 0 else None
    d = np.diff(mid[ok])
    d = np.sign(d[d != 0])
    na = int((d[1:] != d[:-1]).sum())
    res["eta"] = float((d[1:] == d[:-1]).sum() / (2 * na)) if na else None
    y1 = X["y_1s"].to_numpy()
    res["ic"] = {v: P.rank_ic(sig[v][0][::5], (y1 / vol if v in ("Z", "R") else y1)[::5])[0] for v in sig}
    if ev is not None:
        ts, s, mo = ev
        net = mo + REBATE
        res["base"] = dict(n=int(len(net)), sum=float(net.sum()))
        for v, (p, th) in sig.items():
            for tau in TAUS:
                gi = np.searchsorted(T, ts - SEE_NS - tau * 1_000_000, side="right") - 1
                okg = gi >= 0
                gi = np.clip(gi, 0, len(T) - 1)
                present = okg & np.isfinite(p[gi]) & np.isfinite(th[gi]) & (s * p[gi] > -th[gi])
                res["%s_%d" % (v, tau)] = dict(n=int(present.sum()), sum=float(net[present].sum()), sq=float((net[present] ** 2).sum()))
    json.dump(res, open(out + ".tmp", "w"))
    os.replace(out + ".tmp", out)


def report():
    rows = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(OUT, "eval_*.json")))]
    lines = ["PX-4: %d hours evaluated" % len(rows)]
    for part in ("oos", "train"):
        R = [r for r in rows if r["part"] == part and "base" in r]
        if not R:
            continue
        vols = np.array([r["vol"] for r in R])
        cut = np.nanquantile(vols, [1 / 3, 2 / 3])
        lines.append("\n%s: %d hours" % (part, len(R)))
        lines.append("  %-8s %9s %9s %8s %9s %10s | per-fill net by hourly-volatility tercile (low / mid / high) and share of hours > 0" % (
            "version", "fills/h", "net/fill", "t(hour)", "hours>0", "median h"))
        for key in ["base"] + ["%s_%d" % (v, t) for t in TAUS for v in "SNZR"]:
            H = [(r[key]["n"], r[key]["sum"], r["vol"]) for r in R if key in r]
            if not H:
                continue
            n = np.array([h[0] for h in H], float)
            sm = np.array([h[1] for h in H])
            vv = np.array([h[2] for h in H])
            t = sm.mean() / (sm.std(ddof=1) / math.sqrt(len(sm))) if len(sm) > 1 and sm.std() > 0 else float("nan")
            terc = []
            for lo, hi in ((-1, cut[0]), (cut[0], cut[1]), (cut[1], 1e9)):
                m = (vv > lo) & (vv <= hi)
                terc.append("%+.2f (%.0f%%)" % (sm[m].sum() / max(n[m].sum(), 1), 100 * (sm[m] > 0).mean()) if m.any() else "-")
            lines.append("  %-8s %9.1f %+9.3f %+8.2f %8.0f%% %+10.1f | %s   [%d hours]" % (
                key, n.mean(), sm.sum() / max(n.sum(), 1), t, 100 * (sm > 0).mean(), np.median(sm), "  ".join(terc), len(H)))
        ics = {v: np.nanmean([r["ic"][v] for r in R if v in r.get("ic", {})]) for v in "SNZR"}
        lines.append("  mean hourly rank IC of the signal (S/N in bp, Z/R on the volatility-scaled return): %s" % {k: round(float(v), 4) for k, v in ics.items()})
    T = [r for r in rows if r["part"] == "train" and "N_25" in r and r["N_25"]["n"] > 0]
    if T:
        d = pd.DataFrame([dict(net=r["N_25"]["sum"] / r["N_25"]["n"], tot=r["N_25"]["sum"], vol=r["vol"], vr=r["vr"], eta=r["eta"]) for r in T]).dropna()
        lines.append("\ntraining days, version N at tau 25 ms: Spearman correlation of the hour's result with the hour's state (%d hours)" % len(d))
        for c in ("vol", "vr", "eta"):
            lines.append("  %-4s per-fill net %+.3f   hourly total %+.3f" % (c, d.net.rank().corr(d[c].rank()), d.tot.rank().corr(d[c].rank())))
    rep = "\n".join(lines)
    open(os.path.join(OUT, "px4_report.txt"), "w", encoding="utf-8").write(rep)
    print(rep)


def main():
    os.makedirs(OUT, exist_ok=True)
    mode = sys.argv[1]
    if mode == "report":
        return report()
    i, n = map(int, sys.argv[2].split("/"))
    order = slots()
    for k, slot in enumerate(order):
        if k % n == i:
            (do_stats(slot) if mode == "stats" else do_eval(slot, order))
            print(mode, slot, flush=True)
    print("PX4_%s_DONE" % mode.upper(), flush=True)


if __name__ == "__main__":
    main()
