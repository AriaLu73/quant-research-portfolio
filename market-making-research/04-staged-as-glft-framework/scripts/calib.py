#!/usr/bin/env python3
"""research7 阶段 1:基准模型的参数校准与 AS 假设的三项检验。

用途      从逐笔委托重建的买一卖一与吃单(data/research7/market)估计 σ、λ(δ)、A、κ,由风险预算反推 γ,
          并检验:① 成交频率与 δ 是否近似指数关系 ② 成交之后价格是否无漂移 ③ σ 是否稳定。
所属阶段  阶段 1(<基准阶段的任务> 第 1、2 条)。
对应公式  估计 GLFT 公式中的 σ、A、κ、γ(全部为常数)。
变量与 <符号表> 的对应
          sigma = σ(美元 / √秒);lam[d] = λ̂(δ)(1 / 秒);A、k = A、κ;gamma = γ;
          eps = ε(假想买入报价被触及 +1,卖出报价被触及 −1);m0 = m_0;mh = m_h
依据      M-102(σ:提示词规定"由中间价收益估计";单位取价格差分,L02 图注)、
          M-103(λ̂ 与 A、κ:L04 §4.4.2 式 (4.12)、Definition 1、Proposition 6,丙类)、
          M-104(γ:glft.gamma_from_budget,推导依据)、M-005(Newey–West)。
预登记    docs/research7/00_范围_阈值_预登记.md 第 5 节(本文件的常数都来自那张表)。
用法      .venv/Scripts/python.exe scripts/research7/calib.py            (10-01 逐笔委托版)
          .venv/Scripts/python.exe scripts/research7/calib.py l2train    (8–9 月训练段,L2 重建版)
"""
import glob
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glft as G

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MKT = os.path.join(ROOT, "data", "research7", "market")
OUT = os.path.join(ROOT, "data", "research7", "calib")
SYM = "XBTUSDTM"
TICK, NS = 0.1, 10**9                       # 美元 / tick(合约接口存档 2026-10-02);纳秒 / 秒
CAL_DAY, OTHER_DAY = "20261001", "20261002"  # 预登记:10-01 校准;10-02 只用来报告参数是否稳定,不参与校准
DT_S = 60                                    # 窗口 ΔT(秒):L04 §4.6.3 "We consider T = 60s"
DELTAS = (0.5, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48)   # δ 网格(美元):预登记,ASSUMPTION
MIN_HITS = 30                                # 参与拟合的最少被触及次数:预登记,ASSUMPTION
HORIZONS = (0.1, 1.0, 10.0, 60.0)            # 成交后漂移的时间窗(秒):提示词 <markout与P&L归因>
ORDER_BTC = 0.2                              # Δ:项目记录(预登记)
BUDGET_USD_DAY = 100.0                       # 库存盈亏日波动目标:项目记录 + ASSUMPTION(预登记)
GAP_S = 5                                    # 买一卖一超过这么久没有变化视为数据空档(断流 / 预热):
                                             # 数据估计:正常时每秒变化 30–80 次(market 文件行数 / 3600),5 秒无变化不可能是正常行情;ASSUMPTION
NW_LAG = 1                                   # Newey–West 滞后(小时块):预登记,ASSUMPTION


def load_hours(day):
    """读某天全部小时文件 → [(小时标签, bbo, sw)]。bbo [n,5]、sw [m,6] 的列见 l3_prep.py。"""
    out = []
    for f in sorted(glob.glob(os.path.join(MKT, f"{SYM}_{day}_??.npz"))):
        z = np.load(f)
        if len(z["bbo"]) > 1000:
            out.append((os.path.basename(f)[-6:-4], z["bbo"], z["sw"]))
    return out


MKT_L2 = os.path.join(ROOT, "data", "research7", "market_l2")
# 8–9 月的样本划分(预登记第 2 节):训练 08-26 … 09-07,验证 09-10 … 09-24
TRAIN_DAYS = ("20260826", "20260827", "20260828", "20260829", "20260830", "20260831", "20260901", "20260902", "20260903",
              "20260904", "20260905", "20260906", "20260907")
VALID_DAYS = ("20260910", "20260911", "20260914", "20260917", "20260918", "20260923", "20260924")


def load_l2_days(days):
    """读若干天由 L2 重建的买一卖一与吃单(l2_market.py),按整点切成小时块 → [(日期+小时, bbo, sw)],格式同 load_hours。"""
    out = []
    for day in days:
        z = np.load(os.path.join(MKT_L2, f"{SYM}_{day}.npz"))
        b, w = z["bbo"], z["sw"]
        hb, hw = b[:, 0] // (3600 * NS), w[:, 0] // (3600 * NS)
        for h in np.unique(hb):
            bb = b[hb == h]
            if len(bb) > 1000:
                out.append((f"{day}_{int(h % 24):02d}", bb, w[hw == h]))
    return out


