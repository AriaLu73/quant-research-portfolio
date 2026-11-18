#!/usr/bin/env python3
"""research3 PX-2: cancel the QMM virtual orders when the frozen PX-1 price model says the price is about to move against them.
Pre-registration: docs/research3/px_cancel_2026-10-03.md (written before any result).
  model      data/research3/px/BTC-USDT/ridge.json (fitted on September L2, not refitted), evaluated every 10 ms on the L3 grid
             (px_l3grid.py) with the same time-defined features (px_ic.day_frame(step_ms=10)).
  orders     data/research3/qmm/trace_<day>_d5*.jsonl.gz: one infinitesimal order per new BTC-USDT touch level, 5 ms after the
             birth; fill time and 10 s markout known.
  rule       not posted if the prediction seen at the birth is already adverse; afterwards the first grid point g with an
             adverse prediction (bid: p_h <= -theta, ask: p_h >= +theta) is seen at g + 1.5 ms and the cancel is effective tau later;
             TTL k*h (also effective tau later). Filled only if the fill comes before the effective cancel.
  grid       h in {1 s, 5 s}; theta = q-quantile of |p_h| on the development day, q in {0, .5, .75, .9}; k in {.5, 1, 2, inf}.
  choice     development day 10-01 at tau 25 ms: highest net bp x fills per hour with >= 50 fills per hour; frozen for 10-02.
usage: Python314/python.exe scripts/research3/px_cancel.py [dev=20261001] [check=20261002] [--model=v1|v2]
(v1 = PX-2: 10 ms grid, ridge.json; v2 = PX-3: 2 ms grid, ridge_v2.json with short windows, docs/research3/px3_short_window_2026-10-03.md)"""
import glob, gzip, json, math, os, sys, warnings
import numpy as np, pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_ic as P      # noqa: E402
import l3_mid as LM     # noqa: E402

ROOT = P.ROOT
QMM = os.path.join(ROOT, "data", "research3", "qmm")
OUT = os.path.join(ROOT, "data", "research3", "px", "cancel")
REBATE = OUR_FEE
SEE_NS = 1_500_000                       # our feed delay (measured p50 1.4 ms)
TAUS = (5, 25)
HS = {"200ms": 200_000_000, "1s": 1_000_000_000, "5s": 5_000_000_000}
QS = (0.0, 0.5, 0.75, 0.9)
KS = (0.5, 1.0, 2.0, math.inf)
MS = 1_000_000


CFG = {
    "v1": dict(model="ridge.json", src="BTC-USDT-L3", step=10, hs=("1s", "5s"), ks=(0.5, 1.0, 2.0, math.inf), v2=False),          # PX-2
    "v2": dict(model="ridge_v2.json", src="BTC-USDT-L3-2ms", step=2, hs=("200ms", "1s"), ks=(2.0, math.inf), v2=True),            # PX-3
}


def predictions(day, cfg=None):
    """Frozen model on the L3 grid of one day, hour by hour -> {"t": ns, <h>: prediction} (float32 predictions)."""
    cfg = cfg or CFG["v1"]
    R = json.load(open(os.path.join(ROOT, "data", "research3", "px", "BTC-USDT", cfg["model"])))
    mu, sd = np.array(R["mu"]), np.array(R["sd"])
    hs = [h for h in ("200ms", "1s", "5s", "10s") if h in R["beta"]]
    parts = {k: [] for k in ["t"] + hs}
    ics = {h: [] for h in hs}
    files = sorted(glob.glob(os.path.join(ROOT, "data", "research3", "px", cfg["src"], "grid_%s_??.parquet" % day)))
    for f in files:
        hh = os.path.basename(f)[-10:-8]
        X = P.day_frame("BTC-USDT", day, src=cfg["src"], step_ms=cfg["step"], min_files=1, hours=(hh,), v2=cfg["v2"])
        Z = X[R["feats"]].to_numpy()
        Zs = np.c_[np.ones(len(Z)), np.clip((Z - mu) / sd, -10, 10)]
        ok = X.ok.to_numpy() & np.isfinite(Z).all(1)
        parts["t"].append(X.t.to_numpy(np.int64))
        for h in hs:
            pr = Zs @ np.array(R["beta"][h])
            pr[~ok] = np.nan
            parts[h].append(pr.astype(np.float32))
            ic = P.rank_ic(pr[::5], X["y_" + h].to_numpy()[::5])[0]
            if ic == ic:
                ics[h].append(ic)
        del X, Z, Zs
    out = {k: np.concatenate(v) for k, v in parts.items()}
    for h in hs:
        v = np.array(ics[h])
        print("  %s frozen model on the L3 grid, h %s: rank IC %.3f (sd %.3f, %d hours, %d positive)" % (day, h, v.mean(), v.std(), len(v), (v > 0).sum()), flush=True)
    return out


