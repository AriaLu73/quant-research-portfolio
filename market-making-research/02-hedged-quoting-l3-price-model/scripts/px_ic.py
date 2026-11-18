#!/usr/bin/env python3
"""research3 PX-1 steps A-C (pre-registration docs/research3/px_price_model_2026-10-03.md): features from the 100 ms grid
(px_grid.py), single-feature IC (train / out-of-sample, by horizon and regime, with negative controls), ridge model fitted on
the training days and read once on the out-of-sample days, and the economic gate (do the extreme deciles move >= 1 bp?).
Days are processed one at a time; the ridge fit uses per-day sufficient statistics, so memory stays small.
usage: Python314/python.exe scripts/research3/px_ic.py BTC-USDT
output: data/research3/px/<symbol>/ic_report.txt and ic_*.csv"""
import glob, json, math, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PX = os.path.join(ROOT, "data", "research3", "px")
TICK = {"BTC-USDT": 0.1, "ETH-USDT": 0.01}
TRAIN = ("20260826", "20260827", "20260828", "20260829", "20260830", "20260831", "20260901", "20260902", "20260903",
         "20260904", "20260905", "20260906", "20260907")
OOS = ("20260910", "20260911", "20260914", "20260917", "20260918", "20260923", "20260924")
H = {"100ms": 1, "1s": 10, "5s": 50, "10s": 100, "30s": 300}        # horizons in 100 ms steps
NORM = 3000                                                            # 5 minutes of steps
HOUR = 36000
LAMBDAS = (0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0)


def trailing_mean(x, w):
    c = np.cumsum(np.r_[0.0, np.nan_to_num(x)])
    n = np.cumsum(np.r_[0.0, ~np.isnan(x)])
    i = np.arange(1, len(x) + 1)
    lo = np.maximum(i - w, 0)
    s, k = c[i] - c[lo], n[i] - n[lo]
    out = np.where(k > 0, s / np.maximum(k, 1), np.nan)
    return np.r_[np.nan, out[:-1]]                                     # strictly past


def wsum(x, w):
    c = np.cumsum(np.r_[0.0, x])
    i = np.arange(1, len(x) + 1)
    return c[i] - c[np.maximum(i - w, 0)]


