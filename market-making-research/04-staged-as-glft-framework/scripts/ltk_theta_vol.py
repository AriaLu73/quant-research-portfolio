#!/usr/bin/env python3
"""research7 大 tick 线:公允价过滤门槛按波动缩放的形式与系数(离线,不新跑回放)。

用途      用户 2026-10-09 裁决规则 R 的门槛按波动缩放。本脚本用 10-01 回放已有的成交(方案 imp_all_jit:不带规则)离线选形式与系数。
所属阶段  阶段 4 / 6 的方法在宽价差合约上的应用;预登记 00_范围_阈值_预登记.md 第 18 节。
对应公式  规则 R:ε(F − P)/P × 1e4 ≥ a × 一跳的 bp + b × σ60。
变量      edge = 成交时刻我方价相对公允价的边际(bp);tick_bp = 一跳 / 价格 × 1e4;
          σ60 = 过去 VOL_S 秒 KuCoin 中间价 1 秒对数收益的标准差 × √60(bp,只用过去);
          net = ε(m_{+60s} − P)/P × 1e4 + 返佣(bp);usd = 成交名义金额(美元)。
数据来源  data/research7/ltk_l3/<合约>.npz(ltk_l3.py 的输出:bbo、成交);data/research7/feat/bn_<币安合约>_20261001.npz。
用法      .venv/Scripts/python.exe scripts/research7/ltk_theta_vol.py
"""
import glob
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L3 = os.path.join(ROOT, "data", "research7", "ltk_l3")
FEAT = os.path.join(ROOT, "data", "research7", "feat")
OUT = os.path.join(ROOT, "data", "research7", "ltk_theta")
DAY = "20261001"
NS, STEP_NS = 10**9, 100_000_000
BASIS_S = 300                      # 同回放(ltk_l3.BASIS_S)
VOL_S = 300                        # 波动窗口:与基差窗口相同(ASSUMPTION;探针数据回来后再按预测误差选)
H_S = 60                           # markout 时点:同 ltk_l3_summary.py 的口径
REBATE_BP = OUR_FEE                    # KuCoin 我方费率档,TradFi 合约挂单返佣(项目记录 memory kucoin-mm-offer)
A_GRID = (-0.5, -0.25, 0.0, 0.25, 0.5)
B_GRID = (-0.2, -0.1, -0.05, 0.0, 0.05, 0.1, 0.2)


