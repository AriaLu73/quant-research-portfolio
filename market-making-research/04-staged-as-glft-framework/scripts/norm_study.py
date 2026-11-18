#!/usr/bin/env python3
"""research7 研究六(归一化)的离线估计:同一批逐小时参数,用不同单位表达后哪种最稳定。不含策略回放。

用途      检验预登记第 8 节的两条假设:价格类的量随波动缩放;强度类的量随市场活跃度缩放。
所属阶段  阶段 2,研究六。
对应公式  决定 GLFT 各参数(σ、A、κ)与逆向选择项以什么单位估计和存储;只在生成报价的最后一步换算回价格。
变量与 <符号表> 的对应
          sig = σ(美元/√秒,该小时);A、k = A、κ(该小时,calib.fit_A_k);adv = 被触及后 10 秒的不利变动 −ε(m_h − m_0)(美元,正 = 不利);
          n_tr 每秒吃单笔数;vol 每秒成交张数
依据      逐小时估计沿用 M-102、M-103;时间变换的出处 L32(丙);无量纲组为量纲改写(推导依据,见阶段 2 记录)。
用法      .venv/Scripts/python.exe scripts/research7/norm_study.py
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calib as C

OUT = os.path.join(C.ROOT, "data", "research7", "vol", "norm_study_report.txt")
H_ADV = 10.0            # 不利变动的时间窗(秒):与阶段 1 诊断用的 10 秒 markout 相同(预登记第 5 节)
D_ADV = (0, 1, 2, 3)    # 用最近的四个 δ(0.5–3 美元)的触及合并估计不利变动:它们在阶段 1 里数值相近(−0.87…−1.15 bp),合并以减小逐小时噪声;ASSUMPTION
N_BOOT = 2000           # 自助抽样次数:预登记
MIN_ADV = 30            # 一个小时至少这么多次触及才估计不利变动(与 calib.MIN_HITS 相同)
LINES = []


def P(s=""):
    LINES.append(s)
    print(s, flush=True)


def hour_row(bbo, sw):
    """一个小时块 → 一行估计值;不能拟合时返回 None。"""
    sec, mid = C.good_seconds(bbo)
    sig, n = C.sigma_from_mid(sec, mid)
    if not n or not np.isfinite(sig) or sig <= 0:
        return None
    R = C.touches(bbo, sw)
    if not len(R):
        return None
    lam, cnt = C.lam_hat(R)
    if (cnt >= C.MIN_HITS).sum() < 3:
        return None
    f = C.fit_A_k(lam, cnt, sig)
    r = R[(R[:, 4] == 1) & np.isin(R[:, 2], D_ADV)]
    if len(r) < MIN_ADV:
        return None
    t, m = bbo[:, 0], (bbo[:, 1] + bbo[:, 2]) / 2.0 * C.TICK
    th = r[:, 5].astype(np.int64) + int(H_ADV * C.NS)
    ok = th < t[-1]
    eps = np.where(r[ok, 1] == 0, 1.0, -1.0)
    adv = -float(np.mean(eps * (m[np.searchsorted(t, th[ok], side="right") - 1] - r[ok, 6])))   # 美元,正 = 不利
    dur = (t[-1] - t[0]) / C.NS
    px = float(m.mean())
    return (sig, f["A"], f["k"], adv, len(sw) / dur, sw[:, 2].sum() / dur, px)


def cv(x):
    return float(np.std(x, ddof=1) / np.mean(x))


def boot_diff(a, b, rng):
    """变异系数之差 cv(b) − cv(a) 的自助抽样 95% 区间(成对重抽同一批小时)。"""
    n = len(a)
    d = np.empty(N_BOOT)
    for i in range(N_BOOT):
        j = rng.integers(0, n, n)
        d[i] = cv(b[j]) - cv(a[j])
    return np.percentile(d, (2.5, 97.5))


def main():
    rng = np.random.default_rng(7)                          # 固定种子,结果可复现
    P("研究六(归一化)离线估计 —— XBTUSDTM,逐小时参数在不同单位下的离散程度(变异系数 = 标准差 / 均值)")
    for seg, days in (("训练", C.TRAIN_DAYS), ("验证", C.VALID_DAYS), ("10 月", ("20261001", "20261002"))):
        rows = [hour_row(b, w) for _, b, w in C.load_l2_days(days)]
        n_all = len(rows)
        X = np.array([r for r in rows if r is not None])
        sig, A, k, adv, ntr, vol, px = X.T
        P(f"\n== {seg}:{n_all} 个小时,其中 {len(X)} 个可拟合")
        s60 = sig * math.sqrt(60.0)                         # 该小时 60 秒的价格位移尺度(美元)
        groups = (
            ("1/κ(价差尺度)", [("美元", 1 / k), ("bp", 1 / k / px * 1e4), ("波动单位 1/(κσ√60)", 1 / (k * s60))]),
            ("被触及后 10 秒的不利变动", [("美元", adv), ("bp", adv / px * 1e4), ("波动单位 adv/(σ√10)", adv / (sig * math.sqrt(H_ADV)))]),
            ("A(成交强度)", [("每秒", A), ("每笔吃单 A/n_tr", A / ntr), ("每张成交 A/vol", A / vol)]),
            ("σ(波动)", [("每 √秒", sig), ("每 √笔吃单 σ/√n_tr", sig / np.sqrt(ntr)), ("每 √张成交 σ/√vol", sig / np.sqrt(vol))]),
        )
        for title, items in groups:
            base = items[0][1]
            P(f"   {title}")
            for name, x in items:
                line = f"      {name:<26} 均值 {np.mean(x):10.4g}  变异系数 {cv(x):.3f}"
                if x is not base:
                    lo, hi = boot_diff(base, x, rng)
                    verdict = "显著下降" if hi < 0 else ("显著上升" if lo > 0 else "无显著差别")
                    line += f"   相对第一行之差 {cv(x) - cv(base):+.3f}(95% 区间 {lo:+.3f} … {hi:+.3f})→ {verdict}"
                P(line)
        # 假设 (a) 的直接检验:log κ 对 log σ 的斜率(预言 −1);假设 (b):log A 对 log 吃单率的斜率(预言 +1)
        for nm, y, x, pred in (("log κ 对 log σ", np.log(k), np.log(sig), -1), ("log(不利变动) 对 log σ", np.log(np.maximum(adv, 1e-6)), np.log(sig), 1),
                               ("log A 对 log 每秒吃单笔数", np.log(A), np.log(ntr), 1), ("log σ² 对 log 每秒吃单笔数", 2 * np.log(sig), np.log(ntr), 1),
                               ("log σ² 对 log 每秒成交张数", 2 * np.log(sig), np.log(vol), 1)):
            g = np.isfinite(y) & np.isfinite(x)
            xm, ym = x[g] - x[g].mean(), y[g] - y[g].mean()
            b = float(xm @ ym / (xm @ xm))
            e = ym - b * xm
            se = math.sqrt(float(e @ e) / (g.sum() - 2) / float(xm @ xm))
            P(f"   回归 {nm:<26} 斜率 {b:+.2f}(标准误 {se:.2f};假设预言 {pred:+d})  R² {1 - float(e @ e) / float(ym @ ym):.2f}  n {int(g.sum())}"
              + ("   [不利变动为负的小时 %d 个,取对数时截断]" % int((adv <= 0).sum()) if "不利" in nm else ""))
    open(OUT, "w", encoding="utf8").write("\n".join(LINES))
    print("NORM_STUDY_DONE", flush=True)


if __name__ == "__main__":
    main()
