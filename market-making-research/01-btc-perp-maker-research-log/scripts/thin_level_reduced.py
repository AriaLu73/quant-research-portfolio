"""精简特征版薄档存活 logistic(便于策略实现):10 个引擎内可实时计算的特征;LODO AUC;保存系数供 sim 与引擎共用。"""
import sys, os, json, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); import thin_level_survival as T
ROOT = T.ROOT
RED = ["vol_10000ms", "ret_1000ms", "qdepl_b_200ms", "q", "ofi_1000ms", "imb5", "tcluster_100ms", "form_toward", "tint_1000ms", "depth_chg_1s"]
days = ["20251001", "20260101", "20260401"]
D = pd.concat([T.build(d) for d in days], ignore_index=True)
D = D[D["hit"] | D["grew"]].reset_index(drop=True); y = D["grew"].astype(int).values
X = D[RED].replace([np.inf, -np.inf], np.nan).fillna(0.0).values.astype(np.float64)
lo = np.percentile(X, 1, axis=0); hi = np.percentile(X, 99, axis=0); X = np.clip(X, lo, hi)
mu = X.mean(0); sd = X.std(0) + 1e-9; Xs = (X - mu) / sd
print("events", len(D), "grew rate", round(y.mean(), 3))
for d in days:
    tr = D["day"].values != d; te = ~tr
    w = T.logit_fit(Xs[tr], y[tr]); s = np.c_[np.ones(te.sum()), Xs[te]] @ w
    for pct in (70, 85, 95):
        top = s >= np.percentile(s, pct)
        print(f"  LODO {d}: AUC {T.auc(y[te], s):.3f}  top{100-pct}%: grew {y[te][top].mean():.3f} (base {y[te].mean():.3f}) mk5_now {D.loc[te,'mk5_now'].values[top].mean():+.3f} (all {D.loc[te,'mk5_now'].mean():+.3f}) n {top.sum()}")
w = T.logit_fit(Xs, y)
s_all = np.c_[np.ones(len(Xs)), Xs] @ w
coef = {"features": RED, "lo": lo.tolist(), "hi": hi.tolist(), "mu": mu.tolist(), "sd": sd.tolist(), "w": w[1:].tolist(), "intercept": float(w[0]),
        "score_pct": {str(p): float(np.percentile(s_all, p)) for p in (50, 60, 70, 80, 85, 90, 95)}}
json.dump(coef, open(os.path.join(ROOT, "data", "research", "thin_level_logit_reduced.json"), "w"), indent=1)
print("coef:", dict(zip(RED, np.round(w[1:], 3))), "intercept", round(w[0], 3)); print("score pct:", coef["score_pct"])
