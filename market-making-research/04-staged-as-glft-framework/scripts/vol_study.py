#!/usr/bin/env python3
"""research7 研究五(波动率)的离线估计:估计口径、日内规律、预测模型比较、跳跃占比。不含任何策略回放。

用途      回答:用什么口径量波动;日内有没有稳定的规律;哪种预测在样本外比常数 σ 好、好多少。
所属阶段  阶段 2,研究五。
对应公式  产出 σ_t,替换报价公式中的常数 σ(同时进入保留价的库存项与价差的风险补偿项)。
变量与 <符号表> 的对应
          r      对数收益(bp);v = σ² 方差(bp² / 秒);h 预测的未来 H 秒方差(bp²);rv 实际的未来 H 秒已实现方差(bp²)
          H      预测期(秒);s[小时] 日内乘性因子(均值 1)
依据      M-201 EWMA(L27 式 3.2)、M-202 日内因子(L28 式 7、附录 B)、M-203 HAR 结构(L23 式 8;日内窗口无理论依据)、
          M-204 GARCH(1,1)(L24 式 1–2、定理 1)、M-205 QLIKE(L29 式 6)、M-206 Diebold–Mariano(L30 §1.1)、
          M-207 两尺度估计量(L07 §1.2)、M-208 双幂次变差(L25,作者稿式 3、21–22)。
预登记    docs/research7/00_范围_阈值_预登记.md 第 7 节(下面的常数都来自那张表)。
用法      Python314/python.exe scripts/research7/vol_study.py
"""
import math
import os
import sys

import numpy as np
from scipy.optimize import minimize

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GRID = os.path.join(ROOT, "data", "research7", "vol")
TRAIN = ("20260826", "20260827", "20260828", "20260829", "20260830", "20260831", "20260901", "20260902", "20260903",
         "20260904", "20260905", "20260906", "20260907")
VALID = ("20260910", "20260911", "20260914", "20260917", "20260918", "20260923", "20260924")
OCT = ("20261001", "20261002")
STEP_S = 0.1                                   # 网格间隔(秒):vol_grid.py
GAP_S = 5.0                                    # 报价超过这么久未变视为空档(与 calib.GAP_S 相同)
SIG_STEPS = (1, 2, 5, 10, 20, 50, 100, 300, 600, 3000)   # 签名图的采样间隔(单位:网格点;= 0.1 … 300 秒)
HALF_LIVES = (10, 30, 60, 120, 300, 600, 1800, 3600)     # EWMA 半衰期候选(秒):预登记
HORIZONS = (10, 60, 300)                       # 预测期 H(秒):预登记;模型选择以 60 为准
H_SELECT = 60
HAR_WINDOWS = (60, 600, 3600)                  # HAR 型回归的三个回看窗口(秒):预登记(无理论依据,仅比较)
GARCH_STEP = 10                                # GARCH 用的收益间隔(秒):预登记
DM_LAG = 5                                     # Diebold–Mariano 长期方差的 Bartlett 窗滞后(块):预登记,ASSUMPTION
FLAT_TOL = 0.03                                # 签名图"变平"的判据:相邻间隔相差 < 3%:预登记,ASSUMPTION
OUT = os.path.join(GRID, "vol_study_report.txt")
LINES = []


def P(s=""):
    LINES.append(s)
    print(s, flush=True)


def load(day):
    """读一天的网格 → (t0 纳秒, log 中间价, log 加权中间价, 是否可用)。可用 = 报价没有超过 GAP_S 秒不变。"""
    z = np.load(os.path.join(GRID, f"grid_{day}.npz"))
    return int(z["t0"]), np.log(z["mid"].astype(np.float64)), np.log(z["micro"].astype(np.float64)), z["age"] < GAP_S


def rv_at_step(lp, ok, k):
    """采样间隔 k 个网格点时的平均已实现波动(bp / √秒)。只用两端都可用的区间;不重叠采样。"""
    x, o = lp[::k], ok[::k]
    r = np.diff(x) * 1e4
    m = o[1:] & o[:-1]
    return math.sqrt(np.sum(r[m] ** 2) / (m.sum() * k * STEP_S)) if m.sum() > 10 else float("nan")


