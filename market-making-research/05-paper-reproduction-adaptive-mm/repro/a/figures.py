"""Part A 图:Figure 3(单区间需求与线性拟合)、Figure 6(某日平均需求曲线 + 日均 (c,p) 直线)、Figure 4(π± 对 g3 状态)、Figure 5(移动平均对比)。
用法  python figures.py fig3 <sym> <day> <dt_ms> <V_LO> [k]      → reports/step02/fig3_<sym>_<day>_k<k>.png
      python figures.py fig6 <sym> <day> <dt_ms> <V_LO>          → reports/step02/fig6_<sym>_<day>.png
      python figures.py fig4 <sym> <dt_ms> <day_from> <day_to>   → reports/step04/fig4_<sym>_<from>_<to>.png(窗内各日计数相加)
      python figures.py fig5 <sym> <dt_ms> <day>                 → reports/step04/fig5_<sym>_<day>.png(该日自身的 g1 模型,双侧窗诊断)
"""
import datetime as dt
import glob
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt      # noqa: E402
import numpy as np                   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "data"))
import arrivals as AR                # noqa: E402
import demand as DM                  # noqa: E402
import events as EV                  # noqa: E402
import ladder_store as LS            # noqa: E402

NS = 1_000_000_000


def day_bounds(day):
    t = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    return t, t + 86400 * NS


def load_day(sym, day):
    files = sorted(glob.glob(os.path.join(REPRO, "data", "step01", sym, f"{day}_*.npz")))
    return [LS.load(p) for p in files]


def reach_for(sym, dt_ms, tag="base"):
    p = os.path.join(REPRO, "reports", "step02", f"reach_{sym}_dt{dt_ms}_{tag}.json")
    if not os.path.exists(p):
        return None
    r = json.load(open(p, encoding="utf-8"))
    return [np.asarray(r["bid"]), np.asarray(r["ask"])]


def curves_of_day(sym, day, dt_ms, V_LO, side=1, curve_grid="levels"):
    """(c,p) 按默认档位口径估计;曲线本身可按 curve_grid 重算(Figure 6 用 "ticks":逐 tick 的需求函数在每个区间都有定义,才能跨区间平均)。"""
    lads = load_day(sym, day)
    d0, d1 = day_bounds(day)
    fr = EV.build(lads, dt_ms, d0, d1)
    est_fit = DM.DemandEstimator(V_LO, reach=reach_for(sym, dt_ms))
    dp = est_fit.estimate(fr, lads)
    est = est_fit if curve_grid == "levels" else DM.DemandEstimator(V_LO, grid_mode="ticks", weight_fn="uniform")
    bnd_lad = np.concatenate([d["bnd_lad"] for d in lads])
    sw_ts = np.concatenate([d["sw_ts"] for d in lads]); sw_side = np.concatenate([d["sw_side"] for d in lads]).astype(int)
    sw_vol = np.concatenate([d["sw_vol"] for d in lads]); sw_lad = np.concatenate([d["sw_lad"] for d in lads])
    col = 0 if side == 1 else 1
    out = []
    for k in np.where(dp.valid[:, col])[0]:
        sl = slice(np.searchsorted(sw_ts, fr.t0[k]), np.searchsorted(sw_ts, fr.t0[k] + dt_ms * 1_000_000))
        m = sw_side[sl] == (0 if side == 1 else 1)
        Lg, Q = est.curve(bnd_lad[fr.bnd_index[k]], int(fr.mid2[k]), sw_vol[sl][m], sw_lad[sl][m], side)
        out.append((k, Lg, Q, dp.c[k, col], dp.p[k, col]))
    return fr, dp, out