def load_traces(day):
    raw = []
    for p in sorted(glob.glob(os.path.join(QMM, "trace_%s_d5*.jsonl.gz" % day))):
        with gzip.open(p, "rt") as fh:
            for l in fh:
                r = json.loads(l)
                r.pop("tr", None)
                raw.append(r)
    # markouts recomputed against the L3 mid (l3_mid.py): the L2-based series used at collection time has holes (audit 2026-10-03)
    LM.fix_markouts(raw, day, lambda r: None if r["f"] is None else r["t"] * MS + r["f"] * 1000)
    return [(r["h"], r["s"], r["t"] * MS, None if r["f"] is None else r["t"] * MS + r["f"] * 1000,
             (r["m"][2] + REBATE) if r["f"] is not None and r["m"][2] == r["m"][2] else None) for r in raw]


def simulate(recs, pred, h, theta, k, tau_ms):
    """-> per order: (hour, posted, filled, net, reason) where reason = '' / 'model' / 'ttl' for the order's cancel."""
    T, p = pred["t"], pred[h]
    tau = tau_ms * MS
    out = []
    for hr, sg, t0, fill, net in recs:
        birth = t0 - 5 * MS
        i = np.searchsorted(T, birth - SEE_NS, side="right") - 1          # last grid point seen before the decision to post
        if i >= 0 and p[i] == p[i] and sg * p[i] <= -theta:
            out.append((hr, False, False, None, "skip"))
            continue
        end = fill if fill is not None else t0 + 5000 * MS
        j0 = np.searchsorted(T, birth - SEE_NS, side="right")
        j1 = np.searchsorted(T, end - SEE_NS, side="right")
        seg = sg * p[j0:j1]
        bad = np.nonzero(seg <= -theta)[0]
        c_model = T[j0 + bad[0]] + SEE_NS + tau if len(bad) else math.inf
        c_ttl = t0 + k * HS[h] + tau if k != math.inf else math.inf
        c = min(c_model, c_ttl)
        reason = "" if c == math.inf else ("model" if c_model <= c_ttl else "ttl")
        filled = fill is not None and fill < c
        out.append((hr, True, filled, net if filled else None, reason if not filled else ""))
    return out


def summary(out, hours, would_fill):
    nets = np.array([o[3] for o in out if o[2] and o[3] is not None])
    n = len(nets)
    bh = {}
    for o in out:
        if o[2] and o[3] is not None:
            bh[o[0]] = bh.get(o[0], 0.0) + o[3]
    cancels = sum(1 for o in out if o[1] and not o[2] and o[4] in ("model", "ttl"))
    saved = sum(1 for o, wf in zip(out, would_fill) if o[1] and not o[2] and wf)
    mean = nets.mean() if n else float("nan")
    se = nets.std(ddof=1) / math.sqrt(n) if n > 1 else float("nan")
    return dict(fills_h=n / hours, net=mean, se=se, t=mean / se if se == se and se > 0 else float("nan"),
                pos=sum(v > 0 for v in bh.values()), hours=hours, value_h=(mean * n / hours) if n else 0.0,
                cancels_h=cancels / hours, posted=sum(o[1] for o in out), avoided=saved)


