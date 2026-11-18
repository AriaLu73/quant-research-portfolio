#!/usr/bin/env python3
"""research7 阶段 4:成交强度(研究二)与逆向选择(研究三)在同一批假想报价上的联合估计。离线,不含策略回放。

用途      在每 5 秒、买卖两侧、8 个距离上放固定价格的假想报价(存活 10 秒),同时记录"是否成交"与"成交之后怎样",
          回答:成交概率随距离与状态怎样变;成交后的不利变动随什么变、其中多少已被 α̂ 解释;有没有每笔净值为正的(距离 × 状态)区域。
所属阶段  阶段 4(研究二、研究三;预登记 00_范围_阈值_预登记.md 第 12 节,常数均来自那里)。
对应公式  A_t、κ_t(替换 GLFT 的常数 A、κ)与 c^AS_b(X_t)、c^AS_a(X_t)(加在 δ^b、δ^a 上)。
变量与 <符号表> 的对应
          eps = ε(买入报价 +1,卖出报价 −1);P = 报价价格;m0 = 成交前中间价 m_0;mh = m_h;
          e_h = ε·(m_h − P)(bp):这笔成交在 h 秒后按中间价计的毛利(不含返佣)= 价差收益 + markout
          a_h = −ε·(m_h − m_0)(bp):不利变动(正 = 对我方不利)= −markout
          alpha = α̂(bp;data/research7/feat/micro_table.json)
成交口径  最优价之外:队首(对侧吃单成交价到达或穿过即成交;用户裁决的口径,排队位置的上界)。
          距离 0:并列"队首"与"排队"(我方之后该价位累计被吃的量 ≥ 进簿时的同侧最优价挂单量,或该档被扫穿;不计前方撤单,下界)。
没有用未来数据的保证  报价价格与状态只取放置时刻之前的网格行;分位边界取训练段。
用法      .venv/Scripts/python.exe scripts/research7/as_study.py build <YYYYMMDD>
          .venv/Scripts/python.exe scripts/research7/as_study.py report
"""
import bisect
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calib as C

ROOT = C.ROOT
FEAT = os.path.join(ROOT, "data", "research7", "feat")
MKT = os.path.join(ROOT, "data", "research7", "market_l2")
OUT = os.path.join(ROOT, "data", "research7", "as")
TICK, STEP_NS, GRID_PER_S = 0.1, 100_000_000, 10
DELTAS = (0, 1, 5, 20, 50, 100, 200, 400)      # 离同侧最优价的 tick 数:预登记
EVERY_S, LIFE_S = 5, 10                        # 每 5 秒放一组,存活 10 秒:预登记
HS = (1, 10, 60)                               # 成交后的时间窗(秒):预登记
GAP_S, EWMA_HL_S = 5.0, 600
REBATE = OUR_FEE                                   # 挂单返佣(bp):KuCoin Market Maker Program Ver. April 2026,我方费率档
ORDER_BTC = 0.2                                # 每单数量(折算美元用):项目记录
OCT = ("20261001", "20261002")
COLS = ("day", "hour", "side", "di", "fillU", "fillQ", "through", "tau", "e1", "e10", "e60", "a1", "a10", "a60",
        "alpha_adv", "imb_s", "sig", "act", "lead1", "swq", "px")


