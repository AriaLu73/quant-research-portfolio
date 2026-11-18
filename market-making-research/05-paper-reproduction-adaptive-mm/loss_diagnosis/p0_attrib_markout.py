"""P0:PnL Attribution + Markout + Maker Rebate Economics(用户 2026-11-09 提示词 §3–§5;对象 = XBTUSDCM,P1 原论文目录,Δt = 2000 ms,l3sim 1.8 ms,9 个测试日)。
数据
  成交 / 全部委托:repro/data/step14/XBTUSDCM/dt2000/<day>_P1_M_g3_L1.8.npz(fills: ts, side, tick, qty, ahead0, ahead_fill, wait_ns, sweep_qty, level0, born)
  中价(L3 分辨率):同目录 <day>_bbo.npz(ts, mid2)
  盘口 / 市场成交(50 ms 网格,前 20 档):repro/data/step01/XBTUSDCM/<day>_HH.npz(bnd_ts, bnd_lad, sw_ts, sw_side, sw_vol)
会计边界(全部以 USDC 记;side = +1 卖成交、−1 买成交;q 张;价 = tick × 0.1 USDC;名义额 = 价 × 0.0001 BTC × q)
  每笔成交到日末的 PnL_i        = side·(p_i − m_end)·q_i·mult                      Σ_i PnL_i ≡ W + I·m_end(对账恒等式,残差必须为 0)
    = 报价距离 edge_i           = side·(p_i − m0_i)·q·mult       m0 = 下单时刻中价(事前可知的 spread)
    + 下单→成交中价漂移 drift_i  = side·(m0_i − mf_i)·q·mult      mf = 成交前最后一个 BBO 的中价(l3sim 里盘口穿过挂单价后单子仍挂着,这项可为负)
    + 持仓 MTM_i                = side·(mf_i − m_end)·q·mult     成交后到日末
  spread capture_i(成交时刻口径) = edge_i + drift_i = side·(p_i − mf_i)·q·mult
  返佣 rebate_i = OUR_FEE × 名义额(只加一次,作为单独一列);P1 无市价单、无对冲、无 funding(回测未计)。
  markout_h,i = side·(mf_i − m_{f+h,i})(bp 对名义额)是 MTM_i 在 horizon h 的诊断切片,不进对账表。
输出  loss_diagnosis/out/P1_dt2000_XBTUSDCM/*.csv|png 与 01_P0_report_XBTUSDCM_P1_dt2000.md 的素材(表由本脚本打印)。
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

ROOT = r"主动做市策略"
REPRO = os.path.join(ROOT, "repro")
sys.path.insert(0, os.path.join(REPRO, "data")); import ladder_store as LS   # noqa: E402

SYM, DT, AGENT = "XBTUSDCM", 2000, "P1_M_g3_L1.8"
TICK, MULT, REB_BP = 0.1, 0.0001, 1.2
NS = 1_000_000_000
H_MS = [10, 50, 100, 500, 1000, 5000, 10000, 30000, 60000]
OUT = os.path.join(ROOT, "loss_diagnosis", "out", f"P1_dt{DT}_{SYM}"); os.makedirs(OUT, exist_ok=True)
HOURS = {"20261001": 12, "20261002": 22, "20261013": 14, "20261014": 17, "20261015": 19, "20261016": 24, "20261017": 24, "20261018": 24, "20261019": 22}
TRAIN_DAYS, TEST_DAYS = ["20261001", "20261002", "20261013", "20261014", "20261015"], ["20261016", "20261017", "20261018", "20261019"]


def mid_at(bts, bmid, t, side="right"):
    i = np.searchsorted(bts, t, side=side) - 1
    return bmid[np.clip(i, 0, len(bmid) - 1)], i


def load_day(day):
    od = os.path.join(REPRO, "data", "step14", SYM, f"dt{DT}")
    z = np.load(os.path.join(od, f"{day}_{AGENT}.npz")); fl, rec = z["fills"].astype(np.int64), z["records"].astype(np.int64)
    b = np.load(os.path.join(od, f"{day}_bbo.npz")); bts, bmid = b["ts"].astype(np.int64), b["mid2"].astype(float) / 2.0
    W, I = float(z["W"]), float(z["I"])
    lad_ts, lad, sw_ts, sw_side, sw_vol = [], [], [], [], []
    for p in sorted(glob.glob(os.path.join(REPRO, "data", "step01", SYM, f"{day}_*.npz"))):
        d = LS.load(p, keys=("bnd_ts", "bnd_lad", "sw_ts", "sw_side", "sw_vol"))
        lad_ts.append(d["bnd_ts"]); lad.append(d["bnd_lad"]); sw_ts.append(d["sw_ts"]); sw_side.append(d["sw_side"]); sw_vol.append(d["sw_vol"])
    lad_ts = np.concatenate(lad_ts).astype(np.int64); lad = np.concatenate(lad); sw_ts = np.concatenate(sw_ts).astype(np.int64); sw_vol = np.concatenate(sw_vol).astype(float)
    return fl, rec, bts, bmid, W, I, lad_ts, lad, sw_ts, sw_vol


def per_fill_frame(day):
    fl, rec, bts, bmid, W, I, lad_ts, lad, sw_ts, sw_vol = load_day(day)
    m_end = float(bmid[-1])
    ts, side_raw, tk, q, a0, af, wait, sweep, lvl0, born = [fl[:, k] for k in range(10)]
    side = np.where(side_raw == 1, 1.0, -1.0)                    # +1 卖成交、−1 买成交
    p = tk * TICK
    m0, _ = mid_at(bts, bmid, born, "right"); m0 = m0 * TICK
    mf, i_f = mid_at(bts, bmid, ts, "left"); mf = mf * TICK      # 成交前最后一个 BBO
    notional = p * MULT * q
    df = pd.DataFrame(dict(day=day, ts=ts, born=born, side=side, price=p, qty=q, notional=notional, ahead0=a0, ahead_fill=af, wait_ms=wait / 1e6, sweep_qty=sweep,
                           level0=lvl0, m0=m0, mf=mf, m_end=m_end * TICK))
    df["edge"] = side * (p - m0) * q * MULT                      # USDC
    df["drift"] = side * (m0 - mf) * q * MULT
    df["spread_capture"] = df["edge"] + df["drift"]
    df["mtm_to_close"] = side * (mf - m_end * TICK) * q * MULT
    df["pnl_to_close"] = df["spread_capture"] + df["mtm_to_close"]
    df["rebate"] = REB_BP * 1e-4 * notional
    # markout 切片(bp):adverse = side·(mf − m_{f+h});total = side·(p − m_{f+h});capture_bp = side·(p − mf)
    df["capture_bp"] = side * (p - mf) / p * 1e4
    for h in H_MS:
        j = np.searchsorted(bts, ts + h * 1_000_000, side="right") - 1
        ok = (j >= 0) & (bts[np.clip(j, 0, len(bts) - 1)] >= ts) & (ts + h * 1_000_000 <= bts[-1])
        mh = bmid[np.clip(j, 0, len(bmid) - 1)] * TICK
        df[f"adv_{h}"] = np.where(ok, side * (mf - mh) / p * 1e4, np.nan)
        df[f"tot_{h}"] = np.where(ok, side * (p - mh) / p * 1e4, np.nan)
    # 分组变量
    df["quote_age_ms"] = (ts - born) / 1e6
    df["hour"] = ((ts // NS) % 86400) // 3600
    # 波动:成交前 60 s 内 1 s 采样中价的对数收益标准差(bp)
    t1 = np.arange(0, 61) * NS
    grid = ts[:, None] - t1[None, ::-1]
    mg, _ = mid_at(bts, bmid, grid.ravel(), "right"); mg = mg.reshape(grid.shape)
    r = np.diff(np.log(mg), axis=1) * 1e4
    df["vol_bp_1s"] = r.std(axis=1)
    # 盘口(50 ms 网格,成交前最后一个边界):点差、前 1 档与前 5 档失衡(对齐吃单方向:卖成交→买方吃单→bid 重为"顺向")
    k = np.searchsorted(lad_ts, ts, side="left") - 1; k = np.clip(k, 0, len(lad_ts) - 1)
    L = lad[k]                                                   # [n, 2, 20, 2]
    bb, ba = L[:, 0, 0, 0].astype(float), L[:, 1, 0, 0].astype(float)
    df["spread_ticks"] = ba - bb
    bq1, aq1 = L[:, 0, 0, 1].astype(float), L[:, 1, 0, 1].astype(float)
    bq5, aq5 = L[:, 0, :5, 1].sum(1).astype(float), L[:, 1, :5, 1].sum(1).astype(float)
    imb1 = (bq1 - aq1) / np.maximum(bq1 + aq1, 1); imb5 = (bq5 - aq5) / np.maximum(bq5 + aq5, 1)
    df["imb1_aligned"] = side * imb1                             # 卖成交 side=+1:bid 重 → 正 = 吃单方向有压力
    df["imb5_aligned"] = side * imb5
    # 吃单强度:成交前 10 s 市场吃单张数
    lo = np.searchsorted(sw_ts, ts - 10 * NS); hi = np.searchsorted(sw_ts, ts)
    cs = np.concatenate([[0.0], np.cumsum(sw_vol)])
    df["mkt_taker_qty_10s"] = cs[hi] - cs[lo]
    recon = dict(day=day, W_plus_I_mend=(W + I * m_end) * TICK * MULT, sum_pnl_i=float(df["pnl_to_close"].sum()), n_orders=len(rec), n_fills=len(fl),
                 fill_qty=int(q.sum()), notional=float(notional.sum()), I_end=I, hours=HOURS[day])
    recon["residual"] = recon["W_plus_I_mend"] - recon["sum_pnl_i"]
    return df, recon


def wmean(x, w):
    m = np.isfinite(x) & np.isfinite(w)
    return float(np.average(x[m], weights=w[m])) if m.any() and w[m].sum() > 0 else np.nan


def cluster_se(x, w, clusters):
    """按簇(分钟)聚合的加权均值标准误:簇均值的离散 / sqrt(簇数)。"""
    m = np.isfinite(x) & np.isfinite(w)
    if m.sum() < 2:
        return np.nan, 0
    d = pd.DataFrame(dict(x=x[m], w=w[m], c=clusters[m]))
    g = d.groupby("c").apply(lambda t: pd.Series(dict(xw=(t.x * t.w).sum(), w=t.w.sum())))
    mu = g.xw.sum() / g.w.sum()
    dev = (g.xw - mu * g.w) / (g.w.sum() / len(g))
    return float(dev.std(ddof=1) / np.sqrt(len(g))), int(len(g))


def main():
    frames, recons = [], []
    for day in HOURS:
        df, rc = per_fill_frame(day); frames.append(df); recons.append(rc)
        print(f"{day}: fills {rc['n_fills']:,} 张 {rc['fill_qty']:,} 名义 ${rc['notional']:,.0f}  账本 {rc['W_plus_I_mend']:+.2f}  Σ逐笔 {rc['sum_pnl_i']:+.2f}  残差 {rc['residual']:+.4f} USDC", flush=True)
    F = pd.concat(frames, ignore_index=True); R = pd.DataFrame(recons)
    F["minute"] = F["ts"] // (60 * NS)
    F.to_csv(os.path.join(OUT, "fills_attributed.csv"), index=False)
    R.to_csv(os.path.join(OUT, "reconciliation.csv"), index=False)

    # ---------- 表 1:逐日对账与归因 ----------
    rows = []
    for day, g in F.groupby("day"):
        rc = R[R.day == day].iloc[0]
        rows.append(dict(day=day, hours=rc.hours, fills=len(g), qty=int(g.qty.sum()), notional=g.notional.sum(), edge=g.edge.sum(), drift=g.drift.sum(), capture=g.spread_capture.sum(),
                         mtm=g.mtm_to_close.sum(), gross=g.pnl_to_close.sum(), rebate=g.rebate.sum(), net=g.pnl_to_close.sum() + g.rebate.sum(), residual=rc.residual, I_end=rc.I_end))
    T1 = pd.DataFrame(rows); tot = T1.drop(columns=["day"]).sum(numeric_only=True); tot["day"] = "合计"; T1 = pd.concat([T1, pd.DataFrame([tot])], ignore_index=True)
    T1.to_csv(os.path.join(OUT, "table1_daily_attribution.csv"), index=False)
    print("\n## 表 1 逐日对账与归因(USDC;edge = 报价距离兑现、drift = 下单→成交中价漂移、capture = edge + drift、mtm = 成交后到日末、gross = capture + mtm ≡ W + I·m_end、net = gross + 返佣)")
    print("| 日 | 回放 h | 成交笔 | 张 | 名义额 | edge | drift | spread capture | 持仓 MTM | gross(不含返佣) | 返佣 | net(含返佣) | 残差 | 日末 I 张 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in T1.iterrows():
        print(f"| {r.day} | {r.hours:.0f} | {r.fills:,.0f} | {r.qty:,.0f} | ${r.notional:,.0f} | {r.edge:+.1f} | {r.drift:+.1f} | {r.capture:+.1f} | {r.mtm:+.1f} | {r.gross:+.1f} | {r.rebate:+.1f} | {r.net:+.1f} | {r.residual:+.4f} | {r.I_end:+.0f} |")
    N = F.notional.sum()
    print(f"\n按名义额折 bp(9 天合计 ${N:,.0f}):edge {T1.iloc[-1].edge / N * 1e4:+.2f} | drift {T1.iloc[-1].drift / N * 1e4:+.2f} | capture {T1.iloc[-1].capture / N * 1e4:+.2f} | MTM {T1.iloc[-1].mtm / N * 1e4:+.2f} | gross {T1.iloc[-1].gross / N * 1e4:+.2f} | 返佣 +{REB_BP:.2f} | net {T1.iloc[-1].net / N * 1e4:+.2f}")

    # ---------- 表 2:markout 曲线(bp,按量加权;三条线 + 返佣) ----------
    w = F.notional.values; cl = F.minute.values
    print("\n## 表 2 Markout(bp 对名义额,按名义额加权;adverse = 成交时刻中价→h 后中价(正 = 向我方有利),total = 成交价→h 后中价,capture = 成交价→成交时刻中价;返佣 我方费率 单列)")
    print("| h | n | adverse 全部 | se(分钟簇) | adverse 买成交 | adverse 卖成交 | total 全部 | total + 返佣 | 不含返佣为负占比(total<0) |")
    print("|---|---|---|---|---|---|---|---|---|")
    T2 = []
    for h in H_MS:
        a = F[f"adv_{h}"].values; t = F[f"tot_{h}"].values; ok = np.isfinite(a)
        se, nc = cluster_se(a, w, cl)
        buy, sell = F.side.values < 0, F.side.values > 0
        row = dict(h_ms=h, n=int(ok.sum()), adv=wmean(a, w), se=se, adv_buy=wmean(a[buy], w[buy]), adv_sell=wmean(a[sell], w[sell]), tot=wmean(t, w), tot_reb=wmean(t, w) + REB_BP,
                   neg_share=float(np.average((t[ok] < 0), weights=w[ok])))
        T2.append(row)
        print(f"| {h} ms | {row['n']:,} | {row['adv']:+.2f} | {row['se']:.2f} | {row['adv_buy']:+.2f} | {row['adv_sell']:+.2f} | {row['tot']:+.2f} | {row['tot_reb']:+.2f} | {row['neg_share']:.0%} |")
    print(f"| 到日末 | {len(F):,} | {wmean(F.mtm_to_close.values / F.notional.values * 1e4, w):+.2f} | – | – | – | {wmean(F.pnl_to_close.values / F.notional.values * 1e4, w):+.2f} | {wmean(F.pnl_to_close.values / F.notional.values * 1e4, w) + REB_BP:+.2f} | – |")
    print(f"capture(成交价→成交时刻中价)按量加权 {wmean(F.capture_bp.values, w):+.2f} bp;报价距离(成交价→下单时刻中价){wmean(F.side.values * (F.price.values - F.m0.values) / F.price.values * 1e4, w):+.2f} bp")
    pd.DataFrame(T2).to_csv(os.path.join(OUT, "table2_markout.csv"), index=False)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    hs = [r["h_ms"] for r in T2]
    ax.plot(hs, [r["adv"] for r in T2], "o-", label="adverse:成交时刻中价 → h 后中价")
    ax.plot(hs, [r["tot"] for r in T2], "s-", label="total:成交价 → h 后中价(不含返佣)")
    ax.plot(hs, [r["tot_reb"] for r in T2], "^-", label="total + 返佣 我方费率")
    ax.axhline(0, color="k", lw=0.8); ax.set_xscale("log"); ax.set_xlabel("h(ms,对数轴)"); ax.set_ylabel("bp(按名义额加权)")
    ax.set_title(f"{SYM} P1 原论文 Δt={DT} ms,l3sim 1.8 ms,9 天 {len(F):,} 笔 maker 成交"); ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "fig_markout_curves.png"), dpi=130); plt.close(fig)

    # ---------- 表 3:分组 markout(h = 5 s 与 60 s,total + 返佣;分组按五分位) ----------
    print("\n## 表 3 分组(按量加权,bp;列 = adverse_5s / total_60s + 返佣 / n / 名义额占比)")
    groups = {"quote_age_ms": "quote age(下单→成交 ms)", "sweep_qty": "打到我方的吃单张数", "vol_bp_1s": "成交前 60 s 1 s 波动(bp)", "imb5_aligned": "前 5 档失衡(对齐吃单方向)",
              "spread_ticks": "点差(tick)", "mkt_taker_qty_10s": "成交前 10 s 市场吃单张数", "hour": "UTC 小时", "ahead0": "进簿时前方张数"}
    T3 = []
    for col, lab in groups.items():
        x = F[col].values
        if col == "hour":
            bins = pd.Series(x).astype(int)
        elif col == "ahead0":
            bins = pd.cut(x, [-1, 0, 10, 100, 1e9], labels=["0", "1–10", "11–100", ">100"])
        else:
            try:
                bins = pd.qcut(x, 5, duplicates="drop")
            except ValueError:
                bins = pd.cut(x, 5)
        print(f"\n**{lab}**\n| 分组 | n | 名义额占比 | adverse 5 s | total 60 s + 返佣 | 到日末 + 返佣 |\n|---|---|---|---|---|---|")
        for b, g in F.groupby(bins, observed=True):
            ww = g.notional.values
            r = dict(group_var=col, bin=str(b), n=len(g), share=ww.sum() / N, adv5=wmean(g["adv_5000"].values, ww), tot60r=wmean(g["tot_60000"].values, ww) + REB_BP,
                     closer=wmean(g.pnl_to_close.values / g.notional.values * 1e4, ww) + REB_BP)
            T3.append(r)
            print(f"| {r['bin']} | {r['n']:,} | {r['share']:.0%} | {r['adv5']:+.2f} | {r['tot60r']:+.2f} | {r['closer']:+.2f} |")
    pd.DataFrame(T3).to_csv(os.path.join(OUT, "table3_groups.csv"), index=False)

    # ---------- 表 4:返佣经济学 H1–H3 ----------
    print("\n## 表 4 Maker Rebate Economics")
    g9 = T1.iloc[-1]
    print(f"H1 去掉返佣:我方费率 天 gross {g9.gross:+.1f} USDC({g9.gross / N * 1e4:+.2f} bp),含返佣 {g9.net:+.1f}({g9.net / N * 1e4:+.2f} bp);gross 为正的天数 {(T1.gross.iloc[:-1] > 0).sum()}/9,净为正 {(T1.net.iloc[:-1] > 0).sum()}/9")
    neg_days = T1.iloc[:-1][T1.gross.iloc[:-1] < 0]
    print(f"H2 返佣占比:返佣 {g9.rebate:+.1f} / |亏损日 gross 合计| {abs(neg_days.gross.sum()):.1f} = {g9.rebate / max(abs(neg_days.gross.sum()), 1e-9):.0%};返佣 / |spread capture| = {g9.rebate / max(abs(g9.capture), 1e-9):.0%};返佣 / net = {g9.rebate / g9.net if g9.net else float('nan'):.0%}")
    v60 = F["tot_60000"].values + REB_BP; vclose = F.pnl_to_close.values / F.notional.values * 1e4 + REB_BP
    print(f"H3 扣返佣后仍为负的成交:我方费率 s 口径 {np.average(v60[np.isfinite(v60)] < 0, weights=w[np.isfinite(v60)]):.0%}(按量),到日末口径 {np.average(vclose < 0, weights=w):.0%};"
          f"按 quote age 五分位最高档 total_60s+返佣 = {[r['tot60r'] for r in T3 if r['group_var'] == 'quote_age_ms'][-1]:+.2f} bp,最低档 {[r['tot60r'] for r in T3 if r['group_var'] == 'quote_age_ms'][0]:+.2f} bp")
    # H5 训练/测试:在训练 5 天上找单变量阈值(quote age / imb5 / sweep_qty)使"剔除该组后 total_60s+返佣 均值最大",在测试 4 天上报同规则下的成交级价值(只是 fill-level 上界,非回放)
    print("\nH5(fill-level 上界,非回放;训练 10-01…10-15,测试 10-16…10-19):")
    tr, te = F[F.day.isin(TRAIN_DAYS)], F[F.day.isin(TEST_DAYS)]
    for col, hi_is_bad in (("quote_age_ms", True), ("imb5_aligned", True), ("sweep_qty", True), ("vol_bp_1s", True)):
        best = None
        for qq in (0.5, 0.6, 0.7, 0.8, 0.9):
            thr = tr[col].quantile(qq); keep = tr[col] <= thr if hi_is_bad else tr[col] >= thr
            val = wmean((tr["tot_60000"].values + REB_BP)[keep.values], tr.notional.values[keep.values]) * tr.notional.values[keep.values].sum()
            if best is None or val > best[0]:
                best = (val, qq, thr)
        keep_te = te[col] <= best[2]
        base_te = wmean(te["tot_60000"].values + REB_BP, te.notional.values); kept = wmean((te["tot_60000"].values + REB_BP)[keep_te.values], te.notional.values[keep_te.values])
        print(f"  规则 {col} ≤ 训练 {best[1]:.0%} 分位({best[2]:.3g}):测试 4 天 保留成交占名义额 {te.notional.values[keep_te.values].sum() / te.notional.sum():.0%},total_60s+返佣 基线 {base_te:+.2f} → 保留组 {kept:+.2f} bp;"
              f"保留组 USDC {np.nansum((te["tot_60000"].values + REB_BP)[keep_te.values] * te.notional.values[keep_te.values] / 1e4):+.1f} vs 全部 {np.nansum((te["tot_60000"].values + REB_BP) * te.notional.values / 1e4):+.1f}")
    print("\nDONE")


if __name__ == "__main__":
    main()
