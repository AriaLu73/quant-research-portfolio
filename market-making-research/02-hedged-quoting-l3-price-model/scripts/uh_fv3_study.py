#!/usr/bin/env python3
"""research3 H-FV3(流程阶段 5 离线实验;2026-10-02,结果出来之前写):USDC 盘口单边变宽时,公允价不该跟着中价跑。
起因:ETH-USDC 09-02 09 时 47–57 分,卖盘撤走、点差从 5 bp 变成 33–47 bp,买一没动,但"USDC 中价相对 USDT 中价"的基差从 12 跳到 25–33 bp;
  FV2 的 60 秒中位数跟着上去,我方买价抬高约 15 bp,十分钟内买入 $9.5k,对冲后 5 分钟 −6…−16 bp(scripts/research3/uh_sym_fill_diag.py)。
  中价只在点差窄时才是好观测;点差宽时它只说明"公允价在买一和卖一之间"。research5 的卡尔曼用 r = 半点差²/3 降权,FV2 的中位数没有用这条信息。
假设:把每个观测当作区间 [z_bid, z_ask](公允基差落在其中),取"到各区间距离之和最小"的 D;这个最小化的解是窗口内全部端点(2n 个)的
  第 n 与第 n+1 小之间的一段 [lo, hi];D 只在落到这一段之外时才移动(D_t = clip(D_{t-1}, lo_t, hi_t))。没有新参数(窗口仍是 60 秒)。
  点差窄时 [lo, hi] 很窄,D ≈ 中价中位数;单边变宽时旧值仍在段内,D 不动。
候选(全部只用过去数据,1 秒网格):
  M60   现行 v4:中价基差的 60 秒中位数
  EM60  端点中位数的中点 (lo + hi) / 2(无保持)
  IM60  区间中位数 + 保持:clip(D_prev, lo, hi)
评价(9 月 8 个训练日全天;真实吃单 = 成交价不在买一卖一之间的打印,按 (时间, 方向) 合并):
  报价常挂在离公允价 δ bp(δ = 2, 3, 4, 6),每张吃单成交 min($5k, 它在我方价或更差处的额),成交价 = 我方价;
  对冲后 markout r(h) = s[(U_h − q)/q − (A_h − A_0)/A_0],h = 300 秒;U_h 用两种标价:
    mid   = 当时 USDC 中价(点差宽时本身失真,只作参考)
    tight = A_h × (1 + 之后 5 分钟内"点差不超过当日中位数"的那些秒的中价基差中位数)(没有这样的秒则该笔不计)
  净 = markout + 1.2(返佣)− 0.3(处置成本,BTC 实测;ETH 未单独测,同值代入只为比较)。
事先写定的判定(只看 tight 标价、δ = 3 与 4 合并):
  IM60 采纳 = ETH 上每美元净值比 M60 高(按日配对,8 天里至少 6 天更高,合并差 > 0)且 BTC 上合并差 ≥ −0.1 bp。
  不满足就如实记录,不采纳,另找办法;BTC 不变差是硬条件(BTC 是主力品种)。
用法:Python314/python.exe -X utf8 scripts/research3/uh_fv3_study.py <USDC 原生合约名> <USDT 事件标签>     例:ETHUSDCM ETHUSDTM / XBTUSDCM BTC_B"""
import json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EV = os.path.join(ROOT, "data", "research2", "events")
SPECS = json.load(open(os.path.join(ROOT, "data", "research2", "kc_contract_specs.json")))
DAYS = ["20260901", "20260902", "20260903", "20260910", "20260911", "20260914", "20260917", "20260918"]
CLIP, REB, DISP, WIN = 5000.0, 1.2, 0.30, 60
DELTAS = (2, 3, 4, 6)
usdc, usdt_tag = sys.argv[1], sys.argv[2]
tick_c = float(SPECS[usdc]["tick"])
at = lambda ts, v, t, strict=False: v[np.clip(np.searchsorted(ts, t, "left" if strict else "right") - 1, 0, len(v) - 1)]


