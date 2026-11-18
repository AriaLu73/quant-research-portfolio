#!/usr/bin/env python3
"""research7 阶段 7(研究七:自适应)的离线部分:σ、A、κ 的逐小时漂移有多持续、估计噪声多大、哪种更新机制的一步预测最好。

用途      回答:哪些参数值得在线更新、用多快的速度更新;给出每个小时"只用此前数据"的参数预测表,供逐步向前回放使用。
所属阶段  阶段 7,研究七(预登记 00_范围_阈值_预登记.md 第 17 节,常数均来自那里)。
对应公式  报价公式的输入 σ、A、κ 的更新规则(γ 不更新)。
变量      sig = σ(美元/√秒)、A(1/秒)、k = κ(1/美元):每个小时各自估计(calib.py 的方法,M-102、M-103)。预测对 log 参数做。
输出      data/research7/adapt/hourly.npz(逐小时原始估计与两半估计)、params_pred.npz(每小时的预测值与护栏标记)、adapt_report.txt
用法      .venv/Scripts/python.exe scripts/research7/adapt_study.py build     (逐小时估计,约十几分钟)
          .venv/Scripts/python.exe scripts/research7/adapt_study.py report
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calib as C

OUT = os.path.join(C.ROOT, "data", "research7", "adapt")
OCT = ("20261001", "20261002")
ALL = C.TRAIN_DAYS + C.VALID_DAYS + OCT
WINDOWS = (3, 6, 12, 24, 72)             # 滚动均值的小时数:预登记
HALF = (1, 3, 6, 12, 24, 72)             # 指数加权半衰期(小时):预登记
DM_LAG = 5                               # Diebold–Mariano 的 Bartlett 窗滞后(小时):与研究五相同,ASSUMPTION
PARS = ("sig", "A", "k")
GUARD_MAX = 0.05                         # 护栏触发占比的可接受上限:预登记第 3 节


def est(bbo, sw):
    """一个时间块 → (σ, A, κ, 是否有效)。有效 = 至少 3 个 δ 的触及次数 ≥ MIN_HITS(同阶段 1)。"""
    if len(bbo) < 1000:
        return (np.nan, np.nan, np.nan, 0)
    sec, mid = C.good_seconds(bbo)
    sig, n = C.sigma_from_mid(sec, mid)
    R = C.touches(bbo, sw)
    if not n or not len(R):
        return (np.nan, np.nan, np.nan, 0)
    lam, cnt = C.lam_hat(R)
    if (cnt >= C.MIN_HITS).sum() < 3:
        return (sig, np.nan, np.nan, 0)
    f = C.fit_A_k(lam, cnt, sig)
    return (sig, f["A"], f["k"], 1)


def build():
    rows = []
    for day in ALL:
        for lab, bbo, sw in C.load_l2_days((day,)):
            h = int(bbo[0, 0] // (3600 * C.NS))
            full = est(bbo, sw)
            tm = (h * 3600 + 1800) * C.NS                         # 小时中点:拆成前后两半各估一次(量估计噪声)
            a = est(bbo[bbo[:, 0] < tm], sw[sw[:, 0] < tm])
            b = est(bbo[bbo[:, 0] >= tm], sw[sw[:, 0] >= tm])
            rows.append((h, int(day), *full, *a, *b))
        print(f"adapt build {day} done", flush=True)
    os.makedirs(OUT, exist_ok=True)
    np.save(os.path.join(OUT, "hourly.npy"), np.asarray(rows, float))
    print("ADAPT_BUILD_DONE", flush=True)


def dm(l1, l2):
    d = l1 - l2
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 10:
        return float("nan")
    e = d - d.mean()
    lr = float(e @ e) / T
    for j in range(1, DM_LAG + 1):
        lr += 2.0 * (1.0 - j / (DM_LAG + 1.0)) * float(e[j:] @ e[:-j]) / T
    return d.mean() / math.sqrt(max(lr, 1e-300) / T)


def report():
    L = []
    P = lambda s="": (L.append(s), print(s, flush=True))
    X = np.load(os.path.join(OUT, "hourly.npy"))
    hour, day = X[:, 0].astype(np.int64), X[:, 1].astype(int)
    seg = np.where(day <= 20260907, 0, np.where(day <= 20260924, 1, 2))      # 0 训练 1 验证 2 十月
    P(f"阶段 7 离线:σ、A、κ 的逐小时漂移与一步预测 —— XBTUSDTM,{len(X)} 个小时(训练 {int((seg == 0).sum())} / 验证 {int((seg == 1).sum())} / 10 月 {int((seg == 2).sum())})")
    pred_out = {"hour": hour}
    for pi, name in enumerate(PARS):
        y = np.log(X[:, 2 + pi])                                    # 整小时估计(log)
        ya, yb = np.log(X[:, 6 + pi]), np.log(X[:, 10 + pi])        # 前半、后半
        ok = np.isfinite(y)
        tr = (seg == 0) & ok
        # ---- 漂移的持续性与估计噪声
        def acorr(lag):
            idx = {h: i for i, h in enumerate(hour)}
            a, b = [], []
            for i, h in enumerate(hour):
                j = idx.get(h - lag)
                if j is not None and ok[i] and ok[j] and seg[i] == 0 and seg[j] == 0:
                    a.append(y[i]); b.append(y[j])
            return np.corrcoef(a, b)[0, 1] if len(a) > 20 else float("nan")
        hv = tr & np.isfinite(ya) & np.isfinite(yb)
        noise_sd = float(np.std((ya - yb)[hv], ddof=1) / 2.0)        # 两半之差的标准差 / 2 ≈ 整小时估计的噪声标准差(两半独立、各占一半信息)
        tot_sd = float(np.std(y[tr], ddof=1))
        P(f"\n== {name}(log):训练段逐小时标准差 {tot_sd:.3f};估计噪声标准差约 {noise_sd:.3f}(两半估计之差 / 2,{int(hv.sum())} 个小时)→ 噪声占方差的 {min(noise_sd ** 2 / tot_sd ** 2, 9.99):.0%};"
          f"自相关 滞后 1 小时 {acorr(1):+.2f} / 24 小时 {acorr(24):+.2f} / 72 小时 {acorr(72):+.2f};可估计的小时占比 {ok.mean():.0%}")
        # ---- 一步预测(只用该小时之前的有效值)
        static = float(np.mean(y[tr]))
        hod = hour % 24
        season = np.array([np.mean(y[tr & (hod == k)]) - static if (tr & (hod == k)).sum() > 3 else 0.0 for k in range(24)])
        preds = {"固定(训练段均值)": np.full(len(y), static)}
        last = np.full(len(y), static)
        hist = []
        for i in range(len(y)):
            if hist:
                last[i] = hist[-1]
            if ok[i]:
                hist.append(y[i])
        preds["上一小时的值"] = last
        for w in WINDOWS:
            p, hist = np.full(len(y), static), []
            for i in range(len(y)):
                if hist:
                    p[i] = np.mean(hist[-w:])
                if ok[i]:
                    hist.append(y[i])
            preds[f"滚动 {w} 小时"] = p
        for hl in HALF:
            lam = 0.5 ** (1.0 / hl)
            p, cur = np.full(len(y), static), static
            p2, cur2 = np.full(len(y), static), 0.0                  # 带日内因子:对去掉因子后的值做指数加权
            for i in range(len(y)):
                p[i], p2[i] = cur, static + cur2 + season[hod[i]]
                if ok[i]:
                    cur = lam * cur + (1 - lam) * y[i]
                    cur2 = lam * cur2 + (1 - lam) * (y[i] - static - season[hod[i]])
            preds[f"指数加权 {hl} 小时"] = p
            preds[f"指数加权 {hl} 小时 × 日内因子"] = p2
        mse = {k: float(np.mean((y[tr] - v[tr]) ** 2)) for k, v in preds.items()}
        best = min((k for k in mse if k != "固定(训练段均值)"), key=mse.get)
        P(f"   训练段内一步预测的均方误差:固定 {mse['固定(训练段均值)']:.4f};上一小时 {mse['上一小时的值']:.4f};"
          + ";".join(f"{k} {mse[k]:.4f}" for k in (f"滚动 {WINDOWS[1]} 小时", f"滚动 {WINDOWS[3]} 小时", f"指数加权 {HALF[1]} 小时", f"指数加权 {HALF[3]} 小时")))
        P(f"   训练段选定:{best}(均方误差 {mse[best]:.4f},相对固定 {mse[best] / mse['固定(训练段均值)'] - 1:+.0%})")
        for sname, sm in (("验证", (seg == 1) & ok), ("10 月", (seg == 2) & ok)):
            e0, e1 = (y[sm] - preds["固定(训练段均值)"][sm]) ** 2, (y[sm] - preds[best][sm]) ** 2
            P(f"   {sname}:均方误差 固定 {e0.mean():.4f} → 选定机制 {e1.mean():.4f}({e1.mean() / e0.mean() - 1:+.0%});Diebold–Mariano {dm(e1, e0):+.1f};"
              f"预测与实际的相关系数 {np.corrcoef(preds[best][sm], y[sm])[0, 1]:+.2f};固定值的偏差(实际 − 固定的均值){np.mean(y[sm] - static):+.3f}")
        # ---- 护栏
        lo, hi = np.quantile(y[tr], (0.01, 0.99))
        dy = np.abs(np.diff(y[tr]))
        step = float(np.quantile(dy[np.isfinite(dy)], 0.99))
        p = preds[best].copy()
        g_bound = (p < lo) | (p > hi)
        p = np.clip(p, lo, hi)
        g_step = np.r_[False, np.abs(np.diff(p)) > step]
        for i in range(1, len(p)):
            if abs(p[i] - p[i - 1]) > step:
                p[i] = p[i - 1] + math.copysign(step, p[i] - p[i - 1])
        # 回退:连续 3 个小时无法估计 → 用固定值
        bad = ~ok
        g_fall = np.zeros(len(p), bool)
        run = 0
        for i in range(len(p)):
            run = run + 1 if bad[i] else 0
            if run >= 3:
                g_fall[min(i + 1, len(p) - 1)] = True
        p[g_fall] = static
        for sname, sm in (("验证", seg == 1), ("10 月", seg == 2)):
            P(f"   护栏触发({sname}):越界 {g_bound[sm].mean():.1%};单步过大 {g_step[sm].mean():.1%};回退到固定值 {g_fall[sm].mean():.1%}"
              f" → {'可接受' if max(g_bound[sm].mean(), g_step[sm].mean(), g_fall[sm].mean()) <= GUARD_MAX else '超过 5%'}")
        pred_out[name] = np.exp(p)
        pred_out[name + "_static"] = np.full(len(p), math.exp(static))
    np.savez(os.path.join(OUT, "params_pred.npz"), **pred_out)
    open(os.path.join(OUT, "adapt_report.txt"), "w", encoding="utf8").write("\n".join(L))
    print("ADAPT_REPORT_DONE", flush=True)


if __name__ == "__main__":
    {"build": build, "report": report}[sys.argv[1]]()