def load(sym):
    z = np.load(os.path.join(L3, sym + ".npz"))
    fb = os.path.join(FEAT, "bn_%s_%s.npz" % (sym[:-1], DAY))      # KuCoin XXXUSDTM ↔ 币安 XXXUSDT
    if not os.path.exists(fb):
        return None
    zb = np.load(fb)
    tick, mult = float(z["tick"]), float(z["mult"])
    b = z["bbo"]
    t, mid = b[:, 0], (b[:, 1] + b[:, 2]) / 2.0 * tick
    g0, lpb = int(zb["g0"]), np.log(zb["px"].astype(np.float64))
    s0, s1 = int(t[0] // NS) + 1, int(t[-1] // NS)
    secs = np.arange(s0, s1)
    ik = np.searchsorted(t, secs * NS, side="right") - 1
    lm = np.log(mid[ik])
    fresh = secs * NS - t[ik] < 60 * NS                            # 盘口 60 秒内有更新(断档不跨)
    jb = secs * 10 - g0 - 1                                        # 币安滞后一个 100 毫秒网格点
    okb = (jb >= 0) & (jb < len(lpb))
    lb = np.full(len(secs), np.nan)
    lb[okb] = lpb[jb[okb]]
    d = np.where(fresh, lm - lb, np.nan)
    r = np.r_[np.nan, np.diff(lm)] * 1e4
    r[~fresh | ~np.r_[False, fresh[:-1]]] = np.nan
    basis, sig = np.full(len(secs), np.nan), np.full(len(secs), np.nan)
    for i in range(len(secs)):                                     # 第 i 秒可用的值只用 i 之前的样本
        w = d[max(0, i - BASIS_S):i]
        w = w[np.isfinite(w)]
        if len(w) >= BASIS_S // 2:
            basis[i] = np.median(w)
        v = r[max(0, i - VOL_S):i]
        v = v[np.isfinite(v)]
        if len(v) >= VOL_S // 2:
            sig[i] = v.std() * np.sqrt(H_S)
    out = {}
    for name in ("imp_all_jit", "imp_ref_jit"):
        f = z[name]
        ft, side, px, qty = f[:, 0].astype(np.int64), f[:, 1], f[:, 2] * tick, f[:, 3]
        eps = np.where(side == 0, 1.0, -1.0)
        i = ft // NS - s0
        ok = (i >= 0) & (i < len(secs))
        i = np.clip(i, 0, len(secs) - 1)
        jf = ft // STEP_NS - g0 - 1
        okf = (jf >= 0) & (jf < len(lpb))
        F = np.exp(np.where(okf, lpb[np.clip(jf, 0, len(lpb) - 1)], np.nan) + basis[i])
        edge = eps * (F - px) / px * 1e4
        k = np.searchsorted(t, ft + H_S * NS, side="right") - 1
        net = eps * (mid[k] - px) / px * 1e4 + REBATE_BP
        okm = (ft + H_S * NS <= t[-1]) & (ft + H_S * NS - t[k] < 60 * NS)
        m = ok & okm
        if name == "imp_all_jit":
            m = m & np.isfinite(edge) & np.isfinite(sig[i])
        out[name] = dict(edge=edge[m], sig=sig[i][m], net=net[m], usd=(qty * mult * px)[m], hour=((ft // NS // 3600) % 24)[m],
                         tick_bp=tick / px[m] * 1e4)
    return out


def total(D, a, b, sel):
    """给定系数,在 sel 指定的小时上:合计净值美元、成交额、净值为正的合约数。"""
    usd = net = 0.0
    pos = 0
    for x in D.values():
        m = sel(x["hour"]) & (x["edge"] >= a * x["tick_bp"] + b * x["sig"])
        v = float((x["net"][m] * x["usd"][m]).sum() / 1e4)
        net += v
        usd += float(x["usd"][m].sum())
        pos += v > 0
    return net, usd, pos


def main():
    os.makedirs(OUT, exist_ok=True)
    lines = []

    def P(s=""):
        lines.append(s)
        print(s, flush=True)

    D, R = {}, {}
    for f in sorted(glob.glob(os.path.join(L3, "*.npz"))):
        sym = os.path.basename(f)[:-4]
        o = load(sym)
        if o is not None and len(o["imp_all_jit"]["net"]):
            D[sym], R[sym] = o["imp_all_jit"], o["imp_ref_jit"]

    def even(h):
        return h % 2 == 0

    def odd(h):
        return h % 2 == 1

    def allh(h):
        return h >= 0

    n_all = sum(len(x["net"]) for x in D.values())
    P("公允价过滤门槛按波动缩放 —— %s,%d 个合约,方案 imp_all_jit 的成交 %s 笔;每笔净值 = 60 秒 markout + 返佣 %.我方费率f bp" % (DAY, len(D), format(n_all, ","), REBATE_BP))
    P()
    P("== 近似的核对:成交时刻 edge ≥ −0.25 跳的成交 对 回放里真正带规则的方案 imp_ref_jit(全部小时)")
    n0, u0, _ = total(D, -0.25, 0.0, allh)
    rn = sum(float((x["net"] * x["usd"]).sum() / 1e4) for x in R.values())
    ru = sum(float(x["usd"].sum()) for x in R.values())
    P("   近似:成交额 $%s,净值 $%+.0f(%+.2f bp)   回放:成交额 $%s,净值 $%+.0f(%+.2f bp)" % (format(round(u0), ","), n0, n0 / u0 * 1e4, format(round(ru), ","), rn, rn / ru * 1e4))
    P()
    P("== 各合约的波动与一跳(成交时刻的中位数)")
    for sym, x in D.items():
        P("   %-14s 一跳 %5.2f bp   σ60 %5.2f bp(10%%–90%%:%.2f–%.2f)   σ60 / 一跳 %6.2f" % (
            sym, np.median(x["tick_bp"]), np.median(x["sig"]), np.percentile(x["sig"], 10), np.percentile(x["sig"], 90), np.median(x["sig"] / x["tick_bp"])))
    P()
    cands = {"M0 现行": [(-0.25, 0.0)], "M1 只按跳": [(a, 0.0) for a in A_GRID], "M2 只按波动": [(0.0, b) for b in B_GRID],
             "M3 跳 + 波动": [(a, b) for a in A_GRID for b in B_GRID]}
    base = total(D, -9e9, 0.0, odd)
    P("== 偶数小时选系数,奇数小时判读(不设规则时奇数小时:净值 $%+.0f,成交额 $%s,正的合约 %d)" % (base[0], format(round(base[1]), ","), base[2]))
    best = {}
    for name, grid in cands.items():
        a, b = max(grid, key=lambda ab: total(D, ab[0], ab[1], even)[0])
        e, o = total(D, a, b, even), total(D, a, b, odd)
        best[name] = (a, b)
        P("   %-10s 选定 a = %+.2f 跳,b = %+.2f σ60 | 偶数小时 $%+.0f | 奇数小时 净值 $%+.0f(%+.2f bp),成交额 $%s(保留 %.0f%%),正的合约 %d / %d" % (
            name, a, b, e[0], o[0], o[0] / max(o[1], 1) * 1e4, format(round(o[1]), ","), 100 * o[1] / base[1], o[2], len(D)))
    P()
    P("== 奇数小时,按成交时刻 σ60 在本合约内的三分位分组:各方案的每笔净值(bp)/ 净值美元")
    for name, (a, b) in best.items():
        row = []
        for lo, hi in ((0, 33.33), (33.33, 66.67), (66.67, 100)):
            net = usd = 0.0
            for x in D.values():
                q0, q1 = np.percentile(x["sig"], lo), np.percentile(x["sig"], hi)
                m = odd(x["hour"]) & (x["sig"] >= q0) & ((x["sig"] < q1) | (hi == 100)) & (x["edge"] >= a * x["tick_bp"] + b * x["sig"])
                net += float((x["net"][m] * x["usd"][m]).sum() / 1e4)
                usd += float(x["usd"][m].sum())
            row.append("%+.2f bp / $%+.0f" % (net / max(usd, 1) * 1e4, net))
        P("   %-10s 低 %-22s 中 %-22s 高 %s" % (name, row[0], row[1], row[2]))
    P()
    for title, a in (("M2 的 b 全网格(a = 0)", 0.0), ("M3 在 a = −0.25 时的 b 全网格", -0.25)):
        P("== %s(奇数小时;看结果对系数是否敏感)" % title)
        for b in B_GRID:
            o = total(D, a, b, odd)
            P("   b = %+.2f:净值 $%+.0f(%+.2f bp),成交额 $%s,正的合约 %d" % (b, o[0], o[0] / max(o[1], 1) * 1e4, format(round(o[1]), ","), o[2]))
    open(os.path.join(OUT, "theta_vol_report.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