def tsrv(lp, ok, K):
    """两尺度已实现方差(L07 §1.2):慢尺度(间隔 K 点)的子样本平均,减去由最快尺度估出的噪声偏差。
    [Y,Y]^(avg) − (n̄ / n)·[Y,Y]^(all),n̄ = (n − K + 1) / K。返回 bp / √秒。空档处的收益记 0(略微低估,空档占比见 vol_grid 输出)。"""
    r1 = np.where(ok[1:] & ok[:-1], np.diff(lp) * 1e4, 0.0)
    n = len(r1)
    all_ = np.sum(r1 ** 2)
    c = np.r_[0.0, np.cumsum(r1)]
    rk = c[K:] - c[:-K]                                    # 间隔 K 点的全部重叠收益
    avg = np.sum(rk ** 2) / K                              # K 个子网格的平均
    nbar = (n - K + 1) / K
    return math.sqrt(max(avg - nbar / n * all_, 0.0) / (n * STEP_S))


def sec_returns(lp, ok, step_pts):
    """按 step_pts 个网格点取不重叠对数收益(bp)与可用标记。"""
    x, o = lp[::step_pts], ok[::step_pts]
    return np.diff(x) * 1e4, o[1:] & o[:-1]


def ewma(r2, ok, hl, v0):
    """EWMA 方差(L27 式 3.2 的递推,按 L26 式 [5.3] 的时间下标:v[t] 只用到第 t 个及以前的收益)。
    r2: 每秒收益平方(bp²);不可用的秒保持上一个值;hl: 半衰期(秒);v0: 初值(bp²/秒)。返回 v[t](bp²/秒)。"""
    lam = 0.5 ** (1.0 / hl)
    v = np.empty(len(r2))
    cur = v0
    for i in range(len(r2)):
        if ok[i]:
            cur = lam * cur + (1.0 - lam) * r2[i]
        v[i] = cur
    return v


def qlike(h, rv):
    """QLIKE 损失(L29 式 6):L = log h + rv / h,逐块。"""
    return np.log(h) + rv / h


def dm(l1, l2):
    """Diebold–Mariano 统计量(L30 §1.1):d = l1 − l2;S = d̄ / sqrt(长期方差 / T),Bartlett 窗滞后 DM_LAG。
    S < 0 表示模型 1 的损失更低。"""
    d = l1 - l2
    d = d[np.isfinite(d)]
    T = len(d)
    e = d - d.mean()
    lr = float(e @ e) / T
    for j in range(1, DM_LAG + 1):
        lr += 2.0 * (1.0 - j / (DM_LAG + 1.0)) * float(e[j:] @ e[:-j]) / T
    return d.mean() / math.sqrt(max(lr, 1e-300) / T)


