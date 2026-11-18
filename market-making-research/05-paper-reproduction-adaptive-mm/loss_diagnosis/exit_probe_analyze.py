"""出场探针分析(用户 2026-11-09 两问):
1. 成交之后 10–60 s 内用 maker 单出去的概率(只看能否成交;报价 = 不穿价的最激进价位,跟盘口重挂;见 exit_probe_run.py),
   以及因子库 own_taker_limit_slack(fill1s 入库)在探针发出时刻的值对"能否出去"的预测力(按五分位的成交概率、AUC)。
2. 60 s 内没出去的单子,不平会造成多少亏损:持仓时间 τ × 收益(bp 对名义额,USDC)曲线;另给 τ 时刻用市价单平掉的口径。
输入  out/P1_dt2000_XBTUSDCM/exit_probe/<day>_probes.csv、<day>_takers.npz;fills_attributed.csv;L3 中价 repro/data/step14/XBTUSDCM/dt2000/<day>_bbo.npz;
      50 ms 盘口 repro/data/step01/XBTUSDCM/<day>_HH.npz(τ 时刻的点差)。
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = r"主动做市策略"; REPRO = os.path.join(ROOT, "repro")
sys.path.insert(0, os.path.join(REPRO, "data")); import ladder_store as LS   # noqa: E402
BASE = os.path.join(ROOT, "loss_diagnosis", "out", "P1_dt2000_XBTUSDCM"); PD = os.path.join(BASE, "exit_probe")
SYM, TICK, MULT, NS, REB, TAKER = "XBTUSDCM", 0.1, 0.0001, 1_000_000_000, 1.2, 1.8
DAYS = ["20261001", "20261002", "20261013", "20261014", "20261015", "20261016", "20261017", "20261018", "20261019"]
TAUS = [1, 2, 5, 10, 20, 30, 45, 60]
CURVE_T = [0, 0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1800]
LAM = np.log(2.0) / 2000.0            # 因子原代码:半衰期 2000 ms
BLOCK = 30000.0


def decayed_at_events(v, x):
    """因子原代码 _decayed_at_events 的逐行照搬(v 毫秒升序,返回含第 k 个事件的指数衰减和)。"""
    n = len(v)
    if n == 0:
        return np.zeros(0)
    T0 = v[0]; b = np.floor((v - T0) / BLOCK).astype(np.int64); nb = int(b[-1]) + 1; Tb = T0 + b * BLOCK
    w = x * np.exp(LAM * (v - Tb)); cs = np.cumsum(w)
    starts = np.searchsorted(b, np.arange(nb), side="left"); ends = np.searchsorted(b, np.arange(nb), side="right")
    cs0 = np.concatenate([[0.0], cs]); base = cs0[starts]; blocksum = cs0[ends] - base; within = cs - base[b]
    C = np.zeros(nb); dec = np.exp(-LAM * BLOCK); c = 0.0
    for i in range(nb):
        C[i] = c; c = (c + blocksum[i]) * dec
    return (C[b] + within) * np.exp(-LAM * (v - Tb))


def factor_at(day, a_t_ms, a_side):
    """own_taker_limit_slack:a_side = +1 我方挂买单(被卖吃单打)、−1 我方挂卖单;原代码取 d == −s 的吃单。"""
    z = np.load(os.path.join(PD, f"{day}_takers.npz"), allow_pickle=True)
    tm = z["ts"].astype(np.float64) / 1e6; d = z["d"].astype(np.float64); tp = z["taker_px"]; px = z["fill_tick"].astype(np.float64) * TICK; oid = z["oid"]
    ok = np.isfinite(tp) & (tp != 0) & (z["fill_tick"] > 0)
    df = pd.DataFrame(dict(oid=oid[ok], tm=tm[ok], px=px[ok], tp=tp[ok], d=d[ok]))
    g = df.groupby(["oid", "tm"], sort=False).agg(d=("d", "first"), tp=("tp", "first"), pmax=("px", "max"), pmin=("px", "min"))
    gtm = g.index.get_level_values("tm").to_numpy().astype(np.float64); gd = g["d"].to_numpy(); tpx = g["tp"].to_numpy()
    plast = np.where(gd > 0, g["pmax"].to_numpy(), g["pmin"].to_numpy())
    slack = np.clip(np.nan_to_num(np.rint(gd * (tpx - plast) * 10.0), nan=0.0), 0.0, 10000.0)   # ×10 = 除以 tick 0.1(原代码)
    x = np.log1p(slack); v = gtm + 1.0
    val = np.full(len(a_t_ms), np.nan)
    for s in (1, -1):
        sel = (gd == -s) & np.isfinite(v); vs, xs = v[sel], x[sel]; o = np.argsort(vs, kind="mergesort"); vs, xs = vs[o], xs[o]
        am = a_side == s
        if len(vs) == 0 or not am.any():
            continue
        A = decayed_at_events(vs, xs); N = decayed_at_events(vs, np.ones_like(xs))
        ta = a_t_ms[am]; idx = np.searchsorted(vs, ta, side="right") - 1; okk = idx >= 0; ii = np.clip(idx, 0, len(vs) - 1)
        dec = np.exp(-LAM * (ta - vs[ii])); val[am] = np.where(okk, (A[ii] * dec) / (N[ii] * dec + 1.0), np.nan)
    return val


def auc(score, y):
    m = np.isfinite(score); s, y = score[m], y[m].astype(bool)
    if y.all() or (~y).all():
        return np.nan
    r = pd.Series(s).rank().to_numpy(); n1 = y.sum(); n0 = (~y).sum()
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def main():
    F = pd.read_csv(os.path.join(BASE, "fills_attributed.csv"), dtype={"day": str}); F["row"] = np.arange(len(F))
    P = pd.concat([pd.read_csv(os.path.join(PD, f"{d}_probes.csv")) for d in DAYS], ignore_index=True)
    D = F.merge(P.drop(columns=["qty"]), on="row", how="inner", validate="one_to_one")
    D["t_full_s"] = (D.full_fill_ts - D.start_ts) / 1e9; D["t_first_s"] = (D.first_fill_ts - D.start_ts) / 1e9
    valid = (~D.interrupted) & (D.end_reason != "censored")
    print(f"探针 {len(D):,} 笔(= P1 2000 ms 9 天全部 maker 成交);有效 {valid.sum():,};断流 {int(D.interrupted.sum())};日末截尾 {int((D.end_reason == 'censored').sum())}")
    V = D[valid].copy(); w = V.notional.values
    # 因子
    V["factor"] = np.nan
    for day in DAYS:
        m = V.day == day
        if not m.any():
            continue
        a_side = np.where(V.loc[m, "exit_side"].values == 0, 1, -1)            # 引擎 side 0 = 挂买单 → 因子 s = +1
        V.loc[m, "factor"] = factor_at(day, V.loc[m, "start_ts"].values / 1e6, a_side)
    # 报价位置 / 出场价相对中价
    V["mode"] = V.first_mode
    ex_px = V.exit_vwap_tick * TICK
    V["exit_vs_mid_bp"] = np.where(V.filled_qty > 0, -V.side * (ex_px - V.mf) / V.price * 1e4, np.nan)   # 出场价相对"开仓成交时刻中价"的有利程度(正 = 有利)
    V["rt_bp"] = np.where(V.filled_qty >= V.qty, V.side * (V.price - ex_px) / V.price * 1e4, np.nan)       # 一进一出价差(不含返佣)
    # ---------------- 1. 成交概率 ----------------
    print("\n## 1. 出场 maker 单在 τ 秒内全部成交的概率(按笔 / 按名义额;报价 = 不穿价最激进价位,跟盘口重挂)")
    print("| τ | 全部成交 按笔 | 按名义额 | 至少部分成交 按笔 |\n|---|---|---|---|")
    rows = []
    for tau in TAUS:
        full = (V.t_full_s <= tau).values; part = (V.t_first_s <= tau).values
        rows.append(dict(tau=tau, p_full=full.mean(), p_full_w=np.average(full, weights=w), p_part=part.mean()))
        print(f"| {tau} s | {full.mean():.1%} | {np.average(full, weights=w):.1%} | {part.mean():.1%} |")
    pd.DataFrame(rows).to_csv(os.path.join(PD, "exit_prob_curve.csv"), index=False)
    print(f"\n全部成交用时 p50 / p90 / p99 = {np.nanpercentile(V.t_full_s, 50):.1f} / {np.nanpercentile(V.t_full_s, 90):.1f} / {np.nanpercentile(V.t_full_s, 99):.1f} s(只算 60 s 内成交的)")
    print(f"首挂方式:改善 1 tick {np.mean(V['mode'] == 'improve'):.1%},加入最优价 {np.mean(V['mode'] == 'join'):.1%};每笔重挂次数 p50 / p90 = {V.n_repeg.median():.0f} / {V.n_repeg.quantile(0.9):.0f}")
    print("\n逐日(按笔):\n| 日 | 笔数 | 10 s | 30 s | 60 s | 60 s 未出完 |\n|---|---|---|---|---|---|")
    for day, g in V.groupby("day"):
        print(f"| {day} | {len(g):,} | {(g.t_full_s <= 10).mean():.1%} | {(g.t_full_s <= 30).mean():.1%} | {(g.t_full_s <= 60).mean():.1%} | {(~(g.t_full_s <= 60)).sum():,} |")
    print("\n按出场方向 / 开仓时点差(按笔):\n| 组 | 笔数 | 10 s | 60 s |\n|---|---|---|---|")
    for lab, m in (("多头出场(挂卖)", V.exit_side == 1), ("空头出场(挂买)", V.exit_side == 0)):
        g = V[m]; print(f"| {lab} | {len(g):,} | {(g.t_full_s <= 10).mean():.1%} | {(g.t_full_s <= 60).mean():.1%} |")
    for b, g in V.groupby(pd.qcut(V.spread0, 4, duplicates="drop"), observed=True):
        print(f"| 发单时点差 {b} tick | {len(g):,} | {(g.t_full_s <= 10).mean():.1%} | {(g.t_full_s <= 60).mean():.1%} |")
    # 因子
    print(f"\n## 1b. 因子 own_taker_limit_slack(fill1s 入库;发单时刻,出场方向)对能否出去的预测力")
    f = V.factor.values; print(f"有值 {np.isfinite(f).mean():.1%};分位 p10/p50/p90 = {np.nanpercentile(f, 10):.3f} / {np.nanpercentile(f, 50):.3f} / {np.nanpercentile(f, 90):.3f}")
    print("| 因子五分位 | 笔数 | 1 s 内成交 | 10 s | 30 s | 60 s | 全部成交用时 p50 s |\n|---|---|---|---|---|---|---|")
    fq = pd.qcut(V.factor, 5, duplicates="drop")
    for b, g in V.groupby(fq, observed=True):
        print(f"| {b} | {len(g):,} | {(g.t_full_s <= 1).mean():.1%} | {(g.t_full_s <= 10).mean():.1%} | {(g.t_full_s <= 30).mean():.1%} | {(g.t_full_s <= 60).mean():.1%} | {g.t_full_s.median():.1f} |")
    for tau in (1, 10, 60):
        y = (V.t_full_s <= tau).values
        print(f"AUC(因子 → {tau} s 内全部成交)= {auc(f, y):.3f}(0.5 = 无预测力);对照:发单时点差的 AUC = {auc(V.spread0.values.astype(float), y):.3f}")
    # 出场代价(用户说不考虑,单列备查)
    print(f"\n备查(用户说不考虑价差):出场成交价相对开仓成交时刻中价 按量加权 {np.nanmean(V.exit_vs_mid_bp):+.2f} bp;一进一出价差(全部出完的)按量加权 {np.average(V.rt_bp[np.isfinite(V.rt_bp)], weights=w[np.isfinite(V.rt_bp)]):+.2f} bp,"
          f"加两次返佣 {np.average(V.rt_bp[np.isfinite(V.rt_bp)], weights=w[np.isfinite(V.rt_bp)]) + 2 * REB:+.2f} bp")

    # ---------------- 2. 持仓时间 × 收益 ----------------
    print("\n## 2. 持仓时间 τ × 收益(不平仓、按中价计价;bp 对开仓名义额;正 = 赚)")
    cur = {t: np.full(len(V), np.nan) for t in CURVE_T}; hs60 = np.full(len(V), np.nan)
    for day in DAYS:
        m = (V.day == day).values
        if not m.any():
            continue
        b = np.load(os.path.join(REPRO, "data", "step14", SYM, "dt2000", f"{day}_bbo.npz")); bts, bmid = b["ts"].astype(np.int64), b["mid2"] / 2.0 * TICK
        ts = V.ts.values[m].astype(np.int64); p = V.price.values[m]; sd = V.side.values[m]
        for t in CURVE_T:
            tt = ts + int(t * NS); j = np.searchsorted(bts, tt, side="right") - 1
            ok = (j >= 0) & (tt <= bts[-1]) & ((tt - bts[np.clip(j, 0, len(bts) - 1)]) < 300 * NS)
            mh = bmid[np.clip(j, 0, len(bmid) - 1)]
            cur[t][np.where(m)[0]] = np.where(ok, sd * (p - mh) / p * 1e4, np.nan)
        lt, lad = [], []
        for pth in sorted(glob.glob(os.path.join(REPRO, "data", "step01", SYM, f"{day}_*.npz"))):
            z = LS.load(pth, keys=("bnd_ts", "bnd_lad")); lt.append(z["bnd_ts"]); lad.append(z["bnd_lad"][:, :, 0, 0])
        lt = np.concatenate(lt).astype(np.int64); top = np.concatenate(lad)
        k = np.clip(np.searchsorted(lt, ts + 60 * NS, side="right") - 1, 0, len(lt) - 1)
        hs60[np.where(m)[0]] = (top[k, 1] - top[k, 0]) * TICK / 2 / p * 1e4
    groups = {"60 s 内全部出去": (V.t_full_s <= 60).values, "60 s 内没出完": ~(V.t_full_s <= 60).values, "全部": np.ones(len(V), bool)}
    print("| 组 | 笔数 | 名义额 | " + " | ".join(f"{t:g} s" for t in CURVE_T) + " |")
    print("|---|---|---|" + "---|" * len(CURVE_T))
    curve_rows = []
    for lab, m in groups.items():
        cells = []
        for t in CURVE_T:
            x = cur[t][m]; ok = np.isfinite(x)
            v = np.average(x[ok], weights=w[m][ok]) if ok.any() else np.nan
            cells.append(v); curve_rows.append(dict(group=lab, tau_s=t, bp=v, n=int(ok.sum())))
        print(f"| {lab} | {m.sum():,} | ${w[m].sum():,.0f} | " + " | ".join(f"{c:+.2f}" for c in cells) + " |")
    CR = pd.DataFrame(curve_rows); CR.to_csv(os.path.join(PD, "holding_curve.csv"), index=False)
    nm = groups["60 s 内没出完"]; x60 = cur[60][nm]; ok = np.isfinite(x60)
    usd60 = np.nansum(x60 * w[nm] / 1e4)
    print(f"\n60 s 内没出完的 {nm.sum():,} 笔(名义 ${w[nm].sum():,.0f}):持有到 60 s 按中价 {np.average(x60[ok], weights=w[nm][ok]):+.2f} bp = {usd60:+.1f} USDC;"
          f"60 s 时市价平掉(− 半点差 {np.nanmedian(hs60[nm]):.2f} bp 中位 − taker 我方费率)= {np.average((x60 - hs60[nm] - TAKER)[ok & np.isfinite(hs60[nm])], weights=w[nm][ok & np.isfinite(hs60[nm])]):+.2f} bp "
          f"= {np.nansum((x60 - hs60[nm] - TAKER) * w[nm] / 1e4):+.1f} USDC;加开仓返佣 我方费率 后 {np.average((x60 - hs60[nm] - TAKER)[ok & np.isfinite(hs60[nm])], weights=w[nm][ok & np.isfinite(hs60[nm])]) + REB:+.2f} bp")
    print(f"60 s 时亏损(按中价 < 0)的占比 {np.average(x60[ok] < 0, weights=w[nm][ok]):.0%};最差 1% 笔 {np.nanpercentile(x60, 1):+.1f} bp")
    for lab, m in groups.items():
        x = cur[60][m]; print(f"  {lab}:60 s 按中价分位 p10 / p50 / p90 = {np.nanpercentile(x, 10):+.1f} / {np.nanpercentile(x, 50):+.1f} / {np.nanpercentile(x, 90):+.1f} bp")
    # 图
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    ax = axes[0]
    pc = pd.DataFrame(rows); ax.plot(pc.tau, pc.p_full * 100, "o-", label="全部成交(按笔)"); ax.plot(pc.tau, pc.p_part * 100, "s--", label="至少部分成交")
    for b, g in V.groupby(fq, observed=True):
        ax.plot(TAUS, [(g.t_full_s <= t).mean() * 100 for t in TAUS], lw=0.8, alpha=0.7, label=f"因子 {b}")
    ax.set_xlabel("开仓成交后 τ(s)"); ax.set_ylabel("出场 maker 单已成交 %"); ax.set_title("1. 出场 maker 单成交概率(最激进不穿价报价,跟盘口)"); ax.grid(alpha=0.3); ax.legend(fontsize=7)
    ax = axes[1]
    for lab in groups:
        g = CR[CR.group == lab]; ax.plot(np.maximum(g.tau_s, 0.05), g.bp, "o-", label=f"{lab}(按中价)")
    ax.axhline(0, color="k", lw=0.8); ax.axhline(-REB, color="grey", ls=":", lw=0.8, label="我方费率(返佣能抵的亏损)")
    ax.set_xscale("log"); ax.set_xlabel("持仓时间 τ(s,对数轴;0 画在 0.05)"); ax.set_ylabel("bp(按开仓名义额加权,不含返佣)")
    ax.set_title("2. 持仓时间 × 收益:不平仓按中价计价"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(os.path.join(PD, "fig_exit_prob_and_holding_curve.png"), dpi=130); plt.close(fig)
    V.to_csv(os.path.join(PD, "probes_merged.csv"), index=False)
    print("\nDONE")


if __name__ == "__main__":
    main()
