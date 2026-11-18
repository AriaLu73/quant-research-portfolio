#!/usr/bin/env python3
"""research3 H-FV4(流程阶段 5 离线实验;2026-10-02,结果出来之前写):用户代码评审第 2、3、5 点——公允价滞后、观测等权、没用盘口量。
现行:基差 = "USDC 中价相对 USDT 中价"每秒一个观测的 60 秒中位数(M60),观测等权;basis_observation 算出的噪声 r 没用。
候选(全部只用过去数据,1 秒网格;评价口径与 uh_fv3_study.py 完全相同):
  M15 / M30   窗口缩短(第 2 点:60 秒中位数对基差跳变要约 30 秒才反应)
  WM60        加权中位数,权重 = 1 / max(半点差, 0.5 bp)²(第 5 点:点差宽的观测降权;就是原卡尔曼的 r = 半点差² / 3 的倒数)
  WM30        同上,30 秒窗口
  N60         只用"点差不超过近 10 分钟中位点差"的观测取 60 秒中位(窗口内不足 10 个时退回 M60)
  MP60        观测改用 USDC 的 microprice(按买一卖一量加权)相对 USDT 中价,60 秒中位(第 3 点;USDT 一侧点差恒为 1 跳 = 0.013 bp,microprice 与中价最多差 0.006 bp,不单独测)
事先写定的判定(只看 tight 标价、δ = 3 与 4 合并;BTC 是主力品种):
  某候选采纳 = BTC 上每美元净值按日配对 8 天里至少 6 天高于 M60 且合并差 > 0,同时 ETH 上合并差 ≥ −0.1 bp。
  一次比 6 个候选,有多重比较:只有一个候选勉强过线时不采纳,要求过线的候选在跟踪误差(RMSE)上也优于 M60。都不过线就如实记录。
用法:Python314/python.exe -X utf8 scripts/research3/uh_fv4_study.py <USDC 原生合约名> <USDT 事件标签>"""
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


def wmedian_roll(z, w, win, min_obs=10, fallback=None):
    """滚动加权中位数:第 i 个值 = z[i-win+1..i] 按权重 w 的中位数;有效权重的观测不足 min_obs 个时取 fallback[i](无则 NaN)。"""
    n = len(z); out = np.full(n, np.nan)
    for i in range(n):
        j = max(0, i - win + 1); zz = z[j:i + 1]; ww = w[j:i + 1]
        k = ww > 0
        if k.sum() < min_obs:
            if fallback is not None:
                out[i] = fallback[i]
            continue
        zz, ww = zz[k], ww[k]; o = np.argsort(zz); c = np.cumsum(ww[o])
        out[i] = zz[o][np.searchsorted(c, 0.5 * c[-1])]
    return out