def good_seconds(bbo):
    """可用的整秒:该秒及其前 1 秒内盘口数据没有空档。返回 (秒序号数组, 每秒末的中间价 美元)。
    每秒末的中间价 = 该秒结束之前最后一次买一卖一变化的值(只用过去的数据)。"""
    t, mid = bbo[:, 0], (bbo[:, 1] + bbo[:, 2]) / 2.0 * TICK
    s0, s1 = int(t[0] // NS) + 1, int(t[-1] // NS)
    sec = np.arange(s0, s1)
    i = np.searchsorted(t, (sec + 1) * NS, side="left") - 1          # 每秒末之前最后一行
    age = (sec + 1) * NS - t[i]                                        # 这个值有多旧(纳秒)
    ok = age < GAP_S * NS
    return sec[ok], mid[i][ok]


def sigma_from_mid(sec, mid, step=1):
    """σ(美元 / √秒):间隔 step 秒的中间价差分的标准差 / √step。只用相邻(恰好相隔 step 秒)的两个可用秒。"""
    j = np.arange(0, len(sec) - step, step)
    m = (sec[j + step] - sec[j]) == step
    d = (mid[j + step] - mid[j])[m]
    return (float(np.sqrt(np.mean(d * d)) / math.sqrt(step)), int(m.sum())) if m.sum() > 10 else (float("nan"), 0)


def touches(bbo, sw):
    """等待时间样本(L04 §4.4.2)。每 ΔT 秒一个窗口,窗口起点中间价 ± δ 处各放一张固定价格的假想报价。
    返回 rows:[窗口起点秒, side(0 买 1 卖), δ 下标, 等待时间(秒,未触及 = ΔT), 是否触及, 触及时刻纳秒, m_0, 报价价格]
    "触及":对侧吃单的最差成交价到达或越过报价价格(项目口径:等于或穿过都算;没有队列信息,这是"被触及"不是"成交")。
    没有用未来数据:报价价格只由窗口起点的中间价决定。"""
    t, mid = bbo[:, 0], (bbo[:, 1] + bbo[:, 2]) / 2.0 * TICK
    gap_after = np.r_[np.diff(t), 0] > GAP_S * NS                      # 这一行之后出现空档
    rows = []
    w0 = (int(t[0] // NS) // DT_S + 1) * DT_S
    for start in range(w0, int(t[-1] // NS) - DT_S, DT_S):
        a, b = np.searchsorted(t, [start * NS, (start + DT_S) * NS])
        if a == 0 or gap_after[a - 1:b].any():
            continue                                                   # 窗口里有数据空档:不用
        s0 = mid[a - 1]                                                # 窗口起点的中间价 S_0
        i0, i1 = np.searchsorted(sw[:, 0], [start * NS, (start + DT_S) * NS])
        w = sw[i0:i1]
        for side in (0, 1):
            ws = w[w[:, 1] == side]
            worst = ws[:, 4] * TICK                                    # 吃单打到的最差价格(美元)
            for di, d in enumerate(DELTAS):
                px = s0 - d if side == 0 else s0 + d
                hit = np.nonzero(worst <= px if side == 0 else worst >= px)[0]
                if len(hit):
                    th = int(ws[hit[0], 0])
                    m0 = mid[np.searchsorted(t, th, side="left") - 1]  # 这张吃单到达之前的中间价
                    rows.append((start, side, di, (th - start * NS) / NS, 1, th, m0, px))
                else:
                    rows.append((start, side, di, float(DT_S), 0, 0, np.nan, px))
    return np.asarray(rows, float)


def lam_hat(R):
    """式 (4.12):λ̂(δ) = Σ 1{X < ΔT} / Σ X。返回 (λ̂[len(DELTAS)](1/秒), 被触及次数)。"""
    lam, n = np.full(len(DELTAS), np.nan), np.zeros(len(DELTAS), int)
    for di in range(len(DELTAS)):
        r = R[R[:, 2] == di]
        if len(r):
            n[di] = int(r[:, 4].sum())
            lam[di] = r[:, 4].sum() / r[:, 3].sum()
    return lam, n


def log_phi_int(k, sigma):
    """Proposition 6(布朗运动):∫₀^ΔT φ(κ, ξ) dξ = 2/(κ²σ²) · (e^{κ²σ²ΔT/2} − 1) 的自然对数(∫ 的单位:秒)。
    直接算指数会溢出(κ²σ²ΔT/2 可达几百),所以在对数里算:log(2/x) + xΔT/2 + log(1 − e^{−xΔT/2}),x = κ²σ²。"""
    x = k * k * sigma * sigma
    if x * DT_S < 1e-9:
        return math.log(DT_S)
    return math.log(2.0 / x) + x * DT_S / 2.0 + math.log1p(-math.exp(-x * DT_S / 2.0))


def fit_A_k(lam, n, sigma, plain=False):
    """Definition 1 的最小二乘:min Σ_δ ( log Λ̂(δ) + κδ − log A − log ∫φ )²,Λ̂(δ) = λ̂(δ)·ΔT(每窗口的期望次数)。
    对给定 κ,log A 的最优值有解析式(残差均值为 0);κ 在网格上搜索后黄金分割细化。
    plain=True:去掉参考价移动修正项(log ∫φ 换成 log ΔT),即直接对 log λ̂ 做线性回归 —— 只作对照,说明修正项的影响。
    返回 dict(A, k, r2, resid[δ])。只用被触及次数 ≥ MIN_HITS 的 δ。"""
    use = (n >= MIN_HITS) & np.isfinite(lam) & (lam > 0)
    d, y = np.asarray(DELTAS, float)[use], np.log(lam[use] * DT_S)

    def sse(k):
        c = math.log(DT_S) if plain else log_phi_int(k, sigma)
        z = y + k * d - c
        return float(np.sum((z - z.mean()) ** 2)), float(z.mean())

    ks = np.geomspace(1e-4, 5.0, 400)
    k0 = ks[int(np.argmin([sse(k)[0] for k in ks]))]
    lo, hi = k0 / 1.3, k0 * 1.3
    for _ in range(80):                                                # 黄金分割
        a, b = hi - 0.618 * (hi - lo), lo + 0.618 * (hi - lo)
        if sse(a)[0] < sse(b)[0]:
            hi = b
        else:
            lo = a
    k = (lo + hi) / 2
    s, logA = sse(k)
    sst = float(np.sum((y - y.mean()) ** 2))
    c = math.log(DT_S) if plain else log_phi_int(k, sigma)
    resid = np.full(len(DELTAS), np.nan)
    resid[use] = y - (logA - k * d + c)
    return dict(A=math.exp(logA), k=k, r2=1.0 - s / sst if sst > 0 else float("nan"), resid=resid.tolist(), n_used=int(use.sum()))


def nw_t(x, lag=NW_LAG):
    """块均值序列 x 的均值及其 Newey–West t 值(Bartlett 核,L14 工作论文式 (4) 之后的加权形式)。"""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan"), float("nan"), n
    e = x - x.mean()
    v = float(e @ e) / n
    for j in range(1, min(lag, n - 1) + 1):
        v += 2.0 * (1.0 - j / (lag + 1.0)) * float(e[j:] @ e[:-j]) / n
    return float(x.mean()), float(x.mean() / math.sqrt(max(v, 1e-300) / n)), n


def drift_after_touch(hours):
    """检验"成交之后价格无漂移":对每次触及,ε·(m_h − m_0)(美元);按 δ、按 h,用小时块均值做 t 检验。
    hours: [(标签, bbo, R)]。返回 {δ下标: {h: (均值 美元, t, 小时数, 触及次数)}}。"""
    out = {}
    for di in range(len(DELTAS)):
        out[di] = {}
        for h in HORIZONS:
            blocks, cnt = [], 0
            for _, bbo, R in hours:
                r = R[(R[:, 2] == di) & (R[:, 4] == 1)]
                if not len(r):
                    continue
                t, mid = bbo[:, 0], (bbo[:, 1] + bbo[:, 2]) / 2.0 * TICK
                th = r[:, 5].astype(np.int64) + int(h * NS)
                ok = th < t[-1]
                mh = mid[np.searchsorted(t, th[ok], side="right") - 1]
                eps = np.where(r[ok, 1] == 0, 1.0, -1.0)
                x = eps * (mh - r[ok, 6])
                if len(x):
                    blocks.append(float(x.mean()))
                    cnt += len(x)
            out[di][h] = (*nw_t(blocks), cnt)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    res, L = {}, []
    P = lambda s="": (L.append(s), print(s, flush=True))
    global CAL_DAY, OTHER_DAY
    l2 = len(sys.argv) > 1 and sys.argv[1] == "l2train"
    if l2:
        # 第二种用法:用 8–9 月训练段(L2 重建)校准,验证段只用来报告参数是否稳定。输出 baseline_params_train.json
        CAL_DAY, OTHER_DAY = "train", "valid"
        data = {"train": load_l2_days(TRAIN_DAYS), "valid": load_l2_days(VALID_DAYS)}
    else:
        data = {d: load_hours(d) for d in (CAL_DAY, OTHER_DAY)}
    px = float(np.mean([(b[:, 1] + b[:, 2]).mean() / 2 * TICK for _, b, _ in data[CAL_DAY]]))
    bp = px / 1e4                                                     # 1 bp 合多少美元(只用于把结果换算成 bp 展示)
    P(f"阶段 1 校准(XBTUSDTM;校准日 {CAL_DAY},{len(data[CAL_DAY])} 个小时;均价 ${px:,.0f},1 bp = ${bp:.2f})")

    # ---------- σ 与检验 ③
    P("\n[σ] 中间价差分的标准差(美元 / √秒);括号内为 bp / √秒")
    sig_h = {}
    for day in (CAL_DAY, OTHER_DAY):
        allsec = [good_seconds(b) for _, b, _ in data[day]]
        hs = [sigma_from_mid(s, m)[0] for s, m in allsec]
        sig_h[day] = hs
        pooled = math.sqrt(np.nanmean(np.square(hs)))
        sign = {st: math.sqrt(np.nanmean([sigma_from_mid(s, m, st)[0] ** 2 for s, m in allsec])) for st in (1, 10, 60)}
        P(f"  {day}: 全天 σ = {pooled:.3f}({pooled / bp:.3f} bp);逐小时 最小 {np.nanmin(hs):.3f} 中位 {np.nanmedian(hs):.3f} 最大 {np.nanmax(hs):.3f};"
          f"变异系数 {np.nanstd(hs, ddof=1) / np.nanmean(hs):.2f};不同采样间隔的 σ:1 s {sign[1]:.3f} / 10 s {sign[10]:.3f} / 60 s {sign[60]:.3f}")
        res[f"sigma_{day}"] = pooled
        res[f"sigma_cv_{day}"] = float(np.nanstd(hs, ddof=1) / np.nanmean(hs))
    sigma = res[f"sigma_{CAL_DAY}"]
    cv = res[f"sigma_cv_{CAL_DAY}"]
    P(f"  检验 ③(σ 稳定:逐小时变异系数 ≤ 0.30):校准日 {cv:.2f} → {'成立' if cv <= 0.30 else '不成立'};"
      f"另一天 {res[f'sigma_cv_{OTHER_DAY}']:.2f};两天全天 σ 之比 {res[f'sigma_{OTHER_DAY}'] / sigma:.2f}")

    # ---------- λ̂(δ)、A、κ 与检验 ①
    T = {day: [(lab, b, touches(b, s)) for lab, b, s in data[day]] for day in data}
    P("\n[λ(δ)] 等待时间估计量(L04 式 4.12),ΔT = 60 s,买卖两侧合并;每侧每个 δ 的窗口数 = n_win")
    fits = {}
    for day in (CAL_DAY, OTHER_DAY):
        R = np.vstack([r for _, _, r in T[day] if len(r)])
        lam, n = lam_hat(R)
        nwin = int((R[:, 2] == 0).sum())
        sg = res[f"sigma_{day}"]
        f1, f0 = fit_A_k(lam, n, sg), fit_A_k(lam, n, sg, plain=True)
        fits[day] = (lam, n, f1, f0)
        P(f"  {day}(假想报价 {nwin} 张):")
        P("     δ 美元   " + "".join(f"{d:>8g}" for d in DELTAS))
        P("     δ bp     " + "".join(f"{d / bp:8.2f}" for d in DELTAS))
        P("     触及次数 " + "".join(f"{x:8d}" for x in n))
        P("     λ̂ 每小时 " + "".join(f"{x * 3600:8.1f}" for x in lam))
        P("     拟合残差 " + "".join(f"{x:8.2f}" if x == x else "       ." for x in f1["resid"]) + "   (log 单位;正 = 实际比指数模型多)")
        P(f"     Definition 1 拟合:A = {f1['A']:.4f} /s({f1['A'] * 3600:.0f} /h),κ = {f1['k']:.4f} /美元({f1['k'] * bp:.3f} /bp,1/κ = {1 / f1['k']:.2f} 美元 = {1 / f1['k'] / bp:.2f} bp),R² = {f1['r2']:.3f},用了 {f1['n_used']} 个 δ")
        P(f"     对照(不做参考价移动修正的直接对数线性回归):A = {f0['A']:.4f} /s,κ = {f0['k']:.4f},R² = {f0['r2']:.3f}")
    lam, n, f1, f0 = fits[CAL_DAY]
    A, k = f1["A"], f1["k"]
    P(f"  检验 ①(指数关系):校准日 R² = {f1['r2']:.3f};残差随 δ 的形状见上行(系统性弯曲 = 不是指数)。正式拟合优度检验无理论依据,不下显著性结论。")
    kk = [fit_A_k(*lam_hat(r), sigma)["k"] for _, _, r in T[CAL_DAY] if len(r) and (lam_hat(r)[1] >= MIN_HITS).sum() >= 3]
    if len(kk) > 2:
        P(f"  κ 逐小时(校准日,能拟合的 {len(kk)} 个小时):最小 {min(kk):.4f} 中位 {np.median(kk):.4f} 最大 {max(kk):.4f},变异系数 {np.std(kk, ddof=1) / np.mean(kk):.2f}")
    P(f"  另一天的 A / κ 相对校准日:A × {fits[OTHER_DAY][2]['A'] / A:.2f},κ × {fits[OTHER_DAY][2]['k'] / k:.2f}")

    # ---------- 检验 ②:成交后漂移
    P("\n[检验 ②] 假想报价被触及之后的价格漂移 ε·(m_h − m_0)(bp;负 = 对做市商不利);括号内 t(小时块,Newey–West 滞后 1)/ 触及次数")
    dr = drift_after_touch(T[CAL_DAY])
    for di, d in enumerate(DELTAS):
        if n[di] >= MIN_HITS:
            P(f"   δ {d:>4g} 美元({d / bp:.2f} bp): " + "   ".join(f"{h:g}s {dr[di][h][0] / bp:+.2f}(t {dr[di][h][1]:+.1f} / {dr[di][h][3]})" for h in HORIZONS))
    bad = [(d, h) for di, d in enumerate(DELTAS) for h in HORIZONS if n[di] >= MIN_HITS and abs(dr[di][h][1]) >= 2]
    P(f"   判定(|t| ≥ 2 判不成立):{len(bad)} / {sum(1 for x in n if x >= MIN_HITS) * len(HORIZONS)} 个(δ, h)组合不成立")

    # ---------- γ 与基准报价
    P("\n[γ] 由风险预算反推(M-104)")
    target_btc = BUDGET_USD_DAY / (sigma * math.sqrt(86400.0))        # 库存盈亏日波动 = std(q)·σ·√86400 → std(q)
    gamma = G.gamma_from_budget(target_btc, k, ORDER_BTC, sigma, A)
    qmax_orders = max(1, math.ceil(4.0 * target_btc / ORDER_BTC))      # 预登记:4 倍目标标准差,向上取整,至少 1 张
    for name, g in (("基准", gamma), ("γ × 0.1", gamma * 0.1), ("γ × 10", gamma * 10)):
        c, w = G.c1(g, k, ORDER_BTC), G.skew_per_order(g, k, ORDER_BTC, sigma, A)
        P(f"   {name}: γ = {g:.3e} /美元,γΔ/κ = {g * ORDER_BTC / k:.3e};半价差 c1 = {c:.2f} 美元({c / bp:.2f} bp);每张单的倾斜 w = {w:.3f} 美元({w / bp:.3f} bp);"
          f"模型内库存标准差 {G.inventory_std_orders(g, k, ORDER_BTC, sigma, A):.2f} 张;空仓时两侧各 {c + w / 2:.2f} 美元({(c + w / 2) / bp:.2f} bp),模型内成交强度 {A * math.exp(-k * (c + w / 2)) * 3600:.1f} 张 / 小时 / 侧")
    P(f"   目标库存标准差 {target_btc:.4f} BTC = {target_btc / ORDER_BTC:.2f} 张;库存上限 {qmax_orders} 张")
    res.update(sigma=sigma, A=A, k=k, gamma=gamma, order_btc=ORDER_BTC, qmax_orders=qmax_orders, target_std_btc=target_btc,
               px=px, r2=f1["r2"], A_plain=f0["A"], k_plain=f0["k"])
    tag = "_train" if l2 else ""                              # 两种用法各写各的文件,互不覆盖
    json.dump(res, open(os.path.join(OUT, f"baseline_params{tag}.json"), "w"), indent=1)
    open(os.path.join(OUT, f"calib_report{tag}.txt"), "w", encoding="utf8").write("\n".join(L))
    print("CALIB_DONE", flush=True)


if __name__ == "__main__":
    main()
