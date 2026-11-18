#!/usr/bin/env python3
"""research5 PX-9: does causal trailing-window input normalisation (the BiN idea of the TLOB paper, Berti & Kasneci 2025 /
Tran et al. 2021) and a small MLP improve the short-horizon price model of the KuCoin BTC-USDT perpetual?
PREDICTION STUDY ONLY (rank IC, calibration); no strategy, no fills, no claim about profit.

Data (read-only): the 10 ms grids data/research3/px/BTC-USDT-10ms (20 Aug/Sep days) and data/research5/px_grid_td (6 earlier
days). Features and targets are those of research3 px_ic.day_frame via px4_proxy.frame (imported, unchanged), built per hour on
the 10 ms grid and SAMPLED EVERY 100 ms. The first 5 minutes of every hour (warm-up of the 5-minute scalers inside day_frame,
which restart each hour) are dropped for every model, in training and in evaluation.

Split (fixed before any result): train 20260826..0904 (10 days), validation 0905..0907 (ridge lambda, MLP early stopping),
test 0910..0924 (7 days, read once), earlier = 6 days 20251001..20260801 (read once, models unchanged).

Models (all on the same rows):
  A0   frozen ridge_v2 (research3; 1 s and 5 s only), reference
  A    ridge per target, features standardised with fixed train mean / sd, clipped at +-10        (current practice)
  B1   ridge, each feature z-scored with its own TRAILING 1-minute mean / sd (window ends at the decision row), clip +-10
  B10  same, trailing 10 minutes
  B1x / B10x   B plus 5 columns: the ofi1..5_1s group z-scored ACROSS the five levels at the same row (the only feature group
       on a common scale: each is 1 s order-flow imbalance over the level's own trailing depth)
  C    MLP 24-64-64-1, GELU, AdamW, early stopping on the validation days, on A's inputs
  D1 / D10   the same MLP on B1 / B10 inputs
  extras (outside the brief, marked): Av / B10v = ridge on target / current 1 s volatility, prediction multiplied back by it.
Targets: mid return over 1 s / 5 s / 10 s in bp (y_1s, y_5s, y_10s of day_frame) and the paper's smoothed label for 5 s and
10 s: mean log-mid over [t+h-k, t+h] minus mean over [t-k, t], k = h/5 (fixed, not scanned), in bp.

usage: px9_adaptive_norm.py cache i/n | ridge | mlp F|T1|T10 | eval dev|test|earlier | report | timing
"""
import glob, json, math, os, sys, time, warnings
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
import numpy as np, pandas as pd

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research3"))
GRID_R3 = os.path.join(ROOT, "data", "research3", "px", "BTC-USDT-10ms")
GRID_TD = os.path.join(ROOT, "data", "research5", "px_grid_td")
OUT = os.path.join(ROOT, "data", "research5", "px9")
CACHE, MODELS, EVAL = (os.path.join(OUT, d) for d in ("cache", "models", "eval"))
REPORT = os.path.join(ROOT, "data", "research5", "px9_report.txt")

TRAIN = ("20260826", "20260827", "20260828", "20260829", "20260830", "20260831", "20260901", "20260902", "20260903", "20260904")
VAL = ("20260905", "20260906", "20260907")
TEST = ("20260910", "20260911", "20260914", "20260917", "20260918", "20260923", "20260924")
EARLY = ("20251001", "20260101", "20260401", "20260601", "20260701", "20260801")
BLOCKS = dict(dev=VAL, test=TEST, earlier=EARLY)
TARGETS = ("1s", "5s", "10s", "s5s", "s10s")
YCOLS = ("100ms", "1s", "5s", "10s", "30s")
SM_K = {"s5s": (50, 10), "s10s": (100, 20)}           # (h, k) in 100 ms steps, k = h / 5
W = {"T1": 600, "T10": 6000}                           # trailing windows in 100 ms rows
WARM_NS = 300 * 10**9
LAMBDAS = (1.0, 10.0, 100.0, 1000.0, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9)   # grid widened twice on the VALIDATION days (first pass stopped at 1e5, second at 1e7: both hit the bound)
OFI_GRP = ("ofi1_1s", "ofi2_1s", "ofi3_1s", "ofi4_1s", "ofi5_1s")
MASK = {"20260701": (pd.Timestamp("2026-07-01 18:09:30").value, pd.Timestamp("2026-07-01 18:23:30").value)}   # crossed book + 5 min scaler memory
SD_FLOOR = 0.05                                        # trailing sd is floored at 5 % of the feature's train sd (spread is often constant)
MLP = dict(hidden=(64, 64), lr=1e-3, wd=1e-2, batch=4096, max_epochs=10, checks_per_epoch=2, patience=3, seed=20261006, yclip=20.0)


