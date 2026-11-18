#!/usr/bin/env python3
"""research3 PX-3 step 1: the v2 price model (PX-1 features + short windows) fitted on the September L2 10 ms grid.
Pre-registration: docs/research3/px3_short_window_2026-10-03.md.
Training days 08-26 ... 09-07, hours 02 / 08 / 14 / 20; out-of-sample days 09-10 ... 09-24, same hours (IC report only).
Ridge per horizon (200 ms, 1 s, 5 s), lambda by leave-one-day-out on the training days, from per-day sufficient statistics.
Also fitted: the same ridge on the PX-1 features alone, to show what the short windows add.
usage: Python314/python.exe scripts/research3/px3_fit.py
output: data/research3/px/BTC-USDT/ridge_v2.json and px3_fit_report.txt"""
import json, math, os, sys, warnings
import numpy as np, pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_ic as P      # noqa: E402

SYM, SRC = "BTC-USDT", "BTC-USDT-10ms"
HOURS = ("02", "08", "14", "20")
HZ = ("200ms", "1s", "5s")
V2_ONLY = ("ofi1_20ms", "ofi1_50ms", "tflow_50ms", "ret_50ms", "tflow_200ms", "ret_200ms", "tint_100ms")
SKIP = ("vol", "hour", "ok", "t")


def frame(day):
    X = P.day_frame(SYM, day, src=SRC, step_ms=10, min_files=1, hours=HOURS, v2=True)
    return None if X is None else X[X.ok]


def design(X, feats, mu, sd):
    Z = X[feats].to_numpy()
    return np.c_[np.ones(len(Z)), np.clip((Z - mu) / sd, -10, 10)], np.isfinite(Z).all(1)


def fit(stats, feats_idx, days, h):
    """-> (beta over [1] + feats_idx, lambda) by leave-one-day-out squared error."""
    ix = np.r_[0, 1 + np.array(feats_idx)]
    best = None
    for lam in P.LAMBDAS:
        pen = lam * np.eye(len(ix))
        pen[0, 0] = 0
        err = 0.0
        for dv in days:
            A = sum(stats[d][h][0][np.ix_(ix, ix)] for d in days if d != dv) + pen
            b = sum(stats[d][h][1][ix] for d in days if d != dv)
            bt = np.linalg.solve(A, b)
            XtX, Xty, yty = stats[dv][h]
            err += yty - 2 * bt @ Xty[ix] + bt @ XtX[np.ix_(ix, ix)] @ bt
        if best is None or err < best[0]:
            best = (err, lam)
    lam = best[1]
    pen = lam * np.eye(len(ix))
    pen[0, 0] = 0
    return np.linalg.solve(sum(stats[d][h][0][np.ix_(ix, ix)] for d in days) + pen, sum(stats[d][h][1][ix] for d in days)), lam


def main():
    feats, ms = None, {}
    for day in P.TRAIN:                                   # pass 1: standardisation constants
        X = frame(day)
        if X is None:
            continue
        if feats is None:
            feats = [c for c in X.columns if not c.startswith("y_") and c not in SKIP]
        Z = X[feats].to_numpy()
        ms[day] = (np.nanmean(Z, 0), np.nanstd(Z, 0))
        print("stats", day, len(X), flush=True)
    days = sorted(ms)
    mu = np.mean([ms[d][0] for d in days], 0)
    sd = np.mean([ms[d][1] for d in days], 0)
    stats = {}
    for day in days:                                      # pass 2: sufficient statistics with the common standardisation
        X = frame(day)
        D, okz = design(X, feats, mu, sd)
        stats[day] = {}
        for h in HZ:
            y = X["y_" + h].to_numpy()
            m = okz & np.isfinite(y)
            stats[day][h] = (D[m].T @ D[m], D[m].T @ y[m], float(y[m] @ y[m]))
        print("xtx", day, flush=True)
    all_idx = list(range(len(feats)))
    v1_idx = [i for i, f in enumerate(feats) if f not in V2_ONLY]
    model = {}
    for h in HZ:
        b2, l2 = fit(stats, all_idx, days, h)
        b1, l1 = fit(stats, v1_idx, days, h)
        model[h] = dict(beta=b2, lam=l2, beta_v1=b1, lam_v1=l1)
    rows = []
    for part, dl in (("train", days), ("oos", P.OOS)):    # pass 3: IC per hour
        for day in dl:
            X = frame(day)
            if X is None:
                continue
            D, okz = design(X, feats, mu, sd)
            for h in HZ:
                y = X["y_" + h].to_numpy()
                p2 = D @ model[h]["beta"]
                p1 = D[:, np.r_[0, 1 + np.array(v1_idx)]] @ model[h]["beta_v1"]
                for hr in np.unique(X.hour):
                    mm = (X.hour == hr).to_numpy() & okz
                    rows.append(dict(part=part, h=h, model="v2", ric=P.rank_ic(p2[mm], y[mm])[0], pic=P.rank_ic(p2[mm], y[mm])[1]))
                    rows.append(dict(part=part, h=h, model="v1 features", ric=P.rank_ic(p1[mm], y[mm])[0], pic=P.rank_ic(p1[mm], y[mm])[1]))
            print("ic", part, day, flush=True)
    R = P.summarize(rows, ["part", "model", "h"])
    out_dir = os.path.join(P.PX, SYM)
    lines = ["PX-3 v2 model, %s, 10 ms grid, hours %s; train days %d" % (SYM, ",".join(HOURS), len(days)),
             "rank IC per hour (mean, ICIR, t, share of hours positive, Pearson):",
             R[["part", "model", "h", "hours", "ic", "icir", "t", "pos", "pic"]].round(4).to_string(),
             "lambda: %s" % {h: (model[h]["lam"], model[h]["lam_v1"]) for h in HZ},
             "coefficients (standardised):",
             pd.DataFrame({h: model[h]["beta"][1:] for h in HZ}, index=feats).round(4).to_string()]
    rep = "\n".join(lines)
    open(os.path.join(out_dir, "px3_fit_report.txt"), "w", encoding="utf-8").write(rep)
    json.dump({"feats": feats, "mu": mu.tolist(), "sd": sd.tolist(), "beta": {h: model[h]["beta"].tolist() for h in HZ},
               "lambda": {h: model[h]["lam"] for h in HZ}}, open(os.path.join(out_dir, "ridge_v2.json"), "w"))
    print(rep)
    print("PX3_FIT_DONE", flush=True)


if __name__ == "__main__":
    main()