def day_frame(sym, day, src=None, step_ms=100, min_files=20, hours=None, v2=False):
    """Features and targets of one day. Windows are defined in time (100 ms, 1 s, 5 s, 30 s; normalisation over 5 minutes),
    so the same model can be evaluated on a finer grid (step_ms = 10 for the L3 grid of px_l3grid.py)."""
    fs = sorted(glob.glob(os.path.join(PX, src or sym, "grid_%s_??.parquet" % day)))
    if hours is not None:
        fs = [f for f in fs if os.path.basename(f)[-10:-8] in hours]
    if len(fs) < min_files:
        return None
    k = 100 // step_ms                                                  # grid steps per 100 ms
    parts = []
    for f in fs:
        g = pd.read_parquet(f)
        for c in ["ofi1", "ofi2", "ofi3", "ofi4", "ofi5", "tv", "tn"]:
            g["d" + c] = np.diff(np.r_[0.0, g[c].to_numpy()])
        g["hour"] = int(os.path.basename(f)[-10:-8])
        parts.append(g)
    g = pd.concat(parts, ignore_index=True).sort_values("t").reset_index(drop=True)
    tick = TICK[sym]
    bb, ba = g.bb.to_numpy(), g.ba.to_numpy()
    spr = np.rint((ba - bb) / tick)
    ok = (~g.crossed.to_numpy()) & (spr >= 1) & (spr <= 50)
    mid = np.where(ok, (bb + ba) / 2, np.nan)
    lm = np.log(pd.Series(mid).ffill().to_numpy())
    qb = np.stack([g["qb%d" % i].to_numpy() for i in range(1, 6)])
    qa = np.stack([g["qa%d" % i].to_numpy() for i in range(1, 6)])
    F = {}
    F["imb1"] = (qb[0] - qa[0]) / (qb[0] + qa[0])
    F["imb5"] = (qb.sum(0) - qa.sum(0)) / (qb.sum(0) + qa.sum(0))
    F["wmid_dev"] = F["imb1"] * spr * tick / 2 / mid * 1e4
    dep1 = trailing_mean((qb[0] + qa[0]) / 2, NORM * k)
    for w, nm in ((1, "100ms"), (10, "1s"), (50, "5s")):
        F["ofi1_" + nm] = wsum(g.dofi1.to_numpy(), w * k) / dep1
    for m in range(2, 6):
        depm = trailing_mean((qb[m - 1] + qa[m - 1]) / 2, NORM * k)
        F["ofi%d_1s" % m] = wsum(g["dofi%d" % m].to_numpy(), 10 * k) / depm
    vstep = trailing_mean(np.abs(g.dtv.to_numpy()), NORM * k) * k                # per 100 ms
    nstep = trailing_mean(g.dtn.to_numpy(), NORM * k) * k
    for w, nm in ((10, "1s"), (50, "5s")):
        F["tflow_" + nm] = wsum(g.dtv.to_numpy(), w * k) / (vstep * w)
    F["tint_1s"] = wsum(g.dtn.to_numpy(), 10 * k) / (nstep * 10)
    r1s = np.r_[np.full(10 * k, np.nan), (lm[10 * k:] - lm[:-10 * k]) * 1e4]
    vol = np.sqrt(trailing_mean(r1s ** 2, NORM * k))
    for w, nm in ((10, "1s"), (50, "5s"), (300, "30s")):
        F["ret_" + nm] = np.r_[np.full(w * k, np.nan), (lm[w * k:] - lm[:-w * k]) * 1e4] / (vol * math.sqrt(w / 10))
    F["spread"] = spr
    if v2:                                                              # PX-3 short windows (need step_ms <= 10)
        for ms in (20, 50):
            F["ofi1_%dms" % ms] = wsum(g.dofi1.to_numpy(), ms * k // 100) / dep1
        for ms in (50, 200):
            F["tflow_%dms" % ms] = wsum(g.dtv.to_numpy(), ms * k // 100) / (vstep * ms / 100)
            w = ms * k // 100
            F["ret_%dms" % ms] = np.r_[np.full(w, np.nan), (lm[w:] - lm[:-w]) * 1e4] / (vol * math.sqrt(ms / 1000))
        F["tint_100ms"] = wsum(g.dtn.to_numpy(), k) / nstep
    X = pd.DataFrame(F)
    for nm, h in (H | ({"200ms": 2} if v2 else {})).items():
        X["y_" + nm] = np.r_[(lm[h * k:] - lm[:-h * k]) * 1e4, np.full(h * k, np.nan)]
    X["vol"] = vol
    X["hour"] = g.hour.to_numpy()
    X["t"] = g.t.to_numpy()
    X["ok"] = ok & np.isfinite(vol)
    X = X.replace([np.inf, -np.inf], np.nan)
    return X


FEATS = None


def rank_ic(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 1000:
        return np.nan, np.nan
    a, b = a[m], b[m]
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1]), float(np.corrcoef(a, b)[0, 1])


def summarize(rows, key):
    d = pd.DataFrame(rows)
    out = []
    for k, g in d.groupby(key):
        v = g.ric.dropna()
        n = len(v)
        out.append(dict(zip(key, k)) | dict(hours=n, ic=v.mean(), ic_sd=v.std(), icir=v.mean() / v.std() if n > 1 else np.nan,
                                            t=v.mean() / v.std() * math.sqrt(n) if n > 1 else np.nan, pos=(v > 0).mean(), pic=g.pic.mean()))
    return pd.DataFrame(out)


def main():
    global FEATS
    sym = sys.argv[1]
    out_dir = os.path.join(PX, sym)
    ic_rows, ctl_rows, reg_rows = [], [], []
    XtX, Xty, yty, nn, means = {}, {}, {}, {}, None
    rng = np.random.default_rng(20261003)
    vol_cut = None
    days = [d for d in TRAIN + OOS]
    stats = {}
    for day in days:
        X = day_frame(sym, day)
        if X is None:
            print("skip", day, flush=True)
            continue
        if FEATS is None:
            FEATS = [c for c in X.columns if not c.startswith("y_") and c not in ("vol", "hour", "ok", "t")]
        part = "train" if day in TRAIN else "oos"
        X = X[X.ok]
        if part == "train":
            stats[day] = X[FEATS].agg(["mean", "std"])
        if vol_cut is None and part == "train":
            vol_cut = list(np.nanquantile(X.vol, [1 / 3, 2 / 3]))
        reg = np.where(X.vol < vol_cut[0], "vol_low", np.where(X.vol < vol_cut[1], "vol_mid", "vol_high"))
        sp1 = np.where(X.spread == 1, "spread1", "spread>1")
        for hr, G in X.groupby("hour"):
            idx = (X.hour == hr).to_numpy()
            for f in FEATS:
                a = G[f].to_numpy()
                for nm in H:
                    y = G["y_" + nm].to_numpy()
                    ric, pic = rank_ic(a, y)
                    ic_rows.append(dict(part=part, day=day, hour=hr, feat=f, h=nm, ric=ric, pic=pic))
                    if nm in ("1s", "10s"):
                        ric_s, pic_s = rank_ic(rng.permutation(a), y)
                        ctl_rows.append(dict(part=part, day=day, hour=hr, feat=f, h=nm, ctl="shuffle", ric=ric_s, pic=pic_s))
                        for rg_name, rg in (("vol", reg[idx]), ("spr", sp1[idx])):
                            for lab in np.unique(rg):
                                mm = rg == lab
                                ric_r, pic_r = rank_ic(a[mm], y[mm])
                                reg_rows.append(dict(part=part, feat=f, h=nm, regime=lab, day=day, hour=hr, ric=ric_r, pic=pic_r))
        # negative control 2: feature one hour earlier against this hour's target (positional shift within the day)
        for f in FEATS:
            a = X[f].to_numpy()
            for nm in ("1s", "10s"):
                y = X["y_" + nm].to_numpy()
                if len(a) > 2 * HOUR:
                    ric_s, pic_s = rank_ic(a[:-HOUR], y[HOUR:])
                    ctl_rows.append(dict(part=part, day=day, hour=-1, feat=f, h=nm, ctl="shift1h", ric=ric_s, pic=pic_s))
        if part == "train":
            Z = X[FEATS].to_numpy()
            mu, sd = np.nanmean(Z, 0), np.nanstd(Z, 0)
            for nm in H:
                y = X["y_" + nm].to_numpy()
                m = np.isfinite(Z).all(1) & np.isfinite(y)
                Zs = np.c_[np.ones(m.sum()), np.clip((Z[m] - mu) / sd, -10, 10)]
                XtX[(day, nm)] = Zs.T @ Zs
                Xty[(day, nm)] = Zs.T @ y[m]
                yty[(day, nm)] = float(y[m] @ y[m])
                nn[(day, nm)] = int(m.sum())
            stats[day] = (mu, sd)
        print(day, part, len(X), flush=True)
    ic = summarize(ic_rows, ["part", "feat", "h"])
    ctl = summarize(ctl_rows, ["part", "ctl", "feat", "h"])
    regt = summarize(reg_rows, ["part", "regime", "feat", "h"])
    ic.to_csv(os.path.join(out_dir, "ic_single.csv"), index=False)
    ctl.to_csv(os.path.join(out_dir, "ic_controls.csv"), index=False)
    regt.to_csv(os.path.join(out_dir, "ic_regime.csv"), index=False)
    # ridge: common standardisation = average of the training days' mean / sd; lambda by leave-one-day-out MSE
    tdays = sorted({d for d, _ in XtX})
    mu = np.mean([stats[d][0] for d in tdays], 0)
    sd = np.mean([stats[d][1] for d in tdays], 0)
    beta, lam_pick = {}, {}
    p = len(FEATS) + 1
    for nm in H:
        best = None
        for lam in LAMBDAS:
            pen = lam * np.eye(p)
            pen[0, 0] = 0
            err = 0.0
            for dv in tdays:
                A = sum(XtX[(d, nm)] for d in tdays if d != dv) + pen
                b = sum(Xty[(d, nm)] for d in tdays if d != dv)
                bt = np.linalg.solve(A, b)
                err += yty[(dv, nm)] - 2 * bt @ Xty[(dv, nm)] + bt @ XtX[(dv, nm)] @ bt
            if best is None or err < best[0]:
                best = (err, lam)
        lam = best[1]
        pen = lam * np.eye(p)
        pen[0, 0] = 0
        beta[nm] = np.linalg.solve(sum(XtX[(d, nm)] for d in tdays) + pen, sum(Xty[(d, nm)] for d in tdays))
        lam_pick[nm] = lam
    # out-of-sample read of the ridge model (each day standardised with the training mu / sd above)
    mrows, dec = [], {nm: [] for nm in H}
    for day in OOS:
        X = day_frame(sym, day)
        if X is None:
            continue
        X = X[X.ok]
        Z = X[FEATS].to_numpy()
        Zs = np.c_[np.ones(len(Z)), np.clip((Z - mu) / sd, -10, 10)]
        for nm in H:
            pred = Zs @ beta[nm]
            y = X["y_" + nm].to_numpy()
            for hr in np.unique(X.hour):
                mm = (X.hour == hr).to_numpy()
                ric, pic = rank_ic(pred[mm], y[mm])
                mrows.append(dict(part="oos", feat="ridge", h=nm, day=day, hour=hr, ric=ric, pic=pic))
            ok = np.isfinite(pred) & np.isfinite(y)
            dec[nm].append(pd.DataFrame(dict(pred=pred[ok], y=y[ok])))
    model = summarize(mrows, ["part", "feat", "h"])
    model.to_csv(os.path.join(out_dir, "ic_model.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 400)
    lines = []
    lines.append("PX-1 %s  features %d  train days %d  oos days %d" % (sym, len(FEATS), len(tdays), len(OOS)))
    for part in ("train", "oos"):
        t = ic[ic.part == part].pivot(index="feat", columns="h", values="ic")[list(H)]
        tt = ic[ic.part == part].pivot(index="feat", columns="h", values="t")[list(H)]
        lines.append("\nA. rank IC (mean over hours), %s:\n%s\n   t-values:\n%s" % (part, t.round(4).to_string(), tt.round(1).to_string()))
    c = ctl.pivot_table(index=["ctl", "feat"], columns=["part", "h"], values="ic")
    lines.append("\nnegative controls (mean rank IC):\n%s" % c.round(4).to_string())
    r = regt[(regt.h == "10s")].pivot_table(index="feat", columns=["part", "regime"], values="ic")
    lines.append("\nrank IC by regime, h = 10 s:\n%s" % r.round(4).to_string())
    lines.append("\nB. ridge (lambda by leave-one-day-out on the training days: %s)" % lam_pick)
    lines.append("coefficients (standardised features):\n%s" % pd.DataFrame({nm: beta[nm][1:] for nm in H}, index=FEATS).round(4).to_string())
    lines.append("out-of-sample IC of the model:\n%s" % model[["h", "hours", "ic", "ic_sd", "icir", "t", "pos", "pic"]].round(4).to_string())
    lines.append("\nC. out-of-sample deciles of the prediction: mean realised return (bp), and the gate (top / bottom decile same sign and |.| >= 1 bp)")
    gate = {}
    for nm in H:
        D = pd.concat(dec[nm])
        D["q"] = pd.qcut(D.pred.rank(method="first"), 10, labels=False)
        tab = D.groupby("q").agg(pred=("pred", "mean"), y=("y", "mean"), n=("y", "size"))
        lines.append("  h %s:\n%s" % (nm, tab.round(3).to_string()))
        lo, hi = tab.loc[0], tab.loc[9]
        gate[nm] = bool(hi.y >= 1.0 and lo.y <= -1.0)
    lines.append("gate (h 5 s and 10 s decide): %s" % gate)
    rep = "\n".join(lines)
    open(os.path.join(out_dir, "ic_report.txt"), "w", encoding="utf-8").write(rep)
    json.dump({"feats": FEATS, "mu": mu.tolist(), "sd": sd.tolist(), "beta": {k: v.tolist() for k, v in beta.items()}, "lambda": lam_pick},
              open(os.path.join(out_dir, "ridge.json"), "w"))
    print(rep)
    print("PX_IC_DONE", flush=True)


if __name__ == "__main__":
    main()