def interval_band(zb, za, win):
    """[lo, hi] = 窗口内 2n 个端点的第 n 与第 n+1 小(到各区间距离之和的最小化解集)。前 win−1 个点用已有的。"""
    n = len(zb); lo = np.full(n, np.nan); hi = np.full(n, np.nan)
    for i in range(n):
        j = max(0, i - win + 1)
        e = np.sort(np.concatenate((zb[j:i + 1], za[j:i + 1])))
        m = i + 1 - j
        lo[i], hi[i] = e[m - 1], e[m]
    return lo, hi


def hold(lo, hi, min_obs):
    d = np.full(len(lo), np.nan); prev = None
    for i in range(len(lo)):
        if i + 1 < min_obs:
            continue
        prev = 0.5 * (lo[i] + hi[i]) if prev is None else min(max(prev, lo[i]), hi[i])
        d[i] = prev
    return d


rows, track = [], []
for day in DAYS:
    pu, pa = os.path.join(EV, f"book_{usdc}_{day}.parquet"), os.path.join(EV, f"book_{usdt_tag}_{day}.parquet")
    if not (os.path.exists(pu) and os.path.exists(pa)):
        print("skip", day); continue
    u = pd.read_parquet(pu, columns=["ts", "bb", "ba"]); a = pd.read_parquet(pa, columns=["ts", "bb", "ba"])
    t = pd.read_parquet(os.path.join(EV, f"trades_{usdc}_{day}.parquet"), columns=["ts", "sgn", "px", "qty"])
    uts, ubb, uba = u.ts.values.astype(np.int64), u.bb.values * tick_c, u.ba.values * tick_c; umid = (ubb + uba) / 2
    ats = a.ts.values.astype(np.int64); am = (a.bb.values + a.ba.values) / 2.0
    am = am * (umid.mean() / am.mean())             # 同一价格单位(只把常数基差归零附近,不影响估计量之间的比较)
    g = np.arange(max(uts[0], ats[0]) + 1_000_000, min(uts[-1], ats[-1]), 1_000_000)
    A = at(ats, am, g); B = at(uts, ubb, g); K = at(uts, uba, g)
    zb, za = (B / A - 1) * 1e4, (K / A - 1) * 1e4; zm = 0.5 * (zb + za); sp = za - zb
    lo, hi = interval_band(zb, za, WIN)
    est = {"M60": pd.Series(zm).rolling(WIN, min_periods=30).median().values, "EM60": np.where(np.arange(len(g)) + 1 >= 30, 0.5 * (lo + hi), np.nan), "IM60": hold(lo, hi, 30)}
    # tight 标价用的"之后 5 分钟、点差不超过当日中位数"的中价基差中位数
    tight = sp <= np.median(sp)
    zt = pd.Series(np.where(tight, zm, np.nan))
    fut_tight = zt.iloc[::-1].rolling(300, min_periods=10).median().iloc[::-1].values        # [i, i+299] 内的中位
    for name, D in est.items():
        ok = np.isfinite(D) & np.isfinite(np.roll(fut_tight, -60))
        err = (D - np.roll(fut_tight, -60))[ok][:-360]
        track.append(dict(day=day, est=name, rmse=float(np.sqrt(np.mean(err ** 2))), mae=float(np.median(np.abs(err))), p99=float(np.quantile(np.abs(err), .99))))
    T = t.assign(p=t.px * tick_c); T["usd"] = T.p * T.qty
    Tg = T.groupby(["ts", "sgn"]).agg(pmin=("p", "min"), pmax=("p", "max")).reset_index()
    Tg = Tg[(Tg.ts > g[0] + 120_000_000) & (Tg.ts < g[-1] - 700_000_000)]
    tt, sg = Tg.ts.values, Tg.sgn.values
    near = np.where(sg > 0, Tg.pmin.values, Tg.pmax.values)
    iu = np.clip(np.searchsorted(uts, tt, "left") - 1, 0, len(uts) - 1)
    keep = ~((near > ubb[iu] + 0.5 * tick_c) & (near < uba[iu] - 0.5 * tick_c))
    Tg = Tg[keep]; tt, sg = Tg.ts.values, Tg.sgn.values
    T = T.merge(Tg[["ts", "sgn"]], on=["ts", "sgn"], how="inner")
    a0 = at(ats, am, tt, strict=True)
    gi = np.clip(np.searchsorted(g, tt, "left") - 1, 0, len(g) - 1)
    A5 = at(ats, am, tt + 300_000_000); U5 = at(uts, umid, tt + 300_000_000)
    gi5 = np.clip(np.searchsorted(g, tt + 300_000_000, "right") - 1, 0, len(g) - 1)
    U5t = A5 * (1 + fut_tight[gi5] / 1e4)
    for name, D in est.items():
        f0 = a0 * (1 + D[gi] / 1e4)
        Tm = T.merge(pd.DataFrame(dict(ts=tt, sgn=sg, f0=f0)), on=["ts", "sgn"])
        dd = Tm.sgn.values * (Tm.p.values - Tm.f0.values) / Tm.f0.values * 1e4
        idx = pd.MultiIndex.from_arrays([tt, sg])
        for dl in DELTAS:
            x = Tm[dd >= dl].groupby(["ts", "sgn"]).usd.sum().clip(upper=CLIP)
            rec = dict(day=day, est=name, delta=dl, fills=len(x), usd=float(x.sum()), rw_mid=0.0, rw_tight=0.0, usd_tight=0.0)
            if len(x):
                pos = idx.get_indexer(x.index); q = f0[pos] * (1 + sg[pos] * dl / 1e4); s = -sg[pos]
                hed = (A5[pos] - a0[pos]) / a0[pos]
                rec["rw_mid"] = float((s * ((U5[pos] - q) / q - hed) * 1e4 * x.values).sum())
                rt = s * ((U5t[pos] - q) / q - hed) * 1e4; okt = np.isfinite(rt)
                rec["rw_tight"] = float((rt[okt] * x.values[okt]).sum()); rec["usd_tight"] = float(x.values[okt].sum())
            rows.append(rec)
    print(day, "真实吃单", len(Tg), "点差中位 bp", round(float(np.median(sp)), 2), "90%", round(float(np.quantile(sp, .9)), 2), flush=True)

