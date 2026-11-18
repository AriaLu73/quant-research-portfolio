#!/usr/bin/env python3
"""薄档存活预测(下一假设 H1):新形成/薄的最优档(公开量 ≤ q_thin)在接下来 h 秒内是"被扫"还是"长大"?

事件:bb 变到新价位 P 或 bq1 从 >q_thin 降到 ≤q_thin(卖侧对称)。
标签:swept = 未来 horizon_ms 内出现 ≤P 的卖方主动成交(bid 侧)且价位在该成交后消失/下移;
      grew  = horizon_ms 内无卖方成交打到 P,且 t+grow_ms 时 bb==P 且 bq1 ≥ q_big。
特征:事件时刻因子(imb5、imb1、ofi、tflow、tint、t_since_trade、vol、ret、cancel_imb、qdepl、对侧量、深档量、价位形成方式)。
模型:Logistic(复杂度阶梯 Rule → Linear → Logistic),按日 leave-one-day-out 评估 AUC;输出系数供策略冻结使用。
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KU = os.path.join(ROOT, "data", "research", "kucoin")
FOUT = os.path.join(ROOT, "data", "research", "factors")
US = 1000
FEATS = ["imb5", "imb1", "imb2", "ofi_100ms", "ofi_500ms", "ofi_1000ms", "tflow_1000ms", "tflow_5000ms", "timb_5000ms",
         "tint_1000ms", "tcluster_100ms", "t_since_trade_ms", "vol_10000ms", "ret_1000ms", "ret_5000ms", "accel_1s",
         "cancel_imb_2000ms", "qdepl_b_200ms", "qdepl_a_200ms", "depth_conc_b", "depth_conc_a", "slope_imb", "spread_chg_1s", "depth_chg_1s"]


def build(day, q_thin=0.1, horizon_ms=500, grow_ms=2000, q_big=0.6):
    F = pq.read_table(os.path.join(FOUT, f"{day}.parquet")).to_pandas()
    tr = pq.read_table(os.path.join(KU, f"trades_{day}.parquet")).to_pandas()
    ts = F["ts"].values.astype(np.int64); n = len(ts)
    out = []
    for side, pxc, qc, oqc, sgn in (("bid", "bb", "bq1", "aq1", -1), ("ask", "ba", "aq1", "bq1", 1)):
        px = F[pxc].values.astype(np.float64); q = F[qc].values.astype(np.float64); oq = F[oqc].values.astype(np.float64)
        valid = F["valid"].values
        newpx = np.r_[False, px[1:] != px[:-1]]
        thin_now = q <= q_thin
        became_thin = np.r_[False, (q[1:] <= q_thin) & (q[:-1] > q_thin) & (px[1:] == px[:-1])]
        ev = np.nonzero(valid & thin_now & (newpx | became_thin))[0]
        ev = ev[(ts[ev] > ts[0] + 60_000_000) & (ts[ev] < ts[-1] - 60_000_000)]
        # 价位形成方式:up-tick(新 bb 高于旧 bb)= 价格向本侧移动;down = 本侧被吃后退到新档
        prev_px = np.r_[px[0], px[:-1]]
        form_toward = np.where(newpx[ev], (px[ev] > prev_px[ev]) if side == "bid" else (px[ev] < prev_px[ev]), False)
        # 同侧主动成交(打本侧的)时间与价格
        tts = tr["ts"].values.astype(np.int64); tpx = tr["price"].values; tside = tr["side"].values
        m = tside == sgn
        ats = tts[m]; apx = tpx[m]
        j0 = np.searchsorted(ats, ts[ev], side="right"); j1 = np.searchsorted(ats, ts[ev] + horizon_ms * US, side="right")
        hit = np.zeros(len(ev), dtype=bool)
        for k in range(len(ev)):
            if j1[k] > j0[k]:
                seg = apx[j0[k]:j1[k]]
                hit[k] = np.any(seg <= px[ev[k]] + 1e-9) if side == "bid" else np.any(seg >= px[ev[k]] - 1e-9)
        kg = np.minimum(np.searchsorted(ts, ts[ev] + grow_ms * US, side="left"), n - 1)
        grew = (~hit) & (px[kg] == px[ev]) & (q[kg] >= q_big)
        # 长大后首笔打入该档的成交 markout(5s)
        kk5 = np.minimum(np.searchsorted(ts, ts[ev] + 5000 * US, side="left"), n - 1)
        mid = F["mid"].values.astype(np.float64)
        mk5_if_hit_now = (-sgn) * (mid[kk5] - px[ev]) / px[ev] * 1e4      # 假设事件时刻立刻成交的 markout
        df = pd.DataFrame({"day": day, "side": side, "row": ev, "ts": ts[ev], "px": px[ev], "q": q[ev], "q_opp": oq[ev],
                           "form_toward": form_toward.astype(float), "hit": hit, "grew": grew, "mk5_now": mk5_if_hit_now})
        for c in FEATS:
            v = F[c].values[ev].astype(np.float64)
            # 对齐:本侧有利为正
            if c in ("imb5", "imb1", "imb2", "ofi_100ms", "ofi_500ms", "ofi_1000ms", "tflow_1000ms", "tflow_5000ms", "timb_5000ms",
                     "ret_1000ms", "ret_5000ms", "accel_1s", "cancel_imb_2000ms", "slope_imb"):
                v = v * (1.0 if side == "bid" else -1.0)
            if c == "qdepl_b_200ms":
                v = (F["qdepl_b_200ms"].values[ev] if side == "bid" else F["qdepl_a_200ms"].values[ev]).astype(np.float64)
            if c == "qdepl_a_200ms":
                v = (F["qdepl_a_200ms"].values[ev] if side == "bid" else F["qdepl_b_200ms"].values[ev]).astype(np.float64)
            if c == "depth_conc_b":
                v = (F["depth_conc_b"].values[ev] if side == "bid" else F["depth_conc_a"].values[ev]).astype(np.float64)
            if c == "depth_conc_a":
                v = (F["depth_conc_a"].values[ev] if side == "bid" else F["depth_conc_b"].values[ev]).astype(np.float64)
            df[c] = v
        out.append(df)
    return pd.concat(out, ignore_index=True)


def logit_fit(X, y, l2=1.0, iters=300):
    """简单 L2 正则 logistic(牛顿法),特征已标准化。"""
    n, d = X.shape
    Xb = np.c_[np.ones(n), X]
    w = np.zeros(d + 1)
    for _ in range(iters):
        z = Xb @ w; p = 1 / (1 + np.exp(-z))
        g = Xb.T @ (p - y) + l2 * np.r_[0, w[1:]]
        W = p * (1 - p)
        H = (Xb * W[:, None]).T @ Xb + l2 * np.eye(d + 1); H[0, 0] -= l2
        step = np.linalg.solve(H, g)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w


def auc(y, s):
    order = np.argsort(s); r = np.empty(len(s)); r[order] = np.arange(1, len(s) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0) if n1 and n0 else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="20251001,20260101,20260401")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "research", "thin_level_survival.md"))
    ns = ap.parse_args()
    days = ns.days.split(",")
    D = pd.concat([build(d) for d in days], ignore_index=True)
    D["y"] = D["grew"].astype(int)
    D = D[D["hit"] | D["grew"]].reset_index(drop=True)          # 只保留可判定事件
    feats = FEATS + ["q", "q_opp", "form_toward"]
    X = D[feats].replace([np.inf, -np.inf], np.nan).fillna(0.0).values.astype(np.float64)
    X = np.clip(X, np.percentile(X, 1, axis=0), np.percentile(X, 99, axis=0))
    mu = X.mean(0); sd = X.std(0) + 1e-9
    Xs = (X - mu) / sd
    y = D["y"].values
    L = ["# 薄档存活预测(Thin-level survival)", "",
         f"事件 {len(D):,}(训练日 {', '.join(days)});grew 占比 {y.mean():.3f};swept 占比 {1 - y.mean():.3f}", ""]
    # 单特征 AUC
    L += ["## 单特征 AUC(>0.5 = 值大更可能长大)", "", "| feature | AUC | mean|grew | mean|swept |", "|---|---|---|---|"]
    rows = []
    for i, c in enumerate(feats):
        a = auc(y, Xs[:, i]); rows.append((c, a, X[y == 1, i].mean(), X[y == 0, i].mean()))
    for c, a, m1, m0 in sorted(rows, key=lambda r: -abs(r[1] - 0.5)):
        L.append(f"| {c} | {a:.3f} | {m1:+.3f} | {m0:+.3f} |")
    # leave-one-day-out logistic
    L += ["", "## Logistic(L2)leave-one-day-out", "", "| test day | n | AUC | 预测 top30% 的 grew 率 | 全体 grew 率 | top30% 事件若立刻成交的 mk5 | 全体 |", "|---|---|---|---|---|---|---|"]
    for d in days:
        tr_m = D["day"].values != d; te_m = ~tr_m
        w = logit_fit(Xs[tr_m], y[tr_m])
        s = np.c_[np.ones(te_m.sum()), Xs[te_m]] @ w
        thr = np.percentile(s, 70)
        top = s >= thr
        L.append(f"| {d} | {te_m.sum():,} | {auc(y[te_m], s):.3f} | {y[te_m][top].mean():.3f} | {y[te_m].mean():.3f} | {D.loc[te_m, 'mk5_now'].values[top].mean():+.3f} | {D.loc[te_m, 'mk5_now'].mean():+.3f} |")
    w = logit_fit(Xs, y)
    coef = {"intercept": float(w[0]), "features": feats, "mu": mu.tolist(), "sd": sd.tolist(), "w": w[1:].tolist()}
    json.dump(coef, open(os.path.join(ROOT, "data", "research", "thin_level_logit.json"), "w"), indent=1)
    L += ["", "## 全样本系数(标准化后)", "", "| feature | w |", "|---|---|"] + [f"| {c} | {v:+.3f} |" for c, v in sorted(zip(feats, w[1:]), key=lambda t: -abs(t[1]))]
    open(ns.out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
