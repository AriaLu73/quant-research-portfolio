#!/usr/bin/env python3
"""research7 大 tick 品种第二轮:贴最优价 + 以币安价格为公允价的"挂 / 撤"规则。离线,不含策略回放。

起因      第一轮(ltk_screen.py)显示:白银、布伦特、天然气上贴着不动的报价,成交时价格多半已经先走到报价上——是被外部价格挑走的。
          用户 2026-10-08:外部信息就接外部市场,用币安相关的价格(只读;项目记录 memory ref-feed-ruling:允许 KuCoin 策略只读币安行情)。
所属阶段  阶段 4 / 6 的方法在其它品种上的应用(研究一"跨品种信号"+ 研究八"快速撤单");不改变 BTC 线已有结论。
对应公式  F_t(公允价格)= 币安同名永续的最后成交价 + 基差;执行层的"保持 / 撤单"。
公允价    F(t) = 币安最后成交价(按滞后 100 毫秒读取)× exp(基差),基差 = 过去 BASIS_S 秒里 ln(KuCoin 中间价 / 币安价)的中位数
          (每秒采样,只用 t 之前的数据)。300 秒沿用阶段 3 的设定(ASSUMPTION)。
规则      只用一个参数 θ(单位:tick):我方报价 P 相对公允价的优势 edge = ε·(F − P) ≥ θ·tick 时才挂;存活期间每 100 毫秒检查一次,
          edge < θ·tick 即撤,撤单 100 毫秒后生效(保守:实测撤单 p90 15.6 ms)。θ 候选:不设规则 / −0.25 / 0 / 0.25 / 0.5。
          θ 在训练段选(每张报价的期望净值最高),验证段只读一次。
成交口径  队首(上界)与排到队尾(下界)并列,同 ltk_screen.py。
变量      eps = ε;e_h = ε·(m_h − P) / m0 × 1e4(bp);每笔净值 = e_h + 返佣;half = ε·(m0 − P)(bp)。
容量      每天成交笔数按"每侧同一时刻一张"折算;每笔的成交额取 min(每单名义金额, 那张吃单的成交额)——不再假设每次都全额成交。
用法      .venv/Scripts/python.exe scripts/research7/ltk_ref.py build <KuCoin 合约> <币安合约> <YYYYMMDD>
          .venv/Scripts/python.exe scripts/research7/ltk_ref.py report <KuCoin 合约> [...]
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calib as C
import ltk_screen as S

ROOT = C.ROOT
MKT = os.path.join(ROOT, "data", "research7", "market_l2")
FEAT = os.path.join(ROOT, "data", "research7", "feat")
OUT = os.path.join(ROOT, "data", "research7", "ltk_ref")
STEP_NS, NS = 100_000_000, 10**9
EVERY_S, LIFE_S = 5, 60            # 每 5 秒放一组,最长存活 60 秒(第一轮:这些品种成交稀;ASSUMPTION)
HS = (10, 60, 300)
GAP_S = 30.0
BASIS_S = 300
THETAS = (None, -0.25, 0.0, 0.25, 0.5)     # 预登记于文件头
ORDER_USD = 2000.0                 # 每单名义金额(ASSUMPTION;与第一轮相同)
COLS = ("hour", "side", "ti", "placed", "fillU", "fillQ", "half", "e10", "e60", "e300", "a60", "edge0", "usdU", "usdQ", "life_s")


def build(sym, bsym, day):
    fz = os.path.join(MKT, f"{sym}_{day}.npz")
    fb = os.path.join(FEAT, f"bn_{bsym}_{day}.npz")
    if not (os.path.exists(fz) and os.path.exists(fb)):
        print(f"ltk_ref {sym} {day}: 缺数据  LTKREF_BUILD_DONE", flush=True)
        return
    z, zb = np.load(fz), np.load(fb)
    b, sw = z["bbo"], z["sw"]
    tick, mult = S.spec(sym)
    t, bb, ba, qb, qa = b[:, 0], b[:, 1], b[:, 2], b[:, 3].astype(float), b[:, 4].astype(float)
    mid = (bb + ba) / 2.0 * tick                                   # 美元
    g0, lpb = int(zb["g0"]), np.log(zb["px"].astype(np.float64))
    # 基差:每秒采样 ln(KuCoin 中间价 / 币安价),过去 BASIS_S 秒的中位数(只用过去)
    s0, s1 = int(t[0] // NS) + 1, int(t[-1] // NS)
    secs = np.arange(s0, s1)
    ik = np.searchsorted(t, secs * NS, side="right") - 1
    jb = secs * 10 - g0 - 1                                         # 币安滞后一个网格点
    okb = (jb >= 0) & (jb < len(lpb))
    d = np.full(len(secs), np.nan)
    d[okb] = np.log(mid[ik[okb]]) - lpb[jb[okb]]
    basis = np.full(len(secs), np.nan)
    if len(secs) > BASIS_S + 1:
        win = np.lib.stride_tricks.sliding_window_view(d, BASIS_S)
        basis[BASIS_S:] = np.nanmedian(win, axis=1)[:-1]            # 第 i 秒用的是 [i − 300, i) 的数据
    per_side = [(sw[sw[:, 1] == s][:, 0], sw[sw[:, 1] == s][:, 2].astype(float), sw[sw[:, 1] == s][:, 4]) for s in (0, 1)]
    tick_bp = tick / float(np.mean(mid)) * 1e4
    nstep = LIFE_S * 10
    rows = []
    for sec in range(s0 + BASIS_S + 5, s1 - LIFE_S - max(HS) - 2, EVERY_S):
        t0 = sec * NS
        i0 = int(np.searchsorted(t, t0, side="right")) - 1
        bs = basis[sec - s0]
        j0 = sec * 10 - g0 - 1
        if i0 < 0 or t0 - t[i0] > GAP_S * NS or bb[i0] >= ba[i0] or not np.isfinite(bs) or j0 < 0 or j0 + nstep + 2 >= len(lpb):
            continue
        Fpath = np.exp(lpb[j0:j0 + nstep + 1] + bs)                 # 存活期间每 100 毫秒的公允价(美元);基差在存活期内不更新(保守)
        for s in (0, 1):
            ts_s, q_s, last_s = per_side[s]
            eps = 1 if s == 0 else -1
            ptk = bb[i0] if s == 0 else ba[i0]
            P = ptk * tick
            q_best = qb[i0] if s == 0 else qa[i0]
            edge = eps * (Fpath - P) / P * 1e4                      # bp;正 = 我方报价比公允价好
            lo, hi = np.searchsorted(ts_s, (t0, t0 + LIFE_S * NS), side="right")
            for ti, th in enumerate(THETAS):
                placed, t_stop = 1, t0 + LIFE_S * NS
                if th is not None:
                    thr = th * tick_bp
                    if edge[0] < thr:
                        placed = 0
                    else:
                        below = np.nonzero(edge[1:] < thr)[0]
                        if len(below):
                            t_stop = t0 + (int(below[0]) + 1) * STEP_NS + STEP_NS     # 看到触发的时刻 + 100 毫秒撤单生效
                fU = fQ = 0
                jf = jq = -1
                cum = 0.0
                if placed:
                    for j in range(lo, hi):
                        if ts_s[j] >= t_stop:
                            break
                        if not ((last_s[j] <= ptk) if s == 0 else (last_s[j] >= ptk)):
                            continue
                        through = (last_s[j] < ptk) if s == 0 else (last_s[j] > ptk)
                        if jf < 0:
                            jf, fU = j, 1
                        cum += q_s[j]
                        if through or cum >= q_best:
                            jq, fQ = j, 1
                            break
                half = np.nan
                e = [np.nan] * 3
                a60 = np.nan
                usdU = usdQ = 0.0
                life_s = (t_stop - t0) / NS if placed else 0.0
                if jf >= 0:
                    tf = int(ts_s[jf])
                    it = int(np.searchsorted(t, tf, side="left")) - 1
                    if it >= 0 and tf - t[it] <= GAP_S * NS:
                        m0 = mid[it]
                        half = eps * (m0 - P) / m0 * 1e4
                        for k, h in enumerate(HS):
                            ih = int(np.searchsorted(t, tf + h * NS, side="right")) - 1
                            if tf + h * NS - t[ih] <= max(GAP_S, h) * NS:
                                e[k] = eps * (mid[ih] - P) / m0 * 1e4
                                if h == 60:
                                    a60 = -eps * (mid[ih] - m0) / m0 * 1e4
                    usdU = min(ORDER_USD, q_s[jf] * mult * P)       # 这张吃单能给我方的最大成交额
                    if jq >= 0:
                        usdQ = min(ORDER_USD, max(cum - q_best, q_s[jq] if cum < q_best else cum - q_best) * mult * P)
                rows.append((sec // 3600, s, ti, placed, fU, fQ, half, *e, a60, edge[0], usdU, usdQ, life_s))
    A = np.asarray(rows, np.float64)
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(os.path.join(OUT, f"{sym}_{day}.npz"), rows=A.astype(np.float32), tick_bp=tick_bp,
                        usd=float(np.sum(sw[:, 2] * mult * sw[:, 3] * tick)), basis_sd=float(np.nanstd(d - basis) * 1e4))
    print(f"ltk_ref {sym} {day}: 行 {len(A):,};1 tick = {tick_bp:.2f} bp;KuCoin 中间价相对公允价的偏离标准差 {np.nanstd(d - basis) * 1e4:.2f} bp  LTKREF_BUILD_DONE", flush=True)


def report(syms):
    L = []
    P = lambda s="": (L.append(s), print(s, flush=True))
    P('大 tick 品种第二轮:贴最优价,只在我方报价比币安公允价好 θ 个 tick 以上时挂着(存活最长 60 秒;撤单 100 毫秒生效)')
    P(f"每笔净值取成交后 60 秒;每天美元 = 成交笔数(每侧同一时刻一张)× min(每单 ${ORDER_USD:,.0f}, 吃单成交额)× 每笔净值。θ 在训练段选,验证段只读一次")
    for sym in syms:
        rb = S.rebate(sym)
        sel = None
        for seg, days in (("训练", C.TRAIN_DAYS), ("验证", C.VALID_DAYS)):
            Z = [np.load(os.path.join(OUT, f"{sym}_{d}.npz")) for d in days if os.path.exists(os.path.join(OUT, f"{sym}_{d}.npz"))]
            if not Z:
                continue
            A = np.vstack([z["rows"].astype(np.float64) for z in Z])
            D = {c: A[:, i] for i, c in enumerate(COLS)}
            nd = len(Z)
            P(f"\n== {sym}  {seg}({nd} 天):1 tick = {np.mean([z['tick_bp'] for z in Z]):.2f} bp;全市场成交额 ${np.mean([z['usd'] for z in Z]) / 1e6:.2f}M/天;"
              f"KuCoin 中间价相对公允价的偏离标准差 {np.mean([z['basis_sd'] for z in Z]):.2f} bp;返佣 {rb} bp")
            P("   θ(tick)  挂出比例  平均在簿秒数 | 队首:成交率  成交时优势  每笔净值(t)   笔/天   $/天成交额   $/天净值 | 排到队尾:成交率  每笔净值(t)   笔/天   $/天净值")
            res = {}
            for ti, th in enumerate(THETAS):
                m = D["ti"] == ti
                nq = m.sum()
                pl = m & (D["placed"] == 1)
                out = [f"   {'无规则' if th is None else format(th, '+.2f'):<8} {pl.sum() / nq:>7.1%} {D['life_s'][pl].mean() if pl.sum() else 0:>10.1f}   |"]
                # 重叠折算:同一时刻在簿的张数 = 平均在簿秒数 × 挂出比例 / 5 秒;小于 1 时不放大
                overlap = max(D["life_s"][m].mean() / EVERY_S, 1.0)
                for key, ukey in (("fillU", "usdU"), ("fillQ", "usdQ")):
                    f = pl & (D[key] == 1)
                    x = np.where(f, D["e60"], np.nan) + rb
                    mu, t, n = S.block(x, D["hour"])
                    per_day = f.sum() / nd / overlap
                    usd_fill = float(np.mean(D[ukey][f])) if f.sum() else 0.0
                    half = np.nanmean(D["half"][f]) if f.sum() else float("nan")
                    ev = per_day * usd_fill * (mu if mu == mu else 0.0) / 1e4
                    res[(ti, key)] = (mu, t, per_day, ev, np.nansum(x[f]) / nq if f.sum() else 0.0)
                    if key == "fillU":
                        out.append(f" {f.sum() / nq:>6.2%}  {half:>+7.2f}  {mu:>+7.2f}({t:>+5.1f}) {per_day:>7,.0f} {per_day * usd_fill:>11,.0f} {ev:>+9.2f} |")
                    else:
                        out.append(f" {f.sum() / nq:>6.2%}  {mu:>+7.2f}({t:>+5.1f}) {per_day:>7,.0f} {ev:>+9.2f}")
                P("".join(out))
            if seg == "训练":
                sel = max(range(1, len(THETAS)), key=lambda ti: res[(ti, "fillU")][4])      # 每张报价的期望净值(队首口径)最高
                P(f"   训练段选定 θ = {THETAS[sel]:+.2f} tick(每张报价的期望净值最高,队首口径)")
            elif sel is not None:
                u, q, u0, q0 = res[(sel, "fillU")], res[(sel, "fillQ")], res[(0, "fillU")], res[(0, "fillQ")]
                P(f"   验证段判读(θ = {THETAS[sel]:+.2f}):队首 每笔 {u[0]:+.2f} bp(t {u[1]:+.1f}),${u[3]:+.2f}/天;排到队尾 每笔 {q[0]:+.2f} bp(t {q[1]:+.1f}),${q[3]:+.2f}/天。"
                  f"无规则时:队首 {u0[0]:+.2f} / 队尾 {q0[0]:+.2f} bp")
    open(os.path.join(OUT, "ltk_ref_report_" + "_".join(s[:4] for s in syms) + ".txt"), "w", encoding="utf8").write("\n".join(L))


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        report(sys.argv[2:])