def build(day):
    z = np.load(os.path.join(FEAT, f"feat_{day}.npz"))
    g = z["g"].astype(np.int64)
    g0 = int(g[0])
    cont = np.all(np.diff(g) == 1)
    bb, ba = z["bb"].astype(np.int64), z["ba"].astype(np.int64)
    qb, qa = z["qb"].astype(float), z["qa"].astype(float)
    n = len(g)
    mid2 = bb + ba                                               # 2 × 中间价(tick)
    ok = (z["age"] < GAP_S) & np.r_[True, np.diff(g) == 1]
    lm = np.log(mid2 / 2.0 * TICK)
    # σ_t:1 秒收益平方的指数加权(半衰期 600 秒),只用过去
    r1 = np.r_[0.0, np.diff(lm[::GRID_PER_S])] * 1e4
    lam, v, cur = 0.5 ** (1.0 / EWMA_HL_S), np.empty(len(r1)), float(np.mean(r1 ** 2))
    for i in range(len(r1)):
        cur = lam * cur + (1 - lam) * r1[i] ** 2
        v[i] = cur
    sig = np.repeat(np.sqrt(v), GRID_PER_S)[:n]
    c = np.cumsum(np.r_[0.0, z["tb"].astype(float) + z["ts_"].astype(float)])
    i_ = np.arange(1, n + 1)
    act = c[i_] - c[np.maximum(i_ - 10 * GRID_PER_S, 0)]         # 过去 10 秒吃单张数
    imb = (qb - qa) / np.maximum(qb + qa, 1.0)
    tab = json.load(open(os.path.join(FEAT, "micro_table.json")))
    edges, alpha = tab["edges"], np.asarray(tab["alpha_bp"])
    # 币安过去 1 秒收益(滞后 100 毫秒),用于"与领先品种同向"的识别特征
    lead = np.full(n, np.nan)
    fb = os.path.join(FEAT, f"bn_{day}.npz")
    if os.path.exists(fb):
        zb = np.load(fb)
        j = g - int(zb["g0"]) - 1
        vmask = (j >= GRID_PER_S) & (j < len(zb["px"]))
        px = zb["px"].astype(float)
        lead[vmask] = (np.log(px[j[vmask]]) - np.log(px[j[vmask] - GRID_PER_S])) * 1e4
    sw = np.load(os.path.join(MKT, f"XBTUSDTM_{day}.npz"))["sw"]
    per_side = []
    for s in (0, 1):
        w = sw[sw[:, 1] == s]
        per_side.append((w[:, 0], w[:, 2].astype(float), w[:, 3], w[:, 4]))   # 时间、张数、最先成交 tick、最后(最差)成交 tick
    rows = []
    hmax = max(HS) * GRID_PER_S + 2
    for i0 in range(0, n - (LIFE_S * GRID_PER_S + hmax), EVERY_S * GRID_PER_S):
        if not ok[i0]:
            continue
        t0 = (g0 + i0) * STEP_NS if cont else int(g[i0]) * STEP_NS
        for s in (0, 1):
            ts_s, q_s, first_s, last_s = per_side[s]
            lo, hi = np.searchsorted(ts_s, (t0, t0 + LIFE_S * 10**9), side="right")
            eps = 1 if s == 0 else -1
            best = bb[i0] if s == 0 else ba[i0]
            q_best = qb[i0] if s == 0 else qa[i0]
            for di, d in enumerate(DELTAS):
                p = best - d if s == 0 else best + d
                fU = fQ = thr = 0
                tau = swq = 0.0
                jf = -1
                cum = 0.0
                for j in range(lo, hi):
                    reach = last_s[j] <= p if s == 0 else last_s[j] >= p         # 吃单到达或穿过我方价位
                    if not reach:
                        continue
                    through = last_s[j] < p if s == 0 else last_s[j] > p
                    if jf < 0:
                        jf, fU, thr = j, 1, int(through)
                    if d == 0:
                        cum += q_s[j]                                            # 我方之后该价位累计被吃的量(上界:整张吃单都算在这一档)
                        if (through or cum >= q_best) and not fQ:
                            fQ = 1
                    elif not fQ:
                        fQ = 1                                                   # 最优价之外没有排队口径,取与队首相同
                    if fU and (fQ or d != 0):
                        break
                e = [np.nan] * 3
                a = [np.nan] * 3
                al = ld = np.nan
                if jf >= 0:
                    tfill = int(ts_s[jf])
                    it = tfill // STEP_NS - g0 if cont else int(np.searchsorted(g, tfill // STEP_NS))
                    it = min(max(int(it), 0), n - 1)                             # 成交所在网格行 = 成交前的盘口状态
                    tau, swq = (tfill - t0) / 1e9, q_s[jf]
                    m0 = mid2[it] / 2.0
                    for k, h in enumerate(HS):
                        ih = it + h * GRID_PER_S + 1
                        if ih < n and ok[ih] and ok[it]:
                            mh = mid2[ih] / 2.0
                            e[k] = eps * (mh - p) / m0 * 1e4                     # 单位换算:tick 差 / 价格(tick)→ bp
                            a[k] = -eps * (mh - m0) / m0 * 1e4
                    al = -eps * alpha[bisect.bisect_right(edges, imb[it])]       # α̂ 预言的不利变动(正 = 不利)
                    ld = -eps * lead[it]                                         # 币安成交前 1 秒朝不利方向的变动(bp)
                rows.append((0, (g0 + i0) // (3600 * GRID_PER_S), s, di, fU, fQ, thr, tau, *e, *a, al, eps * imb[i0], sig[i0], act[i0], ld, swq, best * TICK))
    A = np.asarray(rows, np.float64)
    os.makedirs(OUT, exist_ok=True)
    np.save(os.path.join(OUT, f"q_{day}.npy"), A.astype(np.float32))
    f = A[A[:, 3] == 0]
    print(f"as {day}: 假想报价 {len(A):,};距离 0 成交率 队首 {f[:, 4].mean():.1%} / 排队 {f[:, 5].mean():.1%}  AS_BUILD_DONE", flush=True)


def load(days):
    A = np.vstack([np.load(os.path.join(OUT, f"q_{d}.npy")).astype(np.float64) for d in days])
    return {c: A[:, i] for i, c in enumerate(COLS)}


def block_stat(x, hour):
    """按小时分块的均值与 Newey–West t(滞后 1)。x 里的 NaN 剔除。"""
    m = np.isfinite(x)
    if m.sum() < 30:
        return float("nan"), float("nan"), int(m.sum())
    hs = np.unique(hour[m])
    bl = np.array([x[m][hour[m] == h].mean() for h in hs])
    mu, t, _ = C.nw_t(bl)
    return float(np.mean(x[m])), t, int(m.sum())


def report():
    L = []
    P = lambda s="": (L.append(s), print(s, flush=True))
    TR, VA, OC = load(C.TRAIN_DAYS), load(C.VALID_DAYS), load(OCT)
    bp_usd = lambda D: float(np.nanmean(D["px"])) / 1e4
    P("阶段 4 联合估计 —— XBTUSDTM,假想报价(每 5 秒、两侧、8 个距离、存活 10 秒);训练 / 验证 / 10 月")
    P(f"假想报价数:训练 {len(TR['di']):,}  验证 {len(VA['di']):,}  10 月 {len(OC['di']):,};1 tick = {TICK / bp_usd(TR):.4f} bp")
    days = {"训练": len(C.TRAIN_DAYS), "验证": len(C.VALID_DAYS), "10 月": 1.35}       # 10 月两天合计约 32.5 小时

    # ------------------------------------------------------------ 研究二:成交概率随距离
    P("\n[研究二-1] 10 秒内的成交概率(队首口径)与换算的成交强度 λ = −ln(1 − p) / 10 秒;距离 0 另列排队口径")
    P("    距离 tick(bp)      " + "".join(f"{d:>9d}" for d in DELTAS))
    P("                        " + "".join(f"{d * TICK / bp_usd(TR):>9.2f}" for d in DELTAS))
    lam_tr = None
    for seg, D in (("训练", TR), ("验证", VA), ("10 月", OC)):
        p = np.array([D["fillU"][D["di"] == i].mean() for i in range(len(DELTAS))])
        P(f"    {seg} 成交概率       " + "".join(f"{x:>9.4f}" for x in p) + f"   距离 0 排队口径 {D['fillQ'][D['di'] == 0].mean():.4f}")
        lam = -np.log(1 - p) / LIFE_S
        if seg == "训练":
            lam_tr = lam
        P(f"    {seg} λ(每小时)     " + "".join(f"{x * 3600:>9.1f}" for x in lam))
    d_usd = np.array(DELTAS, float) * TICK
    use = np.arange(1, len(DELTAS))                              # 拟合不含距离 0(排队位置不同)
    for name, x in (("指数 log λ ~ δ", d_usd[use]), ("幂律 log λ ~ log δ", np.log(d_usd[use]))):
        y = np.log(lam_tr[use])
        b = np.polyfit(x, y, 1)
        r2 = 1 - np.sum((y - np.polyval(b, x)) ** 2) / np.sum((y - y.mean()) ** 2)
        P(f"    训练段形状({name};距离 1–400 tick):斜率 {b[0]:+.4f},R² {r2:.3f}" + (f"  → κ = {-b[0]:.4f} /美元" if "指数" in name else ""))

    # 状态分组的边界(训练段)
    q_imb = np.quantile(TR["imb_s"], (0.2, 0.4, 0.6, 0.8))
    q_sig = np.quantile(TR["sig"], (1 / 3, 2 / 3))
    q_act = np.quantile(TR["act"], (1 / 3, 2 / 3))
    for D in (TR, VA, OC):
        D["b_imb"], D["b_sig"], D["b_act"] = np.digitize(D["imb_s"], q_imb), np.digitize(D["sig"], q_sig), np.digitize(D["act"], q_act)
    P("\n[研究二-2] 成交概率按状态(训练段;队首口径)。不平衡五分位:0 = 最不利于我方一侧(我方一侧量少),4 = 最有利")
    for key, lab, nb in (("b_imb", "不平衡", 5), ("b_sig", "σ_t", 3), ("b_act", "活跃度", 3)):
        for b in range(nb):
            m = TR[key] == b
            pr = [TR["fillU"][m & (TR["di"] == i)].mean() for i in range(len(DELTAS))]
            lam = -np.log(1 - np.clip(pr, 1e-9, 1 - 1e-9)) / LIFE_S
            y, x = np.log(lam[use]), d_usd[use]
            k = -np.polyfit(x, y, 1)[0]
            P(f"    {lab} {b}: " + "".join(f"{x_:>9.4f}" for x_ in pr) + f"   κ(状态)= {k:.4f} /美元")
    # 校准:训练段(距离 × 不平衡 × σ × 活跃度)格子的成交概率 → 验证段
    def cell(D):
        return (((D["di"].astype(int) * 5 + D["b_imb"]) * 3 + D["b_sig"]) * 3 + D["b_act"]).astype(int)
    ctr = cell(TR)
    ncell = len(DELTAS) * 45
    p_cell = np.bincount(ctr, weights=TR["fillU"], minlength=ncell) / np.maximum(np.bincount(ctr, minlength=ncell), 1)
    for seg, D in (("验证", VA), ("10 月", OC)):
        pred = p_cell[cell(D)]
        order = np.argsort(pred)
        parts = np.array_split(order, 10)
        P(f"\n[研究二-3] 校准({seg}):按预测成交概率分十组,预测 / 实际")
        P("    " + "  ".join(f"{pred[ix].mean():.3f}/{D['fillU'][ix].mean():.3f}" for ix in parts))
        base = (D["fillU"] - np.array([TR["fillU"][TR["di"] == i].mean() for i in range(len(DELTAS))])[D["di"].astype(int)]) ** 2
        P(f"    Brier 分数:状态模型 {np.mean((D['fillU'] - pred) ** 2):.5f};只按距离(基准的 λ(δ))的 {base.mean():.5f}")

    # ------------------------------------------------------------ 研究三:成交后的不利变动
    P("\n[研究三-1] 成交之后(队首口径的成交):不利变动 a_h 与每笔毛利 e_h(bp;e + 返佣 我方费率 = 每笔净值);括号内为按小时分块的 t")
    for seg, D in (("训练", TR), ("验证", VA), ("10 月", OC)):
        P(f"  {seg}")
        for i, d in enumerate(DELTAS):
            m = (D["di"] == i) & (D["fillU"] == 1)
            a = [block_stat(np.where(m, D[f"a{h}"], np.nan), D["hour"]) for h in HS]
            e = [block_stat(np.where(m, D[f"e{h}"], np.nan), D["hour"]) for h in HS]
            thr = D["through"][m].mean() if m.sum() else float("nan")
            P(f"    距离 {d:>3d}: n {int(m.sum()):>7,}  扫穿占比 {thr:.0%} | a1 {a[0][0]:+.2f}  a10 {a[1][0]:+.2f}  a60 {a[2][0]:+.2f} | e1 {e[0][0]:+.2f}  e10 {e[1][0]:+.2f}({e[1][1]:+.1f})  e60 {e[2][0]:+.2f}"
              f" | 每笔净值(10 s){e[1][0] + REBATE:+.2f} bp")
    P("\n[研究三-2] 训练段:按成交方式与方向(距离 0 与 20 tick;10 秒)")
    for i in (0, 3):
        for lab, m in (("买入报价", TR["side"] == 0), ("卖出报价", TR["side"] == 1), ("该档被扫穿", TR["through"] == 1), ("未扫穿(部分消耗)", TR["through"] == 0)):
            k = m & (TR["di"] == i) & (TR["fillU"] == 1)
            P(f"    距离 {DELTAS[i]:>3d} {lab:<10} n {int(k.sum()):>7,}  a1 {np.nanmean(TR['a1'][k]):+.2f}  a10 {np.nanmean(TR['a10'][k]):+.2f}  a60 {np.nanmean(TR['a60'][k]):+.2f}  e10 {np.nanmean(TR['e10'][k]):+.2f}  吃单张数中位 {np.nanmedian(TR['swq'][k]):.0f}")
    P("\n[研究三-3] 不利变动里已被 α̂ 解释的部分(成交时刻的 α̂;训练 / 验证),以及与币安成交前 1 秒变动的关系")
    for i in (0, 1, 3, 5):
        out = []
        for seg, D in (("训练", TR), ("验证", VA)):
            k = (D["di"] == i) & (D["fillU"] == 1) & np.isfinite(D["a10"]) & np.isfinite(D["alpha_adv"])
            share = D["alpha_adv"][k].sum() / D["a10"][k].sum()
            b = np.polyfit(D["alpha_adv"][k], D["a10"][k], 1)
            kk = k & np.isfinite(D["lead1"])
            rk = np.corrcoef(np.argsort(np.argsort(D["lead1"][kk])), np.argsort(np.argsort(D["a1"][kk])))[0, 1] if kk.sum() > 100 else float("nan")
            out.append(f"{seg}:a10 {D['a10'][k].mean():+.2f},α̂ 预言 {D['alpha_adv'][k].mean():+.2f}(占 {share:.0%}),a10 对 α̂ 的斜率 {b[0]:+.2f},残余 {D['a10'][k].mean() - D['alpha_adv'][k].mean():+.2f};与币安前 1 秒不利变动的秩相关(对 a1){rk:+.2f}")
        P(f"    距离 {DELTAS[i]:>3d} " + " | ".join(out))
    P("\n[研究三-4] 不利变动按放置时的状态(训练段,距离 0 / 20 tick,10 秒);每格:a10 / e10 + 返佣 / 成交概率")
    for i in (0, 3):
        for key, lab, nb in (("b_imb", "不平衡", 5), ("b_sig", "σ_t", 3), ("b_act", "活跃度", 3)):
            parts = []
            for b in range(nb):
                k0 = (TR["di"] == i) & (TR[key] == b)
                k = k0 & (TR["fillU"] == 1)
                parts.append(f"{b}: {np.nanmean(TR['a10'][k]):+.2f} / {np.nanmean(TR['e10'][k]) + REBATE:+.2f} / {TR['fillU'][k0].mean():.3f}")
            P(f"    距离 {DELTAS[i]:>3d} {lab}  " + "   ".join(parts))

    # ------------------------------------------------------------ 假设 (d):有没有样本外为正的区域
    P("\n[假设 d] 每笔净值 e10 + 我方费率 为正的(距离 × 不平衡 × σ × 活跃度)格子:训练段挑选(均值 > 0 且按小时 t ≥ 2),验证段只读一次")
    cells_tr, cells_va, cells_oc = cell(TR), cell(VA), cell(OC)
    picked, tested = [], 0
    for cidx in range(ncell):
        k = (cells_tr == cidx) & (TR["fillU"] == 1)
        if k.sum() < 100:
            continue
        tested += 1
        mu, t, n = block_stat(np.where(k, TR["e10"], np.nan) + REBATE, TR["hour"])
        if mu > 0 and t >= 2:
            picked.append((cidx, mu, t, n))
    P(f"    训练段成交数 ≥ 100 的格子 {tested} 个;其中均值 > 0 且 t ≥ 2 的 {len(picked)} 个(Bonferroni 门槛:单侧 p ≤ 0.05 / {tested})")
    usd_per_bp = ORDER_BTC * float(np.nanmean(TR["px"])) / 1e4       # 每单 0.2 BTC,1 bp 合多少美元
    tot = {"验证": [0.0, 0], "10 月": [0.0, 0]}
    for cidx, mu, t, n in sorted(picked, key=lambda x: -x[1] * x[3]):
        di, rest = divmod(cidx, 45)
        bi, rest = divmod(rest, 9)
        bs, ba_ = divmod(rest, 3)
        line = f"    距离 {DELTAS[di]:>3d} 不平衡{bi} σ{bs} 活跃{ba_}:训练 {mu:+.2f} bp(t {t:+.1f},n {n:,})"
        for seg, D, cc in (("验证", VA, cells_va), ("10 月", OC, cells_oc)):
            k = (cc == cidx) & (D["fillU"] == 1)
            m2, t2, n2 = block_stat(np.where(k, D["e10"], np.nan) + REBATE, D["hour"])
            line += f" | {seg} {m2:+.2f} bp(t {t2:+.1f},n {n2:,})"
            if n2 >= 30:
                tot[seg][0] += np.nansum(D["e10"][k] + REBATE)
                tot[seg][1] += n2
        P(line)
    for seg in ("验证", "10 月"):
        s, n = tot[seg]
        if n:
            # 假想报价每 5 秒放一组、存活 10 秒,同一时刻约有 2 张重叠;换算到"每侧同时只有一张"时成交数与金额各除以 2
            P(f"    {seg}合计(入选格子):成交 {n:,} 笔,每笔净值 {s / n:+.2f} bp;按每单 {ORDER_BTC} BTC、每侧同时一张折算:约 {n / 2 / days[seg]:.0f} 笔 / 天,${s / 2 * usd_per_bp / days[seg]:+.0f} / 天")
    P("\n    对照:不挑格子、全部状态,各距离每笔净值(验证段):" + "  ".join(
        f"{d}:{np.nanmean(VA['e10'][(VA['di'] == i) & (VA['fillU'] == 1)]) + REBATE:+.2f}" for i, d in enumerate(DELTAS)))
    open(os.path.join(OUT, "as_study_report.txt"), "w", encoding="utf8").write("\n".join(L))
    print("AS_REPORT_DONE", flush=True)


if __name__ == "__main__":
    build(sys.argv[2]) if sys.argv[1] == "build" else report()