# ---------------------------------------------------------------------------------------------------------------- cache
def all_slots():
    S = []
    for d in (GRID_R3, GRID_TD):
        S += [(d, os.path.basename(f)[5:-8]) for f in sorted(glob.glob(os.path.join(d, "grid_*.parquet")))]
    return S


def do_cache(gdir, slot):
    import px4_proxy as PP
    out = os.path.join(CACHE, "c_%s.npz" % slot)
    if os.path.exists(out):
        return
    PP.SRC, PP.GRID = gdir, gdir
    X, D, ok = PP.frame(slot)
    g = pd.read_parquet(os.path.join(gdir, "grid_%s.parquet" % slot), columns=["t", "bb", "ba", "crossed"])
    assert len(g) == len(X) and (g.t.to_numpy() == X.t.to_numpy()).all()          # one hour, already sorted
    bb, ba = g.bb.to_numpy(), g.ba.to_numpy()
    spr = np.rint((ba - bb) / 0.1)
    okk = (~g.crossed.to_numpy()) & (spr >= 1) & (spr <= 50)
    lm = np.log(pd.Series(np.where(okk, (bb + ba) / 2, np.nan)).ffill().to_numpy())[::10]
    sl = slice(None, None, 10)
    R = dict(feats=X[PP.FEATS].to_numpy(np.float32)[sl], ok=ok[sl], t=X.t.to_numpy(np.int64)[sl], vol=X.vol.to_numpy(np.float32)[sl])
    for h in YCOLS:
        R["y_" + h] = X["y_" + h].to_numpy(np.float32)[sl]
    n = len(lm)
    for nm, (h, k) in SM_K.items():
        c = np.cumsum(np.r_[0.0, lm])
        past = np.full(n, np.nan)
        fut = np.full(n, np.nan)
        i = np.arange(n)
        m = i >= k
        past[m] = (c[i[m] + 1] - c[i[m] - k]) / (k + 1)                              # mean lm[t-k .. t]
        m = i + h < n
        fut[m] = (c[i[m] + h + 1] - c[i[m] + h - k]) / (k + 1)                       # mean lm[t+h-k .. t+h]
        R["y_" + nm] = ((fut - past) * 1e4).astype(np.float32)
    for h in ("1s", "5s"):
        p = D @ np.array(PP.R2["beta"][h])
        R["r2_" + h] = p.astype(np.float32)[sl]
    np.savez(out + ".tmp.npz", **R)
    os.replace(out + ".tmp.npz", out)


def load_day(day):
    fs = sorted(glob.glob(os.path.join(CACHE, "c_%s_??.npz" % day)))
    P = [dict(np.load(f)) for f in fs]
    hrs = [int(os.path.basename(f)[-6:-4]) for f in fs]
    D = {k: np.concatenate([p[k] for p in P]) for k in P[0]}
    D["hour"] = np.concatenate([np.full(len(p["t"]), h, np.int16) for p, h in zip(P, hrs)])
    start = np.concatenate([np.full(len(p["t"]), p["t"][0], np.int64) for p in P])
    good = D["ok"] & np.isfinite(D["feats"]).all(1) & (D["t"] - start >= WARM_NS)
    if day in MASK:
        good &= ~((D["t"] >= MASK[day][0]) & (D["t"] < MASK[day][1]))
    D["good"] = good
    return D


def trail_z(Z, w, floor):
    """Causal: mean / sd of the last w rows up to AND INCLUDING the current row (rows not 'good' are NaN and skipped)."""
    df = pd.DataFrame(Z)
    r = df.rolling(w, min_periods=int(0.4 * w))      # 0.4 not 0.5: the hourly 5-minute warm-up gap must not void the 10-minute window
    m, s = r.mean().to_numpy(), r.std(ddof=0).to_numpy()
    z = (Z - m) / np.maximum(s, floor)
    return np.clip(z, -10, 10).astype(np.float32)