rows, track = [], []
for day in DAYS:
    pu, pa = os.path.join(EV, f"book_{usdc}_{day}.parquet"), os.path.join(EV, f"book_{usdt_tag}_{day}.parquet")
    if not (os.path.exists(pu) and os.path.exists(pa)):
        print("skip", day); continue
    u = pd.read_parquet(pu, columns=["ts", "bb", "ba", "bq1", "aq1"]); a = pd.read_parquet(pa, columns=["ts", "bb", "ba"])
    t = pd.read_parquet(os.path.join(EV, f"trades_{usdc}_{day}.parquet"), columns=["ts", "sgn", "px", "qty"])
    uts, ubb, uba = u.ts.values.astype(np.int64), u.bb.values * tick_c, u.ba.values * tick_c; umid = (ubb + uba) / 2
    ats = a.ts.values.astype(np.int64); am = (a.bb.values + a.ba.values) / 2.0
    am = am * (umid.mean() / am.mean())             # 同一价格单位(只把常数基差归零附近,不影响估计量之间的比较)
    g = np.arange(max(uts[0], ats[0]) + 1_000_000, min(uts[-1], ats[-1]), 1_000_000)
    A = at(ats, am, g); B = at(uts, ubb, g); K = at(uts, uba, g)
    zb, za = (B / A - 1) * 1e4, (K / A - 1) * 1e4; zm = 0.5 * (zb + za); sp = za - zb
    M60 = pd.Series(zm).rolling(60, min_periods=30).median().values
    hs = np.maximum(sp / 2, 0.5); wgt = 1.0 / hs ** 2
    bq = at(uts, u.bq1.values.astype(float), g); aq = at(uts, u.aq1.values.astype(float), g)
    zmp = ((B * aq + K * bq) / np.maximum(bq + aq, 1e-12) / A - 1) * 1e4
    narrow = (sp <= pd.Series(sp).rolling(600, min_periods=60).median().values).astype(float)
    est = {"M60": M60, "M30": pd.Series(zm).rolling(30, min_periods=15).median().values, "M15": pd.Series(zm).rolling(15, min_periods=8).median().values,
           "WM60": wmedian_roll(zm, wgt, 60, 30), "WM30": wmedian_roll(zm, wgt, 30, 15), "N60": wmedian_roll(zm, narrow, 60, 10, M60),
           "MP60": pd.Series(zmp).rolling(60, min_periods=30).median().values}
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
out = os.path.join(ROOT, "data", "research3", "uh_val", "fv4_study"); os.makedirs(out, exist_ok=True)
R.to_csv(os.path.join(out, f"delta_{usdc}.csv"), index=False); K.to_csv(os.path.join(out, f"tracking_{usdc}.csv"), index=False)
pd.set_option("display.width", 220)
print(f"\n== {usdc}:跟踪误差(估计值 − 之后 1–6 分钟点差窄时的中价基差中位;bp)==")
print(K.groupby("est").agg(rmse=("rmse", lambda x: float(np.sqrt((x ** 2).mean()))), mae_med=("mae", "median"), p99=("p99", "mean"), worst_day_rmse=("rmse", "max")).round(2).to_string())
print("\n== δ 曲线(5 分钟,净 = markout + 1.2 − 0.30;每美元 bp;$ = 净 × 额)==")
NAMES = ["M60", "M30", "M15", "WM60", "WM30", "N60", "MP60"]
for name in NAMES:
    X = R[R.est == name].groupby("delta").agg(fills=("fills", "sum"), usd=("usd", "sum"), rw_mid=("rw_mid", "sum"), rw_tight=("rw_tight", "sum"), usd_tight=("usd_tight", "sum"))
    X["net_mid"] = X.rw_mid / X.usd + REB - DISP; X["net_tight"] = X.rw_tight / X.usd_tight + REB - DISP; X["usd_day"] = X.usd / R.day.nunique(); X["$tight_day"] = X.net_tight / 1e4 * X.usd_tight / R.day.nunique()
    print("--", name); print(X[["fills", "usd_day", "net_mid", "net_tight", "$tight_day"]].round(2).to_string())
print()
print("== 判定用:δ = 3 与 4 合并、tight 标价,按日每美元净 bp ==")
P = R[R.delta.isin((3, 4))].groupby(["day", "est"]).agg(rw=("rw_tight", "sum"), usd=("usd_tight", "sum")).reset_index()
P["net"] = P.rw / P.usd + REB - DISP
W = P.pivot(index="day", columns="est", values="net")[NAMES]; print(W.round(2).to_string())
tot = P.groupby("est").apply(lambda d: d.rw.sum() / d.usd.sum() + REB - DISP); usd = P.groupby("est").usd.sum() / R.day.nunique()
print()
print("候选     合并净bp   对 M60   更高的天数   成交额/天   $/天")
for n in NAMES:
    print(f"{n:<7}{tot[n]:>9.3f}{tot[n] - tot['M60']:>+9.3f}{int((W[n] > W['M60']).sum()):>8}/{len(W)}{usd[n]:>13,.0f}{tot[n] / 1e4 * usd[n]:>8.2f}")
