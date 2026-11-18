#!/usr/bin/env python3
"""research7 研究一(公允价格)的离线估计:参考价比较、短期信号的 IC 与衰减、信号组合。不含策略回放。

用途      回答:用哪个价作起点;哪些信号能预测未来中间价、预测力随预测期怎样衰减;组合后样本外还剩多少;幅度够不够大。
所属阶段  阶段 3,研究一(第 6 步"评估"的离线筛选部分)。
对应公式  F_t = S^ref_t + w_t·α̂_t(h),替换保留价中的 S_t。
变量与 <符号表> 的对应
          mid = S_t(美元);y[h] = (m_{t+h} − m_t) / m_t × 1e4(bp),即要预测的量;alpha = α̂_t(h)(bp)
          imb1 = (qb − qa) / (qb + qa) 买一卖一不平衡;imb5 / imb20 同理用 5 / 20 tick 内深度;
          ofi_w  过去 w 秒的订单流不平衡 / 同期平均 (qb + qa);tfi_w 过去 w 秒 (吃单买 − 吃单卖) / (吃单买 + 吃单卖);
          lead_w 币安过去 w 秒对数收益 − KuCoin 同期对数收益(bp);basis 跨所合成价 − 中间价(bp)
预登记    docs/research7/00_范围_阈值_预登记.md 第 10 节(常数均来自那里)。
没有用未来数据的保证:所有特征只用样本点时刻之前(含)的网格行;币安数据再滞后一个网格点(100 毫秒)。
用法      Python314/python.exe scripts/research7/fair_study.py
"""
import math
import os
import sys

import numpy as np
from scipy.stats import rankdata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FEAT = os.path.join(ROOT, "data", "research7", "feat")
TRAIN = ("20260826", "20260827", "20260828", "20260829", "20260830", "20260831", "20260901", "20260902", "20260903",
         "20260904", "20260905", "20260906", "20260907")
VALID = ("20260910", "20260911", "20260914", "20260917", "20260918", "20260923", "20260924")
OCT = ("20261001", "20261002")
TICK = 0.1                      # 美元 / tick
GRID_PER_S = 10                 # 每秒 10 个网格点(100 毫秒)
HORIZONS = (0.1, 0.5, 1, 5, 10, 30, 60)          # 预测期(秒):预登记
H_MAIN = 10                     # 筛选以 10 秒为准:预登记(ASSUMPTION)
GAP_S = 5.0                     # 盘口超过这么久未变视为空档
BN_LAG = 1                      # 币安数据滞后的网格点数(100 毫秒):预登记,保守口径
BASIS_WIN_S = 300               # 基差中位数窗口(秒):预登记,ASSUMPTION
EWMA_HL_S = 600                 # σ_t 的半衰期(秒):研究五
RIDGE = (0.0, 1e-3, 1e-2, 1e-1, 1.0, 10.0)        # 岭惩罚候选(相对特征方差的倍数):训练段内选
N_BUCKET = 10                   # 微观价格的不平衡分桶数:预登记
OUT = os.path.join(FEAT, "fair_study_report.txt")
LINES = []
SIGS = ("imb1", "imb5", "imb20", "ofi_0.1", "ofi_1", "ofi_10", "tfi_1", "tfi_10", "lead_0.1", "lead_0.5", "lead_1", "lead_5", "basis")


def P(s=""):
    LINES.append(s)
    print(s, flush=True)


def roll_sum(x, w):
    """过去 w 个网格点(含当前)的和;开头不足 w 个时用已有的。"""
    c = np.cumsum(np.r_[0.0, x])
    i = np.arange(1, len(x) + 1)
    return c[i] - c[np.maximum(i - w, 0)]