def fig3(sym, day, dt_ms, V_LO, k=None):
    fr, dp, cur = curves_of_day(sym, day, dt_ms, V_LO)
    if k is None:
        k, Lg, Q, c, p = cur[len(cur) // 2]
    else:
        k, Lg, Q, c, p = next(x for x in cur if x[0] == int(k))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(Lg, Q, width=max(0.6, (Lg.max() - Lg.min()) / 60), label="actual demand Q_l (contracts)")
    xs = np.linspace(0, max(Lg.max(), p) * 1.05, 200)
    ax.plot(xs, np.maximum(c * (p - xs), 0), "r-", label=f"fit c(p-L): c={c:.3f}/tick, p={p:.1f} ticks")
    ts = dt.datetime.fromtimestamp(fr.t0[k] / 1e9, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    ax.set_xlabel("distance from mid L (ticks)"); ax.set_ylabel("contracts"); ax.set_title(f"Figure 3 type: {sym} ask side, interval {ts} UTC, dt={dt_ms} ms, V_LO={V_LO}")
    ax.legend(); fig.tight_layout()
    out = os.path.join(REPRO, "reports", "step02", f"fig3_{sym}_{day}_k{k}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True); fig.savefig(out, dpi=120); print(out)


def fig6(sym, day, dt_ms, V_LO):
    fr, dp, cur = curves_of_day(sym, day, dt_ms, V_LO, curve_grid="ticks")
    binsum, bincnt = {}, {}
    for k, Lg, Q, c, p in cur:
        for L, q in zip(np.round(Lg).astype(int), Q):
            binsum[L] = binsum.get(L, 0) + q; bincnt[L] = bincnt.get(L, 0) + 1
    Ls = np.array(sorted(binsum)); avg = np.array([binsum[L] / bincnt[L] for L in Ls])      # 逐 tick 需求函数在各区间都有定义:按有定义的区间数平均
    keep = np.array([bincnt[L] >= 0.5 * len(cur) for L in Ls])                               # 只画多数区间都覆盖到的距离(远处被 20 档截断)
    Ls, avg = Ls[keep], avg[keep]
    cbar, pbar = np.nanmean([x[3] for x in cur]), np.nanmean([x[4] for x in cur])
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(Ls, avg, "o-", ms=3, label="average actual demand (per MO interval)")
    xs = np.linspace(0, max(Ls.max(), pbar) * 1.05, 200)
    ax.plot(xs, np.maximum(cbar * (pbar - xs), 0), "r-", label=f"line with daily mean: c={cbar:.3f}, p={pbar:.1f}")
    ax.set_xlim(0, min(Ls.max(), pbar * 3)); ax.set_xlabel("distance from mid L (ticks)"); ax.set_ylabel("contracts")
    ax.set_title(f"Figure 6 type: {sym} {day} ask side, dt={dt_ms} ms, {len(cur)} intervals with buy MO"); ax.legend(); fig.tight_layout()
    out = os.path.join(REPRO, "reports", "step02", f"fig6_{sym}_{day}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True); fig.savefig(out, dpi=120); print(out)


def model_from_days(sym, dt_ms, day_from, day_to, kind):
    g = AR.GState(kind); m = AR.ArrivalModel(g)
    for p in sorted(glob.glob(os.path.join(REPRO, "data", "step04", sym, f"dt{dt_ms}", "*.npz"))):
        day = os.path.basename(p)[:8]
        if day_from <= day <= day_to:
            z = np.load(p)
            m.count += z[f"{kind}_count"]; m.n_plus += z[f"{kind}_plus"]; m.n_minus += z[f"{kind}_minus"]; m.n_11 += z[f"{kind}_11"]
    return m.finalize()


def fig4(sym, dt_ms, day_from, day_to):
    m = model_from_days(sym, dt_ms, day_from, day_to, "g3")
    order = np.argsort(-m.count)
    seen = order[m.count[order] > 0]
    fig, ax = plt.subplots(figsize=(12, 4))
    x = np.arange(len(seen))
    ax.bar(x - 0.2, m.pi_plus[seen], 0.4, label="pi+"); ax.bar(x + 0.2, m.pi_minus[seen], 0.4, label="pi-")
    ax.set_xticks(x); ax.set_xticklabels([m.g.label(s) for s in seen], rotation=90, fontsize=6)
    ax.set_title(f"Figure 4 type: pi± vs g3 state, {sym}, dt={dt_ms} ms, days {day_from}..{day_to} (states sorted by count; {len(seen)}/81 seen)")
    ax.legend(); fig.tight_layout()
    out = os.path.join(REPRO, "reports", "step04", f"fig4_{sym}_{day_from}_{day_to}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True); fig.savefig(out, dpi=120); print(out)


def fig5(sym, dt_ms, day):
    z = np.load(os.path.join(REPRO, "data", "step04", sym, f"dt{dt_ms}", f"{day}.npz"))
    t, M, P = z["fig5_t"], z["fig5_M"], z["fig5_P"]
    hrs = (t - t[0]) / 3.6e12
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(hrs, M, label="moving avg of actual 1+ (501 pts)"); ax.plot(hrs, P, label="moving avg of pi_hat+ (g1, same-day fit)")
    ax.set_xlabel("hours since day start (UTC)"); ax.set_ylabel("probability"); ax.set_title(f"Figure 5 type: {sym} {day}, dt={dt_ms} ms (two-sided window diagnostic, not for strategy)")
    ax.legend(); fig.tight_layout()
    out = os.path.join(REPRO, "reports", "step04", f"fig5_{sym}_{day}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True); fig.savefig(out, dpi=120); print(out)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "fig3":
        fig3(sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), sys.argv[6] if len(sys.argv) > 6 else None)
    elif cmd == "fig6":
        fig6(sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
    elif cmd == "fig4":
        fig4(sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5])
    elif cmd == "fig5":
        fig5(sys.argv[2], int(sys.argv[3]), sys.argv[4])
