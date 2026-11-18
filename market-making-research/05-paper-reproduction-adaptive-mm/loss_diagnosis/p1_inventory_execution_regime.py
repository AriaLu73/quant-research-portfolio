"""P1:Inventory(§6)/ Execution & Queue & Fill-selection bias(§7)/ Market Regime(§8)。
对象同 P0:XBTUSDCM,P1 原论文目录,Δt = 2000 ms,l3sim 1.8 ms,9 天。**只读现有回放文件,不跑任何回测。**
输入  P0 的 fills_attributed.csv;step14 的 records(全部委托:born, rest_at, side, tick, size, ahead0, ahead, outcome 1 filled/2 canceled/3 lost, filled_qty, level0);bbo;step01 50 ms 盘口 + 市场成交。
输出  out/P1_dt2000_XBTUSDCM/p1_*.csv 与打印的表。
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"主动做市策略"; REPRO = os.path.join(ROOT, "repro")
sys.path.insert(0, os.path.join(REPRO, "data")); import ladder_store as LS   # noqa: E402
SYM, DT, AGENT = "XBTUSDCM", 2000, "P1_M_g3_L1.8"
TICK, MULT, REB_BP, NS = 0.1, 0.0001, 1.2, 1_000_000_000
OUT = os.path.join(ROOT, "loss_diagnosis", "out", f"P1_dt{DT}_{SYM}")
OD = os.path.join(REPRO, "data", "step14", SYM, f"dt{DT}")
DAYS = ["20261001", "20261002", "20261013", "20261014", "20261015", "20261016", "20261017", "20261018", "20261019"]


def wmean(x, w):
    m = np.isfinite(x) & np.isfinite(w); return float(np.average(x[m], weights=w[m])) if m.any() and w[m].sum() > 0 else np.nan


def mid_at(bts, bmid, t):
    return bmid[np.clip(np.searchsorted(bts, t, side="right") - 1, 0, len(bmid) - 1)]


def load_bbo(day):
    b = np.load(os.path.join(OD, f"{day}_bbo.npz")); return b["ts"].astype(np.int64), b["mid2"].astype(float) / 2.0 * TICK


def load_lad(day):
    lt, lad, st, sv = [], [], [], []
    for p in sorted(glob.glob(os.path.join(REPRO, "data", "step01", SYM, f"{day}_*.npz"))):
        d = LS.load(p, keys=("bnd_ts", "bnd_lad", "sw_ts", "sw_vol")); lt.append(d["bnd_ts"]); lad.append(d["bnd_lad"]); st.append(d["sw_ts"]); sv.append(d["sw_vol"])
    return np.concatenate(lt).astype(np.int64), np.concatenate(lad), np.concatenate(st).astype(np.int64), np.concatenate(sv).astype(float)


def main():
    F = pd.read_csv(os.path.join(OUT, "fills_attributed.csv"), dtype={"day": str})
    # ================= §6 Inventory =================
    print("## §6 库存(P1:无平仓、无对冲;库存 = 累计成交;每天独立回放,日末按中价计价)")
    inv_rows, corr_rows, skew_rows, hourly = [], [], [], []
    for day in DAYS:
        g = F[F.day == day].sort_values("ts"); bts, bmid = load_bbo(day)
        dI = np.where(g.side.values > 0, -g.qty.values, g.qty.values); I = np.cumsum(dI); t = g.ts.values
        # 10 s 采样的库存路径(回放时段内)
        grid = np.arange(bts[0], bts[-1], 10 * NS); Ig = np.zeros(len(grid))
        k = np.searchsorted(t, grid, side="right") - 1; Ig = np.where(k >= 0, I[np.clip(k, 0, len(I) - 1)], 0.0)
        mg = mid_at(bts, bmid, grid)
        absI = np.abs(Ig)
        # 持仓段:|I|>0 连续时长;符号段:I 符号不变的连续时长
        sgn = np.sign(Ig); ch = np.where(np.diff(sgn) != 0)[0]; seg_len = np.diff(np.concatenate([[0], ch + 1, [len(sgn)]])) * 10.0
        inv_rows.append(dict(day=day, hours=len(grid) / 360, mean_absI=absI.mean(), p50_absI=np.median(absI), p90_absI=np.percentile(absI, 90), max_absI=absI.max(),
                             share_absI_gt_500=(absI > 500).mean(), sign_seg_p50_s=np.median(seg_len), sign_seg_max_s=seg_len.max(), I_end=I[-1] if len(I) else 0,
                             mtm_usdc=g.mtm_to_close.sum(), gross_usdc=g.pnl_to_close.sum()))
        # 库存 × 未来收益:corr(I_t, m_{t+h} − m_t)(10 s 网格)
        for h in (10, 60, 300, 1800):
            n = h // 10
            if len(grid) > n:
                fut = (mg[n:] - mg[:-n]) / mg[:-n] * 1e4; x = Ig[:-n]
                corr_rows.append(dict(day=day, h_s=h, corr=np.corrcoef(x, fut)[0, 1] if x.std() > 0 else np.nan,
                                      pnl_bp_per_1000=np.polyfit(x / 1000, fut, 1)[0] if x.std() > 0 else np.nan))
        # 库存 × 波动:|I| 在高/低波动小时
        # 报价倾斜:记录里每张单的 level0 与方向,配上下单时刻库存 → ask 距离 − bid 距离 对 I 回归
        rec = np.load(os.path.join(OD, f"{day}_{AGENT}.npz"))["records"].astype(np.int64)
        born, side_r, tk, lvl0 = rec[:, 0], rec[:, 2], rec[:, 3], rec[:, 9]
        m0 = mid_at(bts, bmid, born); dist = np.where(side_r == 1, tk * TICK - m0, m0 - tk * TICK) / TICK      # tick
        kI = np.searchsorted(t, born, side="right") - 1; I_at = np.where(kI >= 0, I[np.clip(kI, 0, len(I) - 1)], 0.0)
        # 同一决策时刻的 ask/bid 配对:按 born 分组
        d = pd.DataFrame(dict(born=born, side=side_r, dist=dist, I=I_at)); pv = d.pivot_table(index="born", columns="side", values=["dist", "I"], aggfunc="first").dropna()
        if len(pv) > 10:
            skew = pv[("dist", 1)].values - pv[("dist", 0)].values; Iv = pv[("I", 1)].values
            b = np.polyfit(Iv, skew, 1)[0] if Iv.std() > 0 else np.nan
            skew_rows.append(dict(day=day, n_decisions=len(pv), skew_mean_tick=skew.mean(), slope_tick_per_contract=b, corr=np.corrcoef(Iv, skew)[0, 1] if Iv.std() > 0 else np.nan,
                                  mean_abs_I_at_decision=np.abs(Iv).mean()))
        # ---- 小时表(§8 用):小时 PnL = 该小时内成交 capture + 库存在小时内的 MTM(期初库存 × 小时中价变化 + 小时内成交 × (m_f − 小时末中价))
        lt, lad, st, sv = load_lad(day)
        for hr in range(24):
            t0 = (bts[0] // (86400 * NS)) * 86400 * NS + hr * 3600 * NS; t1 = t0 + 3600 * NS
            if t1 <= bts[0] or t0 >= bts[-1]:
                continue
            mb = bmid[(bts >= t0) & (bts < t1)]; tb = bts[(bts >= t0) & (bts < t1)]
            if len(mb) < 100:
                continue
            m_start, m_end = mb[0], mb[-1]
            # 1 s 采样收益
            g1 = np.arange(tb[0], tb[-1], NS); m1 = mid_at(bts, bmid, g1); r1 = np.diff(np.log(m1)) * 1e4
            vol = r1.std(); trend = abs(m1[-1] - m1[0]) / m1[0] * 1e4 / max(np.abs(r1).sum(), 1e-9)      # 位移 / 路径长(0 = 来回震荡,1 = 单边)
            rm = pd.Series(r1).rolling(60).sum().dropna().values[::60]; ac1 = np.corrcoef(rm[:-1], rm[1:])[0, 1] if len(rm) > 5 else np.nan   # 1 分钟收益 lag-1 自相关
            mk = (lt >= t0) & (lt < t1); L = lad[mk]
            spread = (L[:, 1, 0, 0] - L[:, 0, 0, 0]).astype(float); depth5 = (L[:, 0, :5, 1].sum(1) + L[:, 1, :5, 1].sum(1)).astype(float)
            imb = np.abs((L[:, 0, 0, 1] - L[:, 1, 0, 1]) / np.maximum(L[:, 0, 0, 1] + L[:, 1, 0, 1], 1))
            taker = sv[(st >= t0) & (st < t1)].sum()
            gh = g[(g.ts >= t0) & (g.ts < t1)]
            kI0 = np.searchsorted(t, t0, side="right") - 1; I0 = I[kI0] if kI0 >= 0 else 0.0
            pnl = gh.spread_capture.sum() + I0 * (m_end - m_start) * MULT + (gh.side.values * (gh.mf.values - m_end) * gh.qty.values * MULT).sum()
            hourly.append(dict(day=day, hour=hr, vol_bp=vol, trend=trend, ac1=ac1, spread_tick=spread.mean(), depth5=depth5.mean(), imb=imb.mean(), taker_qty=taker,
                               fills=len(gh), notional=gh.notional.sum(), pnl_gross=pnl, rebate=gh.rebate.sum(), adv60=wmean(gh.adv_60000.values, gh.notional.values) if len(gh) else np.nan,
                               I0=I0, mean_absI=np.abs(Ig[(grid >= t0) & (grid < t1)]).mean() if ((grid >= t0) & (grid < t1)).any() else np.nan))
    INV = pd.DataFrame(inv_rows); INV.to_csv(os.path.join(OUT, "p1_inventory_daily.csv"), index=False)
    print("\n表 6.1 库存分布(张;10 s 采样,回放时段内)\n| 日 | 回放 h | 均值 \\|I\\| | p50 | p90 | max | \\|I\\|>500 张时间占比 | 符号段 p50 s | 符号段 max s | 日末 I | 持仓 MTM USDC | gross USDC |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in INV.iterrows():
        print(f"| {r.day} | {r.hours:.0f} | {r.mean_absI:,.0f} | {r.p50_absI:,.0f} | {r.p90_absI:,.0f} | {r.max_absI:,.0f} | {r.share_absI_gt_500:.0%} | {r.sign_seg_p50_s:,.0f} | {r.sign_seg_max_s:,.0f} | {r.I_end:+,.0f} | {r.mtm_usdc:+.1f} | {r.gross_usdc:+.1f} |")
    print(f"\n库存 × PnL:日均 |I| 与 持仓 MTM 的相关(9 天) = {np.corrcoef(INV.mean_absI, INV.mtm_usdc)[0,1]:+.2f};与 gross 的相关 = {np.corrcoef(INV.mean_absI, INV.gross_usdc)[0,1]:+.2f}")
    C = pd.DataFrame(corr_rows); C.to_csv(os.path.join(OUT, "p1_inventory_future_return.csv"), index=False)
    print("\n表 6.2 库存 × 未来中价变化(10 s 网格;corr(I_t, Δm_{t→t+h});斜率 = 每 1,000 张库存对应的未来 h 秒中价变化 bp,正 = 库存方向与后续行情同向)\n| h | 9 天 corr 均值 | corr 为正的天数 | 斜率 bp/1000 张 均值 |\n|---|---|---|---|")
    for h, gg in C.groupby("h_s"):
        print(f"| {h} s | {gg['corr'].mean():+.3f} | {(gg['corr'] > 0).sum()}/{len(gg)} | {gg.pnl_bp_per_1000.mean():+.2f} |")
    S = pd.DataFrame(skew_rows); S.to_csv(os.path.join(OUT, "p1_skew.csv"), index=False)
    print(f"\n表 6.3 报价倾斜有效性:同一决策时刻 ask 距离 − bid 距离(tick)对库存 I 的斜率 = {S.slope_tick_per_contract.mean():+.5f} tick/张(9 天均值;相关 {S['corr'].mean():+.3f});"
          f"决策时刻 |I| 均值 {S.mean_abs_I_at_decision.mean():,.0f} 张 → 平均倾斜 {abs(S.slope_tick_per_contract.mean()) * S.mean_abs_I_at_decision.mean():.2f} tick。对冲:无;taker 费拖累:0。")

    # ================= §7 Execution / Queue / Selection bias =================
    print("\n## §7 执行 / 排队 / fill-selection bias(全部委托记录 records,不只成交)")
    R = []
    for day in DAYS:
        rec = np.load(os.path.join(OD, f"{day}_{AGENT}.npz"))["records"].astype(np.int64); rq = np.load(os.path.join(OD, f"{day}_{AGENT}.npz"))["requotes"].astype(np.int64)
        bts, bmid = load_bbo(day); lt, lad, st, sv = load_lad(day)
        born, rest, side_r, tk, size, a0, ah, outc, fq, lvl0 = [rec[:, k] for k in range(10)]
        m0 = mid_at(bts, bmid, born); dist = np.where(side_r == 1, tk * TICK - m0, m0 - tk * TICK) / TICK
        k = np.clip(np.searchsorted(lt, born, side="left") - 1, 0, len(lt) - 1); L = lad[k]
        bq5, aq5 = L[:, 0, :5, 1].sum(1).astype(float), L[:, 1, :5, 1].sum(1).astype(float)
        imb5 = np.where(side_r == 1, 1.0, -1.0) * (bq5 - aq5) / np.maximum(bq5 + aq5, 1)
        spread = (L[:, 1, 0, 0] - L[:, 0, 0, 0]).astype(float)
        # 撤单时刻 = requotes 的 ts(按 born+side 匹配不可靠,用 outcome 与存活时长近似:canceled 单的存活时长 = 下一次改价时刻 − rest;这里用 requotes 的 ts 序列按 side 对齐)
        life = np.full(len(rec), np.nan)
        for s_ in (0, 1):
            m = side_r == s_; rts = np.sort(rq[rq[:, 1] == s_, 0])
            j = np.searchsorted(rts, rest[m], side="right"); j = np.clip(j, 0, len(rts) - 1)
            life[m] = (rts[j] - rest[m]) / 1e6
        R.append(pd.DataFrame(dict(day=day, side=side_r, dist=dist, size=size, ahead0=a0, outcome=outc, filled_qty=fq, level0=lvl0, imb5=imb5, spread=spread, life_ms=life, born=born)))
    R = pd.concat(R, ignore_index=True); R["filled"] = R.filled_qty > 0; R["partial"] = (R.filled_qty > 0) & (R.filled_qty < R["size"])
    R.to_csv(os.path.join(OUT, "p1_all_orders.csv"), index=False)
    n = len(R)
    print(f"\n全部委托 {n:,} 张单(9 天);结局:有成交(含部分成交){R.filled.mean():.2%}、成交完 {(R.outcome == 1).mean():.2%}、改价撤单 {(R.outcome == 2).mean():.2%}、断流作废 {(R.outcome == 3).mean():.2%};部分成交后被撤(成交量 < 单量)的单 {((R.outcome == 2) & (R.filled_qty > 0)).mean():.2%};"
          f"ahead0 = 0 的单 {(R.ahead0 == 0).mean():.1%};改价撤单时放弃的队列位置 p50/p90 = {np.percentile(R.ahead0[R.outcome == 2], 50):.0f}/{np.percentile(R.ahead0[R.outcome == 2], 90):.0f} 张")
    print(f"挂单存活时长(到下一次改价)p50/p90 = {np.nanpercentile(R.life_ms, 50):,.0f}/{np.nanpercentile(R.life_ms, 90):,.0f} ms;成交单的 quote age p50 = {F.quote_age_ms.median():,.0f} ms")
    # 成交概率 × 成交后价值:按决策时刻特征分桶
    F2 = F.copy(); F2["born"] = F2.born.astype(np.int64)
    val = F2.groupby(["day", "born", "side"]).apply(lambda t: pd.Series(dict(v60=np.nansum((t.tot_60000 + REB_BP) * t.notional / 1e4), notional=t.notional.sum()))).reset_index()
    val["side"] = (val.side > 0).astype(int)   # fills 的 side 是 ±1,records 的 side 是 0/1(1 = 卖)
    RM = R.merge(val, on=["day", "born", "side"], how="left"); RM["v60"] = RM.v60.fillna(0.0); RM["notional"] = RM.notional.fillna(0.0)
    print("\n表 7.1 报价层面的价值(每张挂单:P(成交) × 成交后 60 s 含返佣价值;未成交单价值记 0 —— 这是消除 fill-selection bias 的口径)\n| 分组变量 | 分桶 | 挂单数 | P(成交) | 成交单 60 s 净值 bp | 每张挂单期望值 USDC | 每张挂单期望值 / 挂单名义 bp |")
    print("|---|---|---|---|---|---|---|")
    T7 = []
    for col, lab in (("dist", "报价距离 tick"), ("imb5", "前 5 档失衡(对齐本单被吃方向)"), ("spread", "点差 tick"), ("ahead0", "进簿前方张数")):
        if col == "ahead0":
            bins = pd.cut(RM[col], [-1, 0, 10, 100, 1e9], labels=["0", "1–10", "11–100", ">100"])
        else:
            bins = pd.qcut(RM[col], 5, duplicates="drop")
        for b, gg in RM.groupby(bins, observed=True):
            pf = gg.filled.mean(); vbp = (gg.v60.sum() / gg.notional.sum() * 1e4) if gg.notional.sum() > 0 else np.nan
            ev = gg.v60.sum() / len(gg); quote_notional = (gg["size"] * 8.2).mean()
            T7.append(dict(var=col, bin=str(b), n=len(gg), p_fill=pf, v60_bp=vbp, ev_usdc=ev, ev_bp=ev / quote_notional * 1e4))
            print(f"| {lab} | {b} | {len(gg):,} | {pf:.2%} | {vbp:+.2f} | {ev:+.4f} | {ev / quote_notional * 1e4:+.3f} |")
    pd.DataFrame(T7).to_csv(os.path.join(OUT, "p1_quote_value_by_bucket.csv"), index=False)
    # 新鲜 vs 过时:quote age 分桶的 60 s 净值 + 成交时已穿价占比
    F["crossed"] = F.capture_bp < 0
    print("\n表 7.2 新鲜 vs 过时报价(成交单;quote age = 成交时刻 − 下单时刻)\n| quote age | n | 名义占比 | 成交时中价已穿过挂单价占比 | capture bp | adverse 60 s | total 60 s + 返佣 |\n|---|---|---|---|---|---|---|")
    for b, gg in F.groupby(pd.cut(F.quote_age_ms, [0, 250, 500, 1000, 2000, 4000, 1e9]), observed=True):
        ww = gg.notional.values
        print(f"| {b} ms | {len(gg):,} | {ww.sum() / F.notional.sum():.0%} | {np.average(gg.crossed, weights=ww):.0%} | {wmean(gg.capture_bp.values, ww):+.2f} | {wmean(gg.adv_60000.values, ww):+.2f} | {wmean(gg.tot_60000.values, ww) + REB_BP:+.2f} |")
    print("撤单延迟:回测固定 1.8 ms(下单 = 撤单);本对象没有多延迟档回放,Fast/Slow cancel 对比不可做(Table 11 的 0…50 ms 配对只对 P2)。")

    # ================= §8 Regime =================
    H = pd.DataFrame(hourly); H.to_csv(os.path.join(OUT, "p1_hourly_regime.csv"), index=False)
    H["net"] = H.pnl_gross + H.rebate
    print(f"\n## §8 Regime(小时粒度,{len(H)} 个小时;小时 PnL = 小时内 capture + 库存在小时内的 MTM;按名义额折 bp)")
    print("| 变量 | 低三分位 净 bp / gross bp / 成交额 $/h / adv60 | 中 | 高 | 高−低 净 USDC/h |\n|---|---|---|---|---|")
    T8 = []
    for col, lab in (("vol_bp", "1 s 波动"), ("trend", "单边程度(位移/路径)"), ("ac1", "1 min 收益自相关"), ("depth5", "前 5 档深度"), ("spread_tick", "点差"), ("imb", "|失衡|"), ("taker_qty", "吃单量")):
        try:
            bins = pd.qcut(H[col], 3, labels=["低", "中", "高"])
        except ValueError:
            continue
        cells = []
        for lv in ("低", "中", "高"):
            gg = H[bins == lv]; N_ = gg.notional.sum()
            cells.append((gg.net.sum() / N_ * 1e4 if N_ else np.nan, gg.pnl_gross.sum() / N_ * 1e4 if N_ else np.nan, N_ / max(len(gg), 1), wmean(gg.adv60.values, gg.notional.values), gg.net.sum() / max(len(gg), 1)))
            T8.append(dict(var=col, level=lv, hours=len(gg), net_bp=cells[-1][0], gross_bp=cells[-1][1], notional_per_h=cells[-1][2], adv60=cells[-1][3], net_usdc_per_h=cells[-1][4]))
        print(f"| {lab} | " + " | ".join(f"{c[0]:+.2f} / {c[1]:+.2f} / ${c[2]:,.0f} / {c[3]:+.2f}" for c in cells) + f" | {cells[2][4] - cells[0][4]:+.1f} |")
    pd.DataFrame(T8).to_csv(os.path.join(OUT, "p1_regime_terciles.csv"), index=False)
    tod = H.groupby(pd.cut(H.hour, [-1, 5, 11, 17, 23], labels=["00–05", "06–11", "12–17", "18–23"]), observed=True).agg(hours=("net", "size"), notional=("notional", "sum"), gross=("pnl_gross", "sum"), net=("net", "sum"))
    print("\n时段(UTC):\n| 时段 | 小时数 | 成交额 $/h | gross bp | 净 bp |\n|---|---|---|---|---|")
    for b, r in tod.iterrows():
        print(f"| {b} | {r.hours} | ${r.notional / r.hours:,.0f} | {r.gross / r.notional * 1e4:+.2f} | {r.net / r.notional * 1e4:+.2f} |")
    print(f"\n小时净 PnL 为负的小时占比 {(H.net < 0).mean():.0%};最差 5 个小时合计 {H.nsmallest(5, 'net').net.sum():+.1f} USDC(占 9 天 net {H.net.sum():+.1f} 的 {H.nsmallest(5, 'net').net.sum() / H.net.sum():.0%});最好 5 个小时合计 {H.nlargest(5, 'net').net.sum():+.1f}")
    print("Funding regime:回测未计 funding,不可做。")
    print("\nDONE")


if __name__ == "__main__":
    main()