def load_day(day):
    """读一天 → 每 1 秒一个样本点的特征表(dict of 数组)。"""
    z = np.load(os.path.join(FEAT, f"feat_{day}.npz"))
    g = z["g"].astype(np.int64)
    bb, ba = z["bb"].astype(float), z["ba"].astype(float)
    qb, qa = z["qb"].astype(float), z["qa"].astype(float)
    mid = (bb + ba) / 2.0 * TICK
    n = len(g)
    lm = np.log(mid)
    ok = (z["age"] < GAP_S) & np.r_[True, np.diff(g) == 1]             # 盘口新鲜且网格连续
    F = {}
    F["imb1"] = (qb - qa) / np.maximum(qb + qa, 1.0)
    for d in (5, 20):
        b, a = z[f"db{d}"].astype(float), z[f"da{d}"].astype(float)
        F[f"imb{d}"] = (b - a) / np.maximum(b + a, 1.0)
    depth = np.maximum(roll_sum(qb + qa, 100) / np.minimum(np.arange(1, n + 1), 100), 1.0)   # 过去 10 秒平均买一卖一量(归一化用)
    for w in (0.1, 1, 10):
        F[f"ofi_{w:g}"] = roll_sum(z["ofi"].astype(float), int(w * GRID_PER_S)) / depth
    tb, ts_ = z["tb"].astype(float), z["ts_"].astype(float)
    for w in (1, 10):
        b, s = roll_sum(tb, w * GRID_PER_S), roll_sum(ts_, w * GRID_PER_S)
        F[f"tfi_{w}"] = (b - s) / np.maximum(b + s, 1.0)
    # 币安:对齐到同一网格序号,再滞后 BN_LAG 个点
    bn_ok = np.zeros(n, bool)
    fb = os.path.join(FEAT, f"bn_{day}.npz")
    if os.path.exists(fb):
        zb = np.load(fb)
        j = g - int(zb["g0"]) - BN_LAG
        v = (j >= 0) & (j < len(zb["px"]))
        px = np.full(n, np.nan)
        px[v] = zb["px"][j[v]]
        bn_ok = np.isfinite(px)
        lb = np.log(np.where(bn_ok, px, 1.0))
        for w in (0.1, 0.5, 1, 5):
            k = int(w * GRID_PER_S)
            rb = np.r_[np.zeros(k), lb[k:] - lb[:-k]]
            rk = np.r_[np.zeros(k), lm[k:] - lm[:-k]]
            F[f"lead_{w:g}"] = (rb - rk) * 1e4
        # 基差:KuCoin 中间价 − 币安价 的过去 BASIS_WIN_S 秒中位数(按 1 秒采样后滚动,只用过去)
        d1 = (lm - lb)[::GRID_PER_S]
        med = np.full(len(d1), np.nan)
        for i in range(BASIS_WIN_S, len(d1)):
            med[i] = np.median(d1[i - BASIS_WIN_S:i])
        medg = np.repeat(med, GRID_PER_S)[:n]
        F["basis"] = (lb + medg - lm) * 1e4                                 # 跨所合成价 − 中间价(bp)
    else:
        for k in ("lead_0.1", "lead_0.5", "lead_1", "lead_5", "basis"):
            F[k] = np.full(n, np.nan)
    # σ_t(指数加权,1 秒收益;只用过去)→ 波动状态
    r1 = np.r_[0.0, np.diff(lm[::GRID_PER_S])] * 1e4
    lam, v, cur = 0.5 ** (1.0 / EWMA_HL_S), np.empty(len(r1)), float(np.mean(r1 ** 2))
    for i in range(len(r1)):
        cur = lam * cur + (1 - lam) * r1[i] ** 2
        v[i] = cur
    sig = np.repeat(np.sqrt(v), GRID_PER_S)[:n]
    # 目标:未来 h 秒的中间价变动(bp);要求起点与终点都可用且网格连续
    Y = {}
    for h in HORIZONS:
        k = int(round(h * GRID_PER_S))
        y = np.full(n, np.nan)
        good = ok[:-k] & ok[k:] & (g[k:] - g[:-k] == k)
        y[:-k][good] = ((lm[k:] - lm[:-k]) * 1e4)[good]
        Y[h] = y
    idx = np.arange(0, n, GRID_PER_S)                                       # 每 1 秒一个样本点
    idx = idx[ok[idx]]
    out = {k: v_[idx] for k, v_ in F.items()}
    out.update({f"y_{h:g}": Y[h][idx] for h in HORIZONS})
    out["sig"], out["hour"], out["mid"] = sig[idx], (g[idx] // (3600 * GRID_PER_S)), mid[idx]
    out["wmid_dev"] = ((bb * qa + ba * qb) / np.maximum(qa + qb, 1.0) * TICK - mid)[idx] / mid[idx] * 1e4   # 加权中间价 − 中间价(bp)
    return out


def stack(days):
    D = [load_day(d) for d in days]
    return {k: np.concatenate([d[k] for d in D]) for k in D[0]}


def ic_by_hour(x, y, hour):
    """按小时分组的秩 IC 与皮尔逊 IC 序列 → (秩 IC 均值, 标准差, ICIR, t, 皮尔逊 IC 均值, 小时数)。"""
    m = np.isfinite(x) & np.isfinite(y)
    x, y, hour = x[m], y[m], hour[m]
    rs, ps = [], []
    for h in np.unique(hour):
        k = hour == h
        if k.sum() < 300 or np.std(x[k]) == 0 or np.std(y[k]) == 0:
            continue
        rs.append(np.corrcoef(rankdata(x[k]), rankdata(y[k]))[0, 1])
        ps.append(np.corrcoef(x[k], y[k])[0, 1])
    rs = np.asarray(rs)
    if len(rs) < 3:
        return (float("nan"),) * 5 + (len(rs),)
    sd = rs.std(ddof=1)
    return rs.mean(), sd, rs.mean() / sd, rs.mean() / sd * math.sqrt(len(rs)), float(np.mean(ps)), len(rs)


def main():
    P("研究一(公允价格)离线筛选 —— XBTUSDTM,每 1 秒一个样本点;训练 08-26…09-07,验证 09-10…09-24,10 月两天")
    TR, VA, OC = stack(TRAIN), stack(VALID), stack(OCT)
    P(f"样本点:训练 {len(TR['mid']):,}  验证 {len(VA['mid']):,}  10 月 {len(OC['mid']):,};币安数据可用比例(验证){np.isfinite(VA['lead_1']).mean():.1%}")
    rng = np.random.default_rng(3)

    # ---------------------------------------------------------------- 1. 单信号 IC 及其随预测期的衰减
    P("\n[1] 单信号的秩 IC(按小时分组的均值;验证段样本外)随预测期 h 的衰减")
    P("    信号        " + "".join(f"{h:>8g}s" for h in HORIZONS) + f"   | h = {H_MAIN}s:ICIR / t / 皮尔逊 IC / 小时数 | 训练段 IC | 10 月 IC | 负控 t")
    keep = {}
    for s in SIGS:
        row = [ic_by_hour(VA[s], VA[f"y_{h:g}"], VA["hour"])[0] for h in HORIZONS]
        m, sd, icir, t, pe, nh = ic_by_hour(VA[s], VA[f"y_{H_MAIN}"], VA["hour"])
        tr = ic_by_hour(TR[s], TR[f"y_{H_MAIN}"], TR["hour"])[0]
        oc = ic_by_hour(OC[s], OC[f"y_{H_MAIN}"], OC["hour"])[0]
        # 负控:信号在时间上整体平移半个样本(打乱信号与目标的对应),IC 应当为 0
        xs = np.roll(VA[s], len(VA[s]) // 2)
        nc = ic_by_hour(xs, VA[f"y_{H_MAIN}"], VA["hour"])[3]
        keep[s] = (m, t)
        P(f"    {s:<10}" + "".join(f"{x:>+9.3f}" for x in row) + f"   | {icir:+.2f} / {t:+.1f} / {pe:+.3f} / {nh} | {tr:+.3f} | {oc:+.3f} | {nc:+.1f}")

    # ---------------------------------------------------------------- 2. 按波动状态分组(σ_t 三分位,边界取训练段)
    q = np.nanquantile(TR["sig"], (1 / 3, 2 / 3))
    P(f"\n[2] 验证段、h = {H_MAIN}s 的秩 IC 按波动状态分组(σ_t 三分位边界取训练段:{q[0]:.3f} / {q[1]:.3f} bp/√秒)")
    for s in SIGS:
        st = np.digitize(VA["sig"], q)
        P(f"    {s:<10}" + "  ".join(f"状态{k} {ic_by_hour(np.where(st == k, VA[s], np.nan), VA[f'y_{H_MAIN}'], VA['hour'])[0]:+.3f}" for k in range(3)))

    # ---------------------------------------------------------------- 3. 参考价比较(不含回归模型)
    P(f"\n[3] 参考价对未来中间价的预测:1 − MSE(参考价) / MSE(中间价),验证段;条件均值表只用训练段估计")
    def bucket_alpha(key, h):
        """微观价格式的条件均值:按训练段的不平衡分桶,E[未来 h 秒中间价变动 | 桶](bp)。返回 (桶边界, 桶均值)。"""
        x, y = TR[key], TR[f"y_{h:g}"]
        m = np.isfinite(x) & np.isfinite(y)
        edges = np.quantile(x[m], np.linspace(0, 1, N_BUCKET + 1)[1:-1])
        b = np.digitize(x[m], edges)
        return edges, np.array([y[m][b == i].mean() for i in range(N_BUCKET)])
    for h in (1, 10, 60):
        y = VA[f"y_{h:g}"]
        base = np.nanmean(y ** 2)
        parts = []
        for name, pred in (("加权中间价", VA["wmid_dev"]),
                           ("微观价格(买一卖一不平衡分桶)", None), ("多档深度(5 tick)分桶", None), ("多档深度(20 tick)分桶", None),
                           ("跨所合成价", VA["basis"])):
            if pred is None:
                key = {"微": "imb1", "多档深度(5": "imb5", "多档深度(2": "imb20"}[name[:6] if name.startswith("多") else name[:1]]
                edges, mu = bucket_alpha(key, h)
                pred = mu[np.digitize(VA[key], edges)]
            m = np.isfinite(pred) & np.isfinite(y)
            parts.append(f"{name} {1 - np.mean((y[m] - pred[m]) ** 2) / np.mean(y[m] ** 2):+.4f}")
        P(f"    h = {h:>2d}s(中间价的 MSE {base:.3f} bp²): " + ";".join(parts))
    edges, mu = bucket_alpha("imb1", H_MAIN)
    P(f"    微观价格的调整量(训练段,h = {H_MAIN}s,按买一卖一不平衡十分位,bp): " + " ".join(f"{x:+.2f}" for x in mu))

    # ---------------------------------------------------------------- 4. 组合:岭回归
    P(f"\n[4] 多信号岭回归(目标:未来 {H_MAIN}s 中间价变动,bp;特征按训练段标准差标准化;惩罚在训练段内按时间前后两半选)")
    def design(D, sigs):
        X = np.c_[[D[s] for s in sigs]].T
        return X
    def fit(sigs, lam, X, y):
        A = X.T @ X + lam * len(y) * np.eye(X.shape[1])
        return np.linalg.solve(A, X.T @ y)
    for label, sigs in (("本簿信号", [s for s in SIGS if not s.startswith(("lead", "basis"))]), ("本簿 + 币安", list(SIGS))):
        Xtr, ytr = design(TR, sigs), TR[f"y_{H_MAIN}"]
        m = np.isfinite(Xtr).all(1) & np.isfinite(ytr)
        Xtr, ytr, htr = Xtr[m], ytr[m], TR["hour"][m]
        mu_, sd_ = Xtr.mean(0), Xtr.std(0)
        Z = (Xtr - mu_) / sd_
        half = len(Z) // 2
        best = min(RIDGE, key=lambda l: np.mean((ytr[half:] - Z[half:] @ fit(sigs, l, Z[:half], ytr[:half])) ** 2))
        beta = fit(sigs, best, Z, ytr)
        P(f"    {label}:惩罚 {best:g};标准化系数(bp / 每 1 个标准差): " + "  ".join(f"{s} {b:+.3f}" for s, b in zip(sigs, beta)))
        for seg, D in (("训练", TR), ("验证", VA), ("10 月", OC)):
            X = design(D, sigs)
            y = D[f"y_{H_MAIN}"]
            k = np.isfinite(X).all(1) & np.isfinite(y)
            pred = ((X[k] - mu_) / sd_) @ beta
            ic = ic_by_hour(pred, y[k], D["hour"][k])
            r2 = 1 - np.mean((y[k] - pred) ** 2) / np.mean(y[k] ** 2)
            # 幅度:预测值最极端的两个十分位里,未来 10 秒实际变动(bp)
            lo, hi = np.quantile(pred, (0.1, 0.9))
            lo1, hi1 = np.quantile(pred, (0.01, 0.99))
            line = (f"      {seg}:秩 IC {ic[0]:+.3f}(ICIR {ic[2]:+.2f},t {ic[3]:+.1f},{ic[5]} 小时)样本外 R² {r2:+.4f};"
                    f"预测最低 / 最高 10% 时的实际变动 {y[k][pred <= lo].mean():+.2f} / {y[k][pred >= hi].mean():+.2f} bp;最极端 1%:{y[k][pred <= lo1].mean():+.2f} / {y[k][pred >= hi1].mean():+.2f} bp")
            P(line)
            if seg == "验证":
                # 各预测期下同一组合信号的 IC(衰减)与按波动状态分组、残差方差
                P("        同一预测值对各预测期的秩 IC: " + "  ".join(f"{h:g}s {ic_by_hour(pred, D[f'y_{h:g}'][k], D['hour'][k])[0]:+.3f}" for h in HORIZONS))
                st = np.digitize(D["sig"][k], q)
                res = y[k] - pred
                P("        按波动状态:" + "  ".join(f"状态{j} IC {ic_by_hour(np.where(st == j, pred, np.nan), y[k], D['hour'][k])[0]:+.3f} 残差标准差 {res[st == j].std():.2f} bp(未来 10 秒变动本身 {y[k][st == j].std():.2f})" for j in range(3)))
                P(f"        负控(预测值整体平移半个样本)的秩 IC t = {ic_by_hour(np.roll(pred, len(pred) // 2), y[k], D['hour'][k])[3]:+.1f}")
    open(OUT, "w", encoding="utf8").write("\n".join(LINES))
    print("FAIR_STUDY_DONE", flush=True)


if __name__ == "__main__":
    main()
