#!/usr/bin/env python3
"""research7 研究五 / 六的衔接检验:用成交活跃度预测波动,是否比只用过去收益的指数加权更好。离线,不含策略回放。

起因      研究六量到:σ 按"每 √笔吃单"表达时逐小时变异系数从 0.46 降到 0.20(显著),log σ² 对 log 吃单率的斜率 +1.2…+1.3、R² 0.77–0.90。
          即波动的大部分变化可以由成交活跃度解释。于是多了两个候选预测,这里与研究五选定的指数加权(600 秒)比较。
所属阶段  阶段 2(研究五第 3 条的延伸候选;预登记见 00_范围_阈值_预登记.md 第 8b 节)。
对应公式  σ_t(替换常数 σ)。
变量      r 每秒对数收益(bp);n 每秒吃单笔数;v = σ²(bp²/秒)
候选      E1  v_t = EWMA_600s(r²)                                   —— 研究五选定(对照)
          E2  v_t = c · EWMA_hl(n),c = 训练段 mean(r²) / mean(n)      —— 只用活跃度(事件时间下波动为常数;L32 的时钟思想)
          E3  v_t = [EWMA_slow(r²) / EWMA_slow(n)] · EWMA_fast(n)     —— 每笔吃单的方差慢变、活跃度快变
依据      M-209:以成交(量)为时钟,L32(所读为讨论稿,丙:依据未经同行评审);E2、E3 的具体形式是由该思想出发的直接写法,
          半衰期由训练段数据决定。
用法      Python314/python.exe scripts/research7/vol_event_time.py
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vol_study as V

MKT = os.path.join(V.ROOT, "data", "research7", "market_l2")
H = V.H_SELECT                          # 60 秒
FAST = (10, 30, 60, 120, 300, 600)      # 活跃度的快半衰期候选(秒):预登记 8b
SLOW = 3600                             # 每笔方差的慢半衰期(秒):预登记 8b(取研究五半衰期网格的最大值;ASSUMPTION)
OUT = os.path.join(V.GRID, "vol_event_time_report.txt")
LINES = []


def P(s=""):
    LINES.append(s)
    print(s, flush=True)


def series(day):
    """一天的每秒收益 r(bp)、可用标记、每秒吃单笔数 n。n 的第 i 个元素统计第 i 秒内的吃单(与 r 的第 i 个元素同一秒)。"""
    t0, lp, _, ok = V.load(day)
    r, o = V.sec_returns(lp, ok, int(round(1.0 / V.STEP_S)))
    sw = np.load(os.path.join(MKT, f"XBTUSDTM_{day}.npz"))["sw"]
    idx = ((sw[:, 0] - t0) // 10**9).astype(np.int64)
    n = np.bincount(idx[(idx >= 0) & (idx < len(r))], minlength=len(r)).astype(float)
    return r, o, n


def ew(x, ok, hl, x0):
    """指数加权平均(同 vol_study.ewma;x[t] 只用到第 t 个及以前的值)。"""
    return V.ewma(x, ok, hl, x0)


def main():
    S = {d: series(d) for d in V.TRAIN + V.VALID + V.OCT}
    r2m = float(np.mean(np.concatenate([S[d][0][S[d][1]] ** 2 for d in V.TRAIN])))
    nm = float(np.mean(np.concatenate([S[d][2][S[d][1]] for d in V.TRAIN])))
    c = r2m / nm
    P(f"训练段:每秒收益平方均值 {r2m:.4f} bp²,每秒吃单 {nm:.3f} 笔,每笔吃单对应方差 c = {c:.3f} bp²")

    def fc(d, hl_fast):
        r, o, n = S[d]
        m = H
        k = len(r) // m * m
        rv = (r[:k] ** 2).reshape(-1, m).sum(1)
        good = o[:k].reshape(-1, m).all(1) & (rv > 0)
        idx = np.arange(0, k, m)
        good &= idx >= SLOW                                   # 预热一个慢半衰期
        at = lambda v, v0: np.r_[v0, v][idx] * H              # 块起点处的值(只用起点之前的数据)× H
        e1 = at(ew(r ** 2, o, 600, r2m), r2m)
        nf = ew(n, o, hl_fast, nm)
        e2 = at(c * nf, r2m)
        per = ew(r ** 2, o, SLOW, r2m) / np.maximum(ew(n, o, SLOW, nm), 1e-6)
        e3 = at(per * nf, r2m)
        return rv, good, e1, np.maximum(e2, 1e-6), np.maximum(e3, 1e-6)

    P("快半衰期的选择(只在训练段内,后 4 天的 QLIKE;H = 60 秒)")
    sel2, sel3 = {}, {}
    for hl in FAST:
        l2, l3 = [], []
        for d in V.TRAIN[9:]:
            rv, g, e1, e2, e3 = fc(d, hl)
            l2.append(V.qlike(e2[g], rv[g])); l3.append(V.qlike(e3[g], rv[g]))
        sel2[hl], sel3[hl] = float(np.mean(np.concatenate(l2))), float(np.mean(np.concatenate(l3)))
    P("   E2: " + "  ".join(f"{h}s {sel2[h]:.4f}" for h in FAST))
    P("   E3: " + "  ".join(f"{h}s {sel3[h]:.4f}" for h in FAST))
    h2, h3 = min(sel2, key=sel2.get), min(sel3, key=sel3.get)
    P(f"   选定:E2 {h2} 秒,E3 {h3} 秒")
    for seg, days in (("验证", V.VALID), ("10 月", V.OCT)):
        L1, L2, L3, A, F1, F2, F3 = [], [], [], [], [], [], []
        for d in days:
            rv, g, e1, e2, _ = fc(d, h2)
            _, _, _, _, e3 = fc(d, h3)
            L1.append(V.qlike(e1[g], rv[g])); L2.append(V.qlike(e2[g], rv[g])); L3.append(V.qlike(e3[g], rv[g]))
            A.append(np.sqrt(rv[g])); F1.append(np.sqrt(e1[g])); F2.append(np.sqrt(e2[g])); F3.append(np.sqrt(e3[g]))
        L1, L2, L3, A = (np.concatenate(x) for x in (L1, L2, L3, A))
        cor = lambda F: np.corrcoef(np.concatenate(F), A)[0, 1]
        P(f"{seg}(H = 60 秒,块数 {len(L1):,})")
        P(f"   E1 指数加权收益平方(600 s)   QLIKE {L1.mean():.4f}   与实际波动的相关系数 {cor(F1):+.3f}")
        P(f"   E2 只用活跃度({h2} s)        QLIKE {L2.mean():.4f}   相关系数 {cor(F2):+.3f}   对 E1 DM {V.dm(L2, L1):+.1f}")
        P(f"   E3 每笔方差 × 活跃度({h3} s)  QLIKE {L3.mean():.4f}   相关系数 {cor(F3):+.3f}   对 E1 DM {V.dm(L3, L1):+.1f}")
    open(OUT, "w", encoding="utf8").write("\n".join(LINES))
    print("VOL_EVENT_DONE", flush=True)


if __name__ == "__main__":
    main()