def cross_grp(Z, idx):
    G = Z[:, idx]
    s = G.std(1, keepdims=True)
    return np.where(s > 1e-9, (G - G.mean(1, keepdims=True)) / np.maximum(s, 1e-9), 0.0).astype(np.float32)


def feature_sets(D, mu, sd, feats, which=("F", "T1", "T10", "T1x", "T10x")):
    """-> dict of matrices on the day's rows, and the COMMON row mask (every set defined)."""
    Z = D["feats"].astype(np.float64)
    Z[~D["good"]] = np.nan
    S = {}
    mask = D["good"].copy()
    if "F" in which:
        S["F"] = np.clip((Z - mu) / sd, -10, 10).astype(np.float32)
    for nm, w in W.items():
        z = trail_z(Z, w, SD_FLOOR * sd)
        mask &= np.isfinite(z).all(1)
        if nm in which:
            S[nm] = z
        if nm + "x" in which:
            S[nm + "x"] = np.c_[z, cross_grp(Z, [feats.index(f) for f in OFI_GRP])]
    return S, mask


def feats_list():
    import px4_proxy as PP
    return list(PP.FEATS)


def moments():
    f = os.path.join(MODELS, "moments.json")
    if os.path.exists(f):
        m = json.load(open(f))
        return np.array(m["mu"]), np.array(m["sd"])
    s0, s1, s2 = 0, 0.0, 0.0
    for day in TRAIN:
        D = load_day(day)
        Z = D["feats"][D["good"]].astype(np.float64)
        s0 += len(Z); s1 = s1 + Z.sum(0); s2 = s2 + (Z ** 2).sum(0)
    mu = s1 / s0
    sd = np.sqrt(s2 / s0 - mu ** 2)
    json.dump(dict(mu=mu.tolist(), sd=sd.tolist(), n=int(s0)), open(f, "w"))
    return mu, sd


# ---------------------------------------------------------------------------------------------------------------- ridge
RIDGE_SETS = ("F", "T1", "T10", "T1x", "T10x")
RIDGE_NAME = dict(F="A", T1="B1", T10="B10", T1x="B1x", T10x="B10x")
VS = (("F", "Av"), ("T10", "B10v"))                    # extras: target / vol


def do_ridge():
    feats = feats_list()
    mu, sd = moments()
    st = {}
    for part, days in (("train", TRAIN), ("val", VAL)):
        for day in days:
            D = load_day(day)
            S, mask = feature_sets(D, mu, sd, feats)
            for s in RIDGE_SETS:
                X = np.c_[np.ones(len(S[s])), S[s].astype(np.float64)]
                tg = [(t, D["y_" + t].astype(np.float64)) for t in TARGETS]
                if s in dict(VS):
                    tg += [("v" + t, D["y_" + t].astype(np.float64) / D["vol"]) for t in ("1s", "5s", "10s")]
                for t, y in tg:
                    m = mask & np.isfinite(y)
                    a = st.setdefault((part, s, t), [0.0, 0.0, 0.0, 0])
                    a[0] = a[0] + X[m].T @ X[m]; a[1] = a[1] + X[m].T @ y[m]; a[2] += float(y[m] @ y[m]); a[3] += int(m.sum())
            print("ridge stats", part, day, int(mask.sum()), flush=True)
    M = dict(mu=mu.tolist(), sd=sd.tolist(), feats=feats, models={})
    for (part, s, t), (A, b, _, n) in st.items():
        if part != "train":
            continue
        Av, bv, yy, nv = st[("val", s, t)]
        best = None
        for lam in LAMBDAS:
            pen = lam * np.eye(len(b)); pen[0, 0] = 0
            bt = np.linalg.solve(A + pen, b)
            mse = (yy - 2 * bt @ bv + bt @ Av @ bt) / nv
            if best is None or mse < best[0]:
                best = (mse, lam, bt)
        name = (dict(VS)[s] if t.startswith("v") else RIDGE_NAME[s]) + "|" + t.lstrip("v")
        M["models"][name] = dict(set=s, target=t, lam=best[1], beta=best[2].tolist(), n_train=n, val_r2=float(1 - best[0] / (yy / nv)))
        print(name, "lambda", best[1], "val R2 %.5f" % (1 - best[0] / (yy / nv)), flush=True)
    json.dump(M, open(os.path.join(MODELS, "ridge.json"), "w"))