R = pd.DataFrame(rows); K = pd.DataFrame(track)
out = os.path.join(ROOT, "data", "research3", "uh_val", "fv3_study"); os.makedirs(out, exist_ok=True)
R.to_csv(os.path.join(out, f"delta_{usdc}.csv"), index=False); K.to_csv(os.path.join(out, f"tracking_{usdc}.csv"), index=False)
pd.set_option("display.width", 220)
print(f"\n== {usdc}:跟踪误差(估计值 − 之后 1–6 分钟点差窄时的中价基差中位;bp)==")
print(K.groupby("est").agg(rmse=("rmse", lambda x: float(np.sqrt((x ** 2).mean()))), mae_med=("mae", "median"), p99=("p99", "mean"), worst_day_rmse=("rmse", "max")).round(2).to_string())
print("\n== δ 曲线(5 分钟,净 = markout + 1.2 − 0.30;每美元 bp;$ = 净 × 额)==")
for name in ("M60", "EM60", "IM60"):
    X = R[R.est == name].groupby("delta").agg(fills=("fills", "sum"), usd=("usd", "sum"), rw_mid=("rw_mid", "sum"), rw_tight=("rw_tight", "sum"), usd_tight=("usd_tight", "sum"))
    X["net_mid"] = X.rw_mid / X.usd + REB - DISP; X["net_tight"] = X.rw_tight / X.usd_tight + REB - DISP; X["usd_day"] = X.usd / R.day.nunique(); X["$tight_day"] = X.net_tight / 1e4 * X.usd_tight / R.day.nunique()
    print("--", name); print(X[["fills", "usd_day", "net_mid", "net_tight", "$tight_day"]].round(2).to_string())
print("\n== 判定用:δ = 3 与 4 合并、tight 标价,按日 ==")
P = R[R.delta.isin((3, 4))].groupby(["day", "est"]).agg(rw=("rw_tight", "sum"), usd=("usd_tight", "sum")).reset_index()
P["net"] = P.rw / P.usd + REB - DISP
W = P.pivot(index="day", columns="est", values="net"); W["IM60−M60"] = W.IM60 - W.M60; print(W.round(2).to_string())
tot = P.groupby("est").apply(lambda d: d.rw.sum() / d.usd.sum() + REB - DISP)
print("合并:", tot.round(3).to_dict(), " IM60−M60 =", round(float(tot.IM60 - tot.M60), 3), " IM60 更高的天数:", int((W["IM60−M60"] > 0).sum()), "/", len(W))
