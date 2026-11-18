"""Step 10 实验 B —— 非自适应到达模型(P1 §3.2 Table 4/5;策略来自预印本 Capponi–Figueroa-López–Yu 2021):
π^±、π(1,1) 是日内时间的确定性二次函数,在训练窗上用历史数据拟合,不随 MO 历史变化。
拟合(EC-28)  P1 没给拟合方式;本实现:对训练窗全部非缺口区间,以 τ = 当日 UTC 秒数 / 86400 为自变量,
             用最小二乘把指标 1^±(0/1)与 1^+·1^- 回归到 (1, τ, τ²),得 π̂^±(τ)、π̂^{11}(τ);
             评估时截到 [PI_FLOOR, 1−PI_FLOOR],并令 π̂^{11} ≤ min(π̂^+, π̂^-)。变体 π(1,1) ≡ 0 直接置零。
递推  无状态(S = 1、Γ 恒为 0),π 随 k 变:bellman.backward 的 tb 传 callable(k)。
"""
import glob
import os

import numpy as np

import bellman as BM

REPRO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NS = 1_000_000_000


def fit_quadratic(sym, days, dt_ms, tag="base"):
    """返回系数 dict:plus / minus / joint 各 [3](1, τ, τ²)。"""
    X, yp, ym, yj = [], [], [], []
    for d in days:
        z = np.load(os.path.join(REPRO, "data", "step02", sym, tag, f"dt{dt_ms}", f"{d}.npz"))
        ok = ~z["gap"]
        t0 = z["t0"][ok]
        day0 = (t0[0] // (86400 * NS)) * 86400 * NS
        tau = ((t0 - day0) % (86400 * NS)) / (86400 * NS)
        X.append(np.stack([np.ones_like(tau), tau, tau * tau], axis=1))
        yp.append(z["ind_plus"][ok].astype(float))
        ym.append(z["ind_minus"][ok].astype(float))
        yj.append((z["ind_plus"][ok] & z["ind_minus"][ok]).astype(float))
    X = np.concatenate(X)
    out = {}
    for lab, y in (("plus", yp), ("minus", ym), ("joint", yj)):
        y = np.concatenate(y)
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        out[lab] = beta.tolist()
        out[lab + "_mean"] = float(y.mean())
    out["n"] = int(len(X))
    return out


def evaluate(coef, N, dt_ms, pi11_zero=False):
    """测试日网格 k = 0..N 上的 π̂^±_{k+1}、π̂^{11}_{k+1}(用区间 [t_k, t_{k+1}) 起点的 τ)。"""
    tau = (np.arange(N + 1) * dt_ms / 1000.0) / 86400.0
    X = np.stack([np.ones_like(tau), tau, tau * tau], axis=1)
    pp = np.clip(X @ np.asarray(coef["plus"]), BM.PI_FLOOR, 1 - BM.PI_FLOOR)
    pm = np.clip(X @ np.asarray(coef["minus"]), BM.PI_FLOOR, 1 - BM.PI_FLOOR)
    p11 = np.zeros_like(pp) if pi11_zero else np.clip(X @ np.asarray(coef["joint"]), 0.0, np.minimum(pp, pm))
    return pp, pm, p11


def tables_fn(pp, pm, p11):
    G = np.zeros((2, 2, 1), np.int64)
    cache = {}

    def f(k):
        if k not in cache:
            cache[k] = BM.Tables([pp[k]], [pm[k]], [p11[k]], G)
        return cache[k]
    return f