def main():
    ver = "v1"
    for a in list(sys.argv):
        if a.startswith("--model="):
            ver = a.split("=", 1)[1]
            sys.argv.remove(a)
    cfg = CFG[ver]
    hs_grid, ks_grid = cfg["hs"], cfg["ks"]
    dev = sys.argv[1] if len(sys.argv) > 1 else "20261001"
    chk = sys.argv[2] if len(sys.argv) > 2 else "20261002"
    os.makedirs(OUT, exist_ok=True)
    print("model", ver, cfg, flush=True)
    print("development day", dev, flush=True)
    pd_ = predictions(dev, cfg)
    rd = load_traces(dev)
    hours = len({r[0] for r in rd})
    wf = [r[3] is not None for r in rd]
    base = [(r[0], True, r[3] is not None, r[4], "") for r in rd]
    print("  no cancel: %s" % {k: round(v, 3) for k, v in summary(base, hours, wf).items()}, flush=True)
    thetas = {h: {q: (float(np.nanquantile(np.abs(pd_[h][::7]), q)) if q > 0 else 0.0) for q in QS} for h in hs_grid}
    print("  theta (bp) by quantile of |p_h| on the development day:", thetas, flush=True)
    rows = []
    for h in hs_grid:
        for q in QS:
            for k in ks_grid:
                for tau in TAUS:
                    s = summary(simulate(rd, pd_, h, thetas[h][q], k, tau), hours, wf)
                    rows.append(dict(day=dev, h=h, q=q, theta=thetas[h][q], k=k, tau=tau) | s)
    D = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    cols = ["h", "q", "theta", "k", "tau", "fills_h", "net", "se", "t", "pos", "hours", "value_h", "cancels_h", "avoided"]
    print(D[cols].round(3).to_string(), flush=True)
    cand = D[(D.tau == 25) & (D.fills_h >= 50)].sort_values("value_h", ascending=False)
    if not len(cand):
        print("no configuration reaches 50 fills per hour at tau 25 ms on the development day -> NOT_PASSED", flush=True)
        D.to_csv(os.path.join(OUT, "px_cancel_%s_%s.csv" % (ver, dev)), index=False)
        return
    pick = cand.iloc[0]
    frozen = dict(h=pick.h, q=float(pick.q), theta=float(pick.theta), k=float(pick.k))
    json.dump(frozen, open(os.path.join(OUT, "frozen_%s_%s.json" % (ver, dev)), "w"))
    print("\nfrozen on the development day:", frozen, flush=True)
    print("\ncheck day", chk, flush=True)
    del pd_
    pc = predictions(chk, cfg)
    rc = load_traces(chk)
    hc = len({r[0] for r in rc})
    wfc = [r[3] is not None for r in rc]
    basec = [(r[0], True, r[3] is not None, r[4], "") for r in rc]
    print("  no cancel: %s" % {k: round(v, 3) for k, v in summary(basec, hc, wfc).items()}, flush=True)
    res = {}
    for tau in TAUS:
        s = summary(simulate(rc, pc, frozen["h"], frozen["theta"], frozen["k"], tau), hc, wfc)
        res[tau] = s
        print("  frozen rule, tau %d ms: %s" % (tau, {k: round(v, 3) for k, v in s.items()}), flush=True)
    s = res[25]
    ok1 = s["net"] > 0 and s["t"] >= 2
    ok2 = s["fills_h"] >= 50
    ok3 = s["pos"] / s["hours"] >= 0.6
    for tau in (0, 2, 10, 50):
        s2 = summary(simulate(rc, pc, frozen["h"], frozen["theta"], frozen["k"], tau), hc, wfc)
        print("  (sensitivity) tau %d ms: fills/h %.1f net %+.3f (se %.3f) hours > 0: %d/%d" % (tau, s2["fills_h"], s2["net"], s2["se"], s2["pos"], hc), flush=True)
    print("\nverdict (tau 25 ms): %s  (net > 0 & t >= 2: %s, >= 50 fills/h: %s, >= 60%% hours positive: %s)" % (
        "PASSED" if ok1 and ok2 and ok3 else "NOT_PASSED", ok1, ok2, ok3), flush=True)
    D.to_csv(os.path.join(OUT, "px_cancel_%s_%s.csv" % (ver, dev)), index=False)
    print("PX_CANCEL_DONE", flush=True)


if __name__ == "__main__":
    main()