# ------------------------------------------------------------------------------------------------------------------ MLP
def gelu(x):
    return 0.5 * x * (1.0 + np.tanh(0.7978845608 * (x + 0.044715 * x * x * x)))


def gelu_both(x):
    """-> (gelu(x), d gelu / dx), one tanh."""
    x2 = x * x
    t = np.tanh(0.7978845608 * x * (1.0 + 0.044715 * x2))
    return 0.5 * x * (1.0 + t), 0.5 * (1.0 + t) + 0.3989422804 * x * (1.0 - t * t) * (1.0 + 0.134145 * x2)


def mlp_forward(Wt, X):
    h = X
    for i in range(0, len(Wt) - 2, 2):
        h = gelu(h @ Wt[i] + Wt[i + 1])
    return (h @ Wt[-2] + Wt[-1])[:, 0]


def mlp_predict(Wt, X, chunk=200_000):
    return np.concatenate([mlp_forward(Wt, X[i:i + chunk]) for i in range(0, len(X), chunk)]) if len(X) else np.zeros(0, np.float32)


def mlp_train(Xtr, ytr, Xva, yva, cfg, log):
    rng = np.random.default_rng(cfg["seed"])
    sizes = (Xtr.shape[1],) + tuple(cfg["hidden"]) + (1,)
    Wt = []
    for a, b in zip(sizes[:-1], sizes[1:]):
        Wt += [(rng.standard_normal((a, b)) * math.sqrt(1.0 / a)).astype(np.float32), np.zeros(b, np.float32)]
    m1 = [np.zeros_like(w) for w in Wt]; m2 = [np.zeros_like(w) for w in Wt]
    b1, b2, eps, lr, wd, B = 0.9, 0.999, 1e-8, cfg["lr"], cfg["wd"], cfg["batch"]
    nb = len(Xtr) // B
    check = max(nb // cfg["checks_per_epoch"], 1)
    best, bad, step = (np.inf, None), 0, 0

    def val():
        return float(np.mean((mlp_predict(Wt, Xva) - yva) ** 2))

    for ep in range(cfg["max_epochs"]):
        perm = rng.permutation(len(Xtr))
        for k in range(nb):
            ix = perm[k * B:(k + 1) * B]
            x, y = Xtr[ix], ytr[ix]
            h1, g1 = gelu_both(x @ Wt[0] + Wt[1])
            h2, g2 = gelu_both(h1 @ Wt[2] + Wt[3])
            p = (h2 @ Wt[4] + Wt[5])[:, 0]
            g = (2.0 / B) * (p - y)[:, None]
            G = [None] * 6
            G[4] = h2.T @ g; G[5] = g.sum(0)
            d2 = (g @ Wt[4].T) * g2
            G[2] = h1.T @ d2; G[3] = d2.sum(0)
            d1 = (d2 @ Wt[2].T) * g1
            G[0] = x.T @ d1; G[1] = d1.sum(0)
            gn = math.sqrt(sum(float((q * q).sum()) for q in G))
            sc = min(1.0, 1.0 / max(gn, 1e-12))                                    # gradient-norm clip at 1
            step += 1
            for i in range(6):
                q = G[i] * sc
                m1[i] = b1 * m1[i] + (1 - b1) * q
                m2[i] = b2 * m2[i] + (1 - b2) * q * q
                up = (m1[i] / (1 - b1 ** step)) / (np.sqrt(m2[i] / (1 - b2 ** step)) + eps)
                if i % 2 == 0:
                    Wt[i] *= (1 - lr * wd)                                         # decoupled weight decay (weights only)
                Wt[i] -= (lr * up).astype(np.float32)
            if (k + 1) % check == 0:
                v = val()
                log("  epoch %d step %d val mse %.6f" % (ep, step, v))
                if v < best[0] - 1e-7:
                    best, bad = (v, [w.copy() for w in Wt]), 0
                else:
                    bad += 1
                if bad >= cfg["patience"]:
                    return best
    return best


def do_mlp(s):
    feats = feats_list()
    mu, sd = moments()
    A = {}
    for part, days in (("train", TRAIN), ("val", VAL)):
        Xs, Ys = [], {t: [] for t in TARGETS}
        for day in days:
            D = load_day(day)
            S, mask = feature_sets(D, mu, sd, feats, which=(s,))
            Xs.append(S[s][mask])
            for t in TARGETS:
                Ys[t].append(D["y_" + t][mask])
            print("mlp load", s, day, flush=True)
        A[part] = (np.concatenate(Xs), {t: np.concatenate(Ys[t]) for t in TARGETS})
    name = dict(F="C", T1="D1", T10="D10")[s]
    for t in TARGETS:
        out = os.path.join(MODELS, "mlp_%s_%s.npz" % (name, t))
        if os.path.exists(out):
            continue
        mt, mv = np.isfinite(A["train"][1][t]), np.isfinite(A["val"][1][t])
        ysd = float(A["train"][1][t][mt].std())
        c = MLP["yclip"]
        ytr = np.clip(A["train"][1][t][mt] / ysd, -c, c).astype(np.float32)
        yva = np.clip(A["val"][1][t][mv] / ysd, -c, c).astype(np.float32)
        t0 = time.time()
        v, Wt = mlp_train(A["train"][0][mt], ytr, A["val"][0][mv], yva, MLP, lambda m: print(name, t, m, flush=True))
        np.savez(out, ysd=ysd, val_mse=v, val_var=float(yva.var()), **{"w%d" % i: w for i, w in enumerate(Wt)})
        print("%s|%s best val mse %.6f (target var %.6f, R2 %.5f) %.0f s" % (name, t, v, yva.var(), 1 - v / yva.var(), time.time() - t0), flush=True)


# ----------------------------------------------------------------------------------------------------------------- eval
def rk(a):
    return pd.Series(a).rank().to_numpy()


def corr(a, b):
    return float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 and a.std() > 0 and b.std() > 0 else float("nan")


def predict_all(D, feats, mu, sd, R, mlps):
    S, mask = feature_sets(D, mu, sd, feats)
    P = {"A0|1s": D["r2_1s"], "A0|5s": D["r2_5s"]}
    for name, m in R["models"].items():
        p = np.c_[np.ones(len(S[m["set"]])), S[m["set"]]] @ np.array(m["beta"])
        P[name] = p * D["vol"] if m["target"].startswith("v") else p
    for (name, t), (Wt, ysd) in mlps.items():
        X = np.nan_to_num(S[dict(C="F", D1="T1", D10="T10")[name]])
        P["%s|%s" % (name, t)] = mlp_predict(Wt, X) * ysd
    return P, mask


def load_mlps():
    out = {}
    for f in glob.glob(os.path.join(MODELS, "mlp_*.npz")):
        z = np.load(f)
        name, t = os.path.basename(f)[4:-4].split("_")
        out[(name, t)] = ([z["w%d" % i] for i in range(6)], float(z["ysd"]))
    return out


def do_eval(block):
    feats = feats_list()
    mu, sd = moments()
    R = json.load(open(os.path.join(MODELS, "ridge.json")))
    mlps = load_mlps()
    rng = np.random.default_rng(7)
    for day in BLOCKS[block]:
        out = os.path.join(EVAL, "%s_%s.json" % (block, day))
        D = load_day(day)
        P, mask = predict_all(D, feats, mu, sd, R, mlps)
        rows, hrows = [], []
        hours = np.unique(D["hour"])
        hvol = {int(h): float(np.nanmean(D["vol"][mask & (D["hour"] == h)])) for h in hours}
        sub = {"hour": D["hour"][mask][::5], "vol": D["vol"][mask][::5]}
        for name, p in P.items():
            t = name.split("|")[1]
            y = D["y_" + t]
            m = mask & np.isfinite(y) & np.isfinite(p)
            pp, yy, hh = p[m].astype(np.float64), y[m].astype(np.float64), D["hour"][m]
            rp, ry = rk(pp), rk(yy)
            r = dict(model=name.split("|")[0], target=t, day=day, n=int(m.sum()), ric=corr(rp, ry), pic=corr(pp, yy),
                     slope=float(np.cov(pp, yy)[0, 1] / pp.var()), pred_sd=float(pp.std()), y_sd=float(yy.std()),
                     r2=float(1 - ((yy - pp) ** 2).mean() / (yy ** 2).mean()))
            r["ctl_shift"] = corr(np.roll(rp, 36000), ry)                         # prediction paired with the target one hour later
            ys = yy.copy()
            for h in hours:
                ix = np.where(hh == h)[0]
                ys[ix] = yy[rng.permutation(ix)]
                if len(ix) > 1000:
                    hrows.append(dict(model=r["model"], target=t, day=day, hour=int(h), vol=hvol[int(h)], n=int(len(ix)),
                                      ric=corr(rk(pp[ix]), rk(yy[ix])), slope=float(np.cov(pp[ix], yy[ix])[0, 1] / pp[ix].var()) if pp[ix].var() > 0 else None))
            r["ctl_shuf"] = corr(rp, rk(ys))
            if t == "1s":                                                          # the 1 s model read against other horizons
                for h2 in YCOLS:
                    y2 = D["y_" + h2]
                    m2 = m & np.isfinite(y2)
                    r["dec_" + h2] = corr(rk(p[m2]), rk(y2[m2]))
            rows.append(r)
            sub["p_" + name] = p[mask][::5].astype(np.float32)
        for t in TARGETS:
            sub["y_" + t] = D["y_" + t][mask][::5]
        json.dump(dict(rows=rows, hrows=hrows, hvol=hvol, rows_good=int(mask.sum()), rows_all=int(len(mask))), open(out, "w"))
        np.savez(os.path.join(EVAL, "sub_%s_%s.npz" % (block, day)), **sub)
        print("eval", block, day, int(mask.sum()), flush=True)


# --------------------------------------------------------------------------------------------------------------- report
ORDER = ("A0", "A", "B1", "B10", "B1x", "B10x", "C", "D1", "D10", "Av", "B10v")


def tstat(v):
    v = np.asarray([x for x in v if x is not None and np.isfinite(x)], float)
    return (v.mean(), v.std(ddof=1), v.mean() / v.std(ddof=1) * math.sqrt(len(v))) if len(v) > 1 and v.std() > 0 else (v.mean() if len(v) else np.nan, np.nan, np.nan)


def do_report():
    L = []
    P = L.append
    P("PX-9: causal trailing-window input normalisation and a small MLP for the BTC-USDT perpetual price model (prediction only)")
    P("rows: 100 ms samples, first 5 min of each hour dropped, common mask across all models; rank IC = Spearman(prediction, target)")
    dev_h = []
    for day in TRAIN + VAL:
        for f in sorted(glob.glob(os.path.join(CACHE, "c_%s_??.npz" % day))):
            z = np.load(f)
            dev_h.append(float(np.nanmean(z["vol"][z["ok"]])))
    cut = np.nanquantile(dev_h, [1 / 3, 2 / 3])
    P("hourly 1 s volatility terciles (cut on the %d development hours): %.3f / %.3f bp" % (len(dev_h), cut[0], cut[1]))
    R2 = json.load(open(os.path.join(MODELS, "ridge.json")))
    P("ridge lambda (validation days): " + ", ".join("%s=%g" % (k, v["lam"]) for k, v in R2["models"].items()))
    for f in sorted(glob.glob(os.path.join(MODELS, "mlp_*.npz"))):
        z = np.load(f)
        P("  %s  validation R2 (standardised, clipped target) %.5f" % (os.path.basename(f)[4:-4], 1 - float(z["val_mse"]) / float(z["val_var"])))
    ALL = {}
    for block in ("dev", "test", "earlier"):
        fs = sorted(glob.glob(os.path.join(EVAL, "%s_*.json" % block)))
        if not fs:
            continue
        J = [json.load(open(f)) for f in fs]
        d = pd.DataFrame([r for j in J for r in j["rows"]])
        h = pd.DataFrame([r for j in J for r in j["hrows"]])
        ALL[block] = (d, h)
        subs = [np.load(f) for f in sorted(glob.glob(os.path.join(EVAL, "sub_%s_*.npz" % block)))]
        P("\n" + "=" * 150)
        P("BLOCK %s: %d days (%s); rows used %s of %s" % (block, len(J), " ".join(sorted(d.day.unique())), "{:,}".format(sum(j["rows_good"] for j in J)), "{:,}".format(sum(j["rows_all"] for j in J))))
        P("  per-day table: day vol = mean hourly 1 s vol (bp); A|1s rank IC; B10|1s; D10|1s; calibration slope A|1s, B10|1s, Av|1s")
        for day in sorted(d.day.unique()):
            g = d[(d.day == day) & (d.target == "1s")].set_index("model")
            hv = np.mean(list(J[sorted(d.day.unique()).index(day)]["hvol"].values()))
            P("    %s vol %.2f | IC A %.4f B1 %.4f B10 %.4f C %.4f D10 %.4f | slope A %.2f B10 %.2f C %.2f D10 %.2f Av %.2f B10v %.2f" % (
                day, hv, g.ric["A"], g.ric["B1"], g.ric["B10"], g.ric["C"], g.ric["D10"], g.slope["A"], g.slope["B10"], g.slope["C"], g.slope["D10"], g.slope["Av"], g.slope["B10v"]))
        for t in TARGETS:
            P("\n  target %s" % t)
            P("  %-5s | %7s %7s %7s %6s %7s %5s | %7s %7s | %8s | %-20s | %-23s | %-17s | %8s %8s" % (
                "model", "IC pool", "IC day", "sd", "ICIR", "t", ">0", "IC hour", "t(hour)", "Pearson", "IC by hour-vol terc.", "calib slope day mean/min/max", "slope pooled", "ctl shift", "ctl shuf"))
            for mdl in ORDER:
                g = d[(d.model == mdl) & (d.target == t)]
                if not len(g):
                    continue
                gh = h[(h.model == mdl) & (h.target == t)]
                key = "p_%s|%s" % (mdl, t)
                pp = np.concatenate([s[key] for s in subs]); yy = np.concatenate([s["y_" + t] for s in subs])
                m = np.isfinite(pp) & np.isfinite(yy)
                pool = corr(rk(pp[m]), rk(yy[m]))
                pslope = float(np.cov(pp[m].astype(float), yy[m].astype(float))[0, 1] / pp[m].astype(float).var())
                mu_, sd_, t_ = tstat(g.ric)
                hm, _, ht = tstat(gh.ric)
                terc = [gh.ric[(gh.vol > lo) & (gh.vol <= hi)] for lo, hi in ((-1, cut[0]), (cut[0], cut[1]), (cut[1], 1e9))]
                P("  %-5s | %7.4f %7.4f %7.4f %6.1f %7.1f %4.0f%% | %7.4f %7.1f | %8.4f | %-20s | %5.2f / %5.2f / %5.2f     | %8.2f          | %+8.4f %+8.4f" % (
                    mdl, pool, mu_, sd_, mu_ / sd_ if sd_ and sd_ > 0 else np.nan, t_, 100 * (g.ric > 0).mean(), hm, ht, g.pic.mean(),
                    " ".join("%.3f(%d)" % (x.mean(), len(x)) if len(x) else "-" for x in terc), g.slope.mean(), g.slope.min(), g.slope.max(), pslope,
                    g.ctl_shift.mean(), g.ctl_shuf.mean()))
        P("\n  paired differences of rank IC (per day: mean, t over days | per hour: mean, t over hours | hours better)")
        for a, b, why in (("A", "B1", "adaptive 1 min vs fixed"), ("A", "B10", "adaptive 10 min vs fixed"), ("B1", "B1x", "cross-level group, 1 min"), ("B10", "B10x", "cross-level group, 10 min"),
                          ("A", "C", "MLP vs ridge, fixed inputs"), ("B1", "D1", "MLP vs ridge, trailing 1 min"), ("B10", "D10", "MLP vs ridge, trailing 10 min"), ("C", "D10", "MLP: trailing 10 min vs fixed"),
                          ("A0", "A", "refit vs frozen ridge_v2"), ("A", "Av", "extra: vol-scaled target, fixed"), ("A", "B10v", "extra: vol-scaled target + trailing 10 min")):
            for t in TARGETS:
                x = d[(d.model == a) & (d.target == t)].set_index("day").ric
                y = d[(d.model == b) & (d.target == t)].set_index("day").ric
                if not len(x) or not len(y):
                    continue
                dd = (y - x).dropna()
                xh = h[(h.model == a) & (h.target == t)].set_index(["day", "hour"]).ric
                yh = h[(h.model == b) & (h.target == t)].set_index(["day", "hour"]).ric
                dh = (yh - xh).dropna()
                m1, _, t1 = tstat(dd); m2, _, t2 = tstat(dh)
                P("    %-5s - %-4s %-5s %-42s day %+.4f t %+6.1f (%d/%d days) | hour %+.4f t %+6.1f (%.0f%% of %d hours)" % (b, a, t, why, m1, t1, (dd > 0).sum(), len(dd), m2, t2, 100 * (dh > 0).mean(), len(dh)))
        P("\n  per-hour calibration slope (realised on predicted): median, 10 %% / 90 %% quantile across hours, share of hours within 0.7..1.3")
        for t in ("1s", "5s", "10s"):
            for mdl in ("A", "B1", "B10", "C", "D10", "Av", "B10v"):
                s = h[(h.model == mdl) & (h.target == t)].slope.dropna().astype(float)
                if len(s):
                    P("    %-5s %-4s median %.2f  q10 %.2f  q90 %.2f  within %.0f%%  sd of log-slope %.3f" % (mdl, t, s.median(), s.quantile(0.1), s.quantile(0.9), 100 * ((s > 0.7) & (s < 1.3)).mean(), np.log(s[s > 0]).std()))
        P("\n  the 1 s models read against other horizons (mean daily rank IC): " + " ".join(YCOLS))
        for mdl in ORDER:
            g = d[(d.model == mdl) & (d.target == "1s")]
            if len(g):
                P("    %-5s " % mdl + " ".join("%.4f" % g["dec_" + c].mean() for c in YCOLS))
    rep = "\n".join(L)
    extra = os.path.join(OUT, "px9_notes.txt")
    if os.path.exists(extra):
        rep += "\n\n" + open(extra, encoding="utf-8").read()
    open(REPORT, "w", encoding="utf-8").write(rep)
    print(rep)


# --------------------------------------------------------------------------------------------------------------- timing
def do_timing(name="D10", t="1s"):
    """Per-row cost in pure numpy: O(F) update of the trailing sums (ring buffer) + z-score + MLP forward for ONE row."""
    z = np.load(os.path.join(MODELS, "mlp_%s_%s.npz" % (name, t)))
    Wt = [z["w%d" % i].astype(np.float64) for i in range(6)]
    F, w = Wt[0].shape[0], W["T10" if name.endswith("10") else "T1"]
    rng = np.random.default_rng(0)
    buf = rng.standard_normal((w, F)); s1 = buf.sum(0); s2 = (buf ** 2).sum(0)
    floor = np.full(F, 0.05)
    xs = rng.standard_normal((20000, F))
    R = json.load(open(os.path.join(MODELS, "ridge.json")))
    beta = np.array(R["models"]["B10|1s"]["beta"])
    res = {}
    for kind in ("mlp", "ridge"):
        k = 0
        t0 = time.perf_counter()
        for x in xs:
            old = buf[k]
            s1 += x - old; s2 += x * x - old * old
            buf[k] = x
            k = (k + 1) % w
            m = s1 / w
            sdv = np.sqrt(np.maximum(s2 / w - m * m, 0.0))
            zz = np.clip((x - m) / np.maximum(sdv, floor), -10, 10)
            if kind == "mlp":
                h = zz @ Wt[0] + Wt[1]; h = 0.5 * h * (1.0 + np.tanh(0.7978845608 * (h + 0.044715 * h ** 3)))
                h = h @ Wt[2] + Wt[3]; h = 0.5 * h * (1.0 + np.tanh(0.7978845608 * (h + 0.044715 * h ** 3)))
                p = float(h @ Wt[4][:, 0] + Wt[5][0])
            else:
                p = float(beta[0] + zz @ beta[1:])
        res[kind] = (time.perf_counter() - t0) / len(xs) * 1e6
    print("per-row inference, pure numpy, trailing normalisation included: MLP %s %.1f us, ridge %.1f us (budget 300 us)" % (name, res["mlp"], res["ridge"]))
    json.dump(res, open(os.path.join(OUT, "timing.json"), "w"))


def main():
    for d in (OUT, CACHE, MODELS, EVAL):
        os.makedirs(d, exist_ok=True)
    mode = sys.argv[1]
    if mode == "cache":
        i, n = map(int, sys.argv[2].split("/"))
        for k, (gdir, slot) in enumerate(all_slots()):
            if k % n == i:
                do_cache(gdir, slot)
                print("cache", slot, flush=True)
        print("PX9_CACHE_DONE", flush=True)
    elif mode == "ridge":
        do_ridge()
    elif mode == "mlp":
        do_mlp(sys.argv[2])
    elif mode == "eval":
        do_eval(sys.argv[2])
    elif mode == "report":
        do_report()
    elif mode == "timing":
        do_timing(*sys.argv[2:])


if __name__ == "__main__":
    main()