def blocks(day, H, unit_s):
    """把一天切成不重叠的 H 秒块。返回每块:起点的秒下标 i(预测在第 i 秒末做出,只用 ≤ i 的数据)、
    块内已实现方差 rv(bp²,用 unit_s 秒收益的平方和)、块是否可用(块内每个收益都可用)、起点所在 UTC 小时。"""
    t0, lp, _, ok = load(day)
    k = int(round(unit_s / STEP_S))
    r, o = sec_returns(lp, ok, k)
    n = len(r) // int(H / unit_s) * int(H / unit_s)
    m = int(H / unit_s)
    rv = (r[:n] ** 2).reshape(-1, m).sum(1)
    good = o[:n].reshape(-1, m).all(1)
    start_s = np.arange(0, n, m) * unit_s                   # 块起点(距 t0 的秒数)
    hour = ((t0 / 1e9 + start_s) // 3600 % 24).astype(int)
    return start_s, rv, good, hour


def main():
    P("研究五(波动率)离线估计 —— XBTUSDTM,22 天 100 毫秒网格(L2 重建);训练 08-26…09-07,验证 09-10…09-24,10 月两天")
    # ------------------------------------------------------------------ 1. 估计口径:签名图与两尺度估计
    P("\n[1] 不同采样间隔下的平均已实现波动(bp / √秒;签名图,描述)")
    P("    间隔(秒)      " + "".join(f"{k * STEP_S:>8g}" for k in SIG_STEPS) + "   两尺度 K=1s / 5s / 10s")
    sig = {}
    for seg, days in (("训练", TRAIN), ("验证", VALID), ("10 月", OCT)):
        for name, col in (("中间价", 1), ("加权中间价", 2)):
            rows, ts_ = [], []
            for d in days:
                z = load(d)
                rows.append([rv_at_step(z[col], z[3], k) for k in SIG_STEPS])
                ts_.append([tsrv(z[col], z[3], K) for K in (10, 50, 100)])
            a = np.sqrt(np.nanmean(np.square(rows), axis=0))
            b = np.sqrt(np.nanmean(np.square(ts_), axis=0))
            sig[(seg, name)] = a
            P(f"    {seg} {name:<6}" + "".join(f"{x:8.3f}" for x in a) + "   " + " / ".join(f"{x:.3f}" for x in b))
    a = sig[("训练", "中间价")]
    flat = next((i for i in range(len(a) - 1) if abs(a[i + 1] / a[i] - 1) < FLAT_TOL), len(a) - 1)
    unit_s = SIG_STEPS[flat] * STEP_S
    P(f"    判据(相邻间隔相差 < {FLAT_TOL:.0%}):训练段中间价的签名图从 {unit_s:g} 秒起变平 → 已实现方差代理用 {unit_s:g} 秒收益")
    unit_s = max(unit_s, 1.0)                                # 预测模型按秒递推,代理的间隔不小于 1 秒
    P(f"    (预测与代理统一用 {unit_s:g} 秒收益)")

    # ------------------------------------------------------------------ 2. 日内规律
    P("\n[2] 日内乘性因子 s(UTC 小时),均值 1(L28):训练段估计;验证段、10 月各自估计一遍只为比较稳定性")
    def season(days):
        tot, cnt = np.zeros(24), np.zeros(24)
        for d in days:
            _, rv, good, hour = blocks(d, 60, unit_s)
            np.add.at(tot, hour[good], rv[good]); np.add.at(cnt, hour[good], 1)
        s = tot / np.maximum(cnt, 1)
        return s / s[cnt > 0].mean(), cnt
    s_tr, _ = season(TRAIN)
    s_va, _ = season(VALID)
    P("    小时   " + "".join(f"{h:6d}" for h in range(24)))
    P("    训练   " + "".join(f"{x:6.2f}" for x in s_tr))
    P("    验证   " + "".join(f"{x:6.2f}" for x in s_va))
    P(f"    训练与验证两组因子的相关系数 {np.corrcoef(s_tr, s_va)[0, 1]:+.2f};训练段因子 最小 {s_tr.min():.2f} 最大 {s_tr.max():.2f};"
      f"按每天分别估计的因子与训练段因子的相关系数:" + " ".join(f"{np.corrcoef(s_tr, season((d,))[0])[0, 1]:+.2f}" for d in VALID))

    # ------------------------------------------------------------------ 3. 预测模型
    # 每天的秒级序列
    def day_series(d):
        t0, lp, _, ok = load(d)
        r, o = sec_returns(lp, ok, int(round(unit_s / STEP_S)))
        hour = ((t0 / 1e9 + np.arange(len(r)) * unit_s) // 3600 % 24).astype(int)
        return r, o, hour
    S = {d: day_series(d) for d in TRAIN + VALID + OCT}
    v_const = float(np.mean(np.concatenate([S[d][0][S[d][1]] ** 2 for d in TRAIN])) / unit_s)     # 常数方差(bp²/秒):训练段
    P(f"\n[3] 预测比较。常数 σ(训练段)= {math.sqrt(v_const):.3f} bp/√秒")

    def forecasts(d, H, hl):
        """一天内每个 H 秒块起点处的各模型预测(bp²)与实际 rv。预测只用块起点之前的数据。"""
        r, o, hour = S[d]
        m = int(H / unit_s)
        n = len(r) // m * m
        rv = (r[:n] ** 2).reshape(-1, m).sum(1)
        good = o[:n].reshape(-1, m).all(1)
        idx = np.arange(0, n, m)                              # 块起点下标;用到的最后一个收益是 idx − 1
        hb = hour[idx]
        r2 = r ** 2 / unit_s
        v = ewma(r2, o, hl / unit_s, v_const)
        f_ewma = np.r_[v_const, v][idx] * H                   # v[idx − 1]
        v_ds = ewma(r2 / s_tr[hour], o, hl / unit_s, v_const)
        f_seas = np.r_[v_const, v_ds][idx] * s_tr[hb] * H
        # HAR 型:过去三个窗口的已实现波动(开方),只用块起点之前的收益
        c = np.r_[0.0, np.cumsum(np.where(o, r ** 2, 0.0))]
        X = [np.sqrt(np.maximum(c[idx] - c[np.maximum(idx - int(w / unit_s), 0)], 0.0) / w) for w in HAR_WINDOWS]
        warm = idx >= int(HAR_WINDOWS[-1] / unit_s)
        return dict(rv=rv, good=good & warm & (rv > 0), ewma=f_ewma, seas=f_seas, X=np.c_[np.ones(len(idx)), np.array(X).T], const=np.full(len(idx), v_const * H))

    def garch_fit():
        """GARCH(1,1)(L24 式 1–2):h_t = a0 + a1·ε²_{t−1} + b1·h_{t−1},10 秒收益,训练段极大似然(高斯)。"""
        k = int(GARCH_STEP / unit_s)
        rs = []
        for d in TRAIN:
            r, o, _ = S[d]
            n = len(r) // k * k
            x = r[:n].reshape(-1, k).sum(1)
            rs.append(x[o[:n].reshape(-1, k).all(1)])
        e = np.concatenate(rs)
        var = e.var()

        def nll(p):
            a1, b1 = 1 / (1 + math.exp(-p[0])) * 0.5, 1 / (1 + math.exp(-p[1]))
            if a1 + b1 >= 0.9999:
                return 1e18
            a0 = var * (1 - a1 - b1)
            h, s = var, 0.0
            for x in e:
                s += math.log(h) + x * x / h
                h = a0 + a1 * x * x + b1 * h
            return s
        best = min((minimize(nll, x0, method="Nelder-Mead", options=dict(maxiter=200, xatol=1e-3, fatol=1e-2)) for x0 in ((-2.0, 3.0), (-1.0, 2.0))), key=lambda z: z.fun)
        a1, b1 = 1 / (1 + math.exp(-best.x[0])) * 0.5, 1 / (1 + math.exp(-best.x[1]))
        return var * (1 - a1 - b1), a1, b1, var

    def garch_forecast(d, H, par):
        """块起点处对未来 H 秒方差的预测:多步预测之和,E[h_{t+j}] = v̄ + (a1 + b1)^{j−1}·(h_{t+1} − v̄)。"""
        a0, a1, b1, var = par
        r, o, _ = S[d]
        k = int(GARCH_STEP / unit_s)
        n = len(r) // k * k
        x = np.where(o[:n].reshape(-1, k).all(1), r[:n].reshape(-1, k).sum(1), 0.0)
        h = np.empty(len(x) + 1)
        h[0] = var
        for i in range(len(x)):
            h[i + 1] = a0 + a1 * x[i] ** 2 + b1 * h[i] if x[i] != 0.0 else h[i]
        m = int(H / GARCH_STEP)
        nb = len(x) // m
        h1 = h[np.arange(nb) * m]                              # 块起点处的下一步条件方差(只用起点之前的收益)
        p = a1 + b1
        geo = (1 - p ** m) / (1 - p)
        return m * var + (h1 - var) * geo

    P("    EWMA 半衰期的选择(只在训练段内:前 9 天递推、后 4 天算 QLIKE;H = 60 秒)")
    sel = {}
    for hl in HALF_LIVES:
        ls = []
        for d in TRAIN[9:]:
            f = forecasts(d, H_SELECT, hl)
            ls.append(qlike(f["ewma"][f["good"]], f["rv"][f["good"]]))
        sel[hl] = float(np.mean(np.concatenate(ls)))
    P("      " + "  ".join(f"{hl}s: {sel[hl]:.4f}" for hl in HALF_LIVES))
    hl = min(sel, key=sel.get)
    P(f"      选定半衰期 {hl} 秒")
    # HAR 系数:训练段最小二乘,因变量为未来 H 秒已实现波动(开方),与 L23 式 (8) 用波动而非方差一致
    beta = {}
    for H in HORIZONS:
        Xs, ys = [], []
        for d in TRAIN:
            f = forecasts(d, H, hl)
            Xs.append(f["X"][f["good"]]); ys.append(np.sqrt(f["rv"][f["good"]] / H))
        beta[H] = np.linalg.lstsq(np.vstack(Xs), np.concatenate(ys), rcond=None)[0]
    gpar = garch_fit()
    P(f"      GARCH(1,1)(10 秒收益,训练段):a1 = {gpar[1]:.4f},b1 = {gpar[2]:.4f},a1 + b1 = {gpar[1] + gpar[2]:.4f}(< 1:L24 定理 1 的平稳条件)")
    P(f"      HAR 型系数(H = 60 秒;常数、1 分钟、10 分钟、1 小时):" + " ".join(f"{b:+.3f}" for b in beta[60]))

    names = (("const", "0 常数"), ("ewma", f"1 EWMA({hl}s)"), ("seas", "2 EWMA × 日内因子"), ("har", "3 HAR 型(无理论依据)"), ("garch", "4 GARCH(1,1)"))
    for seg, days in (("验证", VALID), ("10 月", OCT)):
        for H in HORIZONS:
            L = {k: [] for k, _ in names}
            R2 = {k: [[], []] for k, _ in names}
            for d in days:
                f = forecasts(d, H, hl)
                g = f["good"]
                f["har"] = np.maximum(f["X"] @ beta[H], 1e-3) ** 2 * H
                gf = garch_forecast(d, H, gpar)
                f["garch"] = np.r_[gf, np.full(max(len(g) - len(gf), 0), np.nan)][:len(g)]
                g = g & np.isfinite(f["garch"])
                for k, _ in names:
                    L[k].append(qlike(f[k][g], f["rv"][g]))
                    R2[k][0].append(np.sqrt(f[k][g] / H)); R2[k][1].append(np.sqrt(f["rv"][g] / H))
            L = {k: np.concatenate(v) for k, v in L.items()}
            P(f"    {seg}  H = {H:>3d} 秒  块数 {len(L['const']):,}")
            prev = None
            for k, lab in names:
                pr, ac = np.concatenate(R2[k][0]), np.concatenate(R2[k][1])
                line = f"      {lab:<22} QLIKE {L[k].mean():.4f}   预测与实际波动的相关系数 {np.corrcoef(pr, ac)[0, 1]:+.3f}   实际 / 预测 的中位比 {np.median(ac / pr):.2f}"
                if k != "const":
                    line += f"   对常数 DM {dm(L[k], L['const']):+.1f}"
                if prev is not None and k not in ("const", "ewma"):
                    line += f"   对上一步 DM {dm(L[k], L[prev]):+.1f}"
                P(line)
                prev = k if k != "har" else prev               # HAR 无理论依据:不作为下一步的比较基准

    # ------------------------------------------------------------------ 4. 跳跃占比(描述)
    P("\n[4] 已实现方差中不能由双幂次变差解释的占比 1 − BV / RV(L25;噪声下的性质无文献依据,仅描述)")
    for step in (1, 10, 60):
        out = []
        for seg, days in (("训练", TRAIN), ("验证", VALID), ("10 月", OCT)):
            num = den = 0.0
            for d in days:
                r, o, _ = S[d]
                k = int(step / unit_s)
                n = len(r) // k * k
                x = r[:n].reshape(-1, k).sum(1)
                g = o[:n].reshape(-1, k).all(1)
                ok2 = g[1:] & g[:-1]
                bv = (math.pi / 2.0) * np.sum(np.abs(x[1:] * x[:-1])[ok2])       # μ1^{-2} = π/2
                rvv = np.sum((x[1:] ** 2)[ok2])
                num += rvv - bv; den += rvv
            out.append(f"{seg} {num / den:+.1%}")
        P(f"    采样 {step:>2d} 秒: " + "  ".join(out))
    open(OUT, "w", encoding="utf8").write("\n".join(LINES))
    print("VOL_STUDY_DONE", flush=True)


if __name__ == "__main__":
    main()
