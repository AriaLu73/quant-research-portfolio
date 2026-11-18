#!/usr/bin/env python3
"""research3 → USDC 线验证报表(读 uh_val.py 的输出;问题定义见 uh_val.py 文件头)。
用法:Python314/python.exe -X utf8 scripts/research3/uh_val_report.py [TAG=UH1_train32]"""
import os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research3", "uh_val")
tag = sys.argv[1] if len(sys.argv) > 1 else "UH1_train32"
CLIP, REB, C_PRIOR = 5000.0, 1.2, 1.238
HS = (1, 5, 30, 300, 1800)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
I = pd.read_csv(os.path.join(OUT, f"{tag}_identity.csv")); F = pd.read_csv(os.path.join(OUT, f"{tag}_fills.csv")); H = pd.read_csv(os.path.join(OUT, f"{tag}_hours.csv"))
TK = pd.read_parquet(os.path.join(OUT, f"{tag}_takers.parquet")); GR = pd.read_parquet(os.path.join(OUT, f"{tag}_grid.parquet")); TR = pd.read_parquet(os.path.join(OUT, f"{tag}_trades.parquet"))
rng = np.random.default_rng(7)
# 成对打印的口径(本市场专用):只有"单一价位"的才算。flow_anatomy 的书本规则把"首笔成交价好于显示盘口"的吃单一律算成对,
# 但 XBTUSDCM 上这类里有大量跨 10 bp 以上、几万美元的多价位扫单(成交时间戳是毫秒、盘口帧滞后),它们是真实吃单。
TK["pair"] = TK.pair.astype(bool) & (TK.pmax == TK.pmin)
TR = TR.drop(columns="pair").merge(TK[["feed", "ts", "sgn", "pair"]], on=["feed", "ts", "sgn"], how="left")
_real = TK[~TK.pair]
_hk = _real.groupby("feed").agg(real_takers=("usd", "size"), real_usd=("usd", "sum"), depth_p90=("depth", lambda x: x.quantile(.9)), depth_max=("depth", "max"),
                                 our_dist_med=("our_dist", "median"), reach=("short_by", lambda x: int((x <= 1e-9).sum())), short_by_min=("short_by", "min"),
                                 real_ge4=("depth", lambda x: int((x >= 4).sum())), real_ge6=("depth", lambda x: int((x >= 6).sum()))).reset_index()
H = H.drop(columns=[c for c in _hk.columns if c != "feed" and c in H.columns]).merge(_hk, on="feed", how="left")
for c in ("real_takers", "real_usd", "reach", "real_ge4", "real_ge6"):
    H[c] = H[c].fillna(0)
# 每笔成交由哪类吃单触发(同侧、±3 ms 内最近的一张)
_k = []
for f in F.itertuples():
    k = TK[(TK.feed == f.feed) & (TK.sgn == -f.s) & ((TK.ts - f.ts).abs() <= 3000)]
    if not len(k):
        _k.append(("无对应成交(盘口穿价)", 0.0)); continue
    k = k.iloc[int(np.argmin((k.ts - f.ts).abs().values))]
    _k.append(("成对打印(单价位)" if k["pair"] else ("真实扫单(多价位)" if k["pmax"] > k["pmin"] else "真实吃单(单价位)"), float(k["usd"])))
F["trigger"] = [x[0] for x in _k]


def boot_ratio(num, den, n=4000):
    """按小时重抽样的 Σnum/Σden × 1e4 的 95% 区间。"""
    num, den = np.asarray(num, float), np.asarray(den, float)
    idx = rng.integers(0, len(num), (n, len(num)))
    r = num[idx].sum(1) / np.maximum(den[idx].sum(1), 1e-9) * 1e4
    return np.percentile(r, [2.5, 97.5])


def wmean_ci(x, w, clusters, n=4000):
    """加权均值及按小时(cluster)重抽样的 95% 区间。"""
    x, w = np.asarray(x, float), np.asarray(w, float)
    ok = np.isfinite(x)
    x, w, clusters = x[ok], w[ok], np.asarray(clusters)[ok]
    if not len(x):
        return np.nan, np.nan, np.nan
    g = pd.DataFrame(dict(c=clusters, xw=x * w, w=w)).groupby("c").sum()
    idx = rng.integers(0, len(g), (n, len(g)))
    r = g.xw.values[idx].sum(1) / np.maximum(g.w.values[idx].sum(1), 1e-9)
    lo, hi = np.percentile(r, [2.5, 97.5])
    return float((x * w).sum() / w.sum()), float(lo), float(hi)


# ============================================================ V1
print("=" * 30, "V1 实现边际恒等式(训练 32 小时,中价计价)")
J = I[I.usdc_usd > 0]
U = I.usdc_usd.sum()
parts = [("A  USDC 价差捕获(成交价对成交前 USDC 中价)", "A_usdc_spread"), ("B  对冲腿价差(对冲成交价对当时 USDT 中价)", "B_hedge_touch"),
         ("C1 USDC 返佣(我方费率)", "C_fee_usdc"), ("C2 对冲腿费用(挂单返佣 / 吃单费)", "C_fee_hedge"),
         ("D  基差持仓盈亏(持有 USDC−USDT 价差到小时末)", "D_basis"), ("E  未对冲方向盈亏(等对冲期间 USDT 的移动 + 零头)", "E_direction")]
print(f"有成交的小时 {len(J)}/{len(I)};USDC 成交额 ${U:,.0f},对冲成交额 ${I.hedge_usd.sum():,.0f}(其中吃单 {I.hedge_taker_usd.sum() / max(1, I.hedge_usd.sum()):.0%});USDC 成交 {int(I.n_usdc.sum())} 笔")
for name, c in parts:
    lo, hi = boot_ratio(J[c], J.usdc_usd)
    print(f"  {name:<46} ${I[c].sum():>8.2f}   {I[c].sum() / U * 1e4:+6.2f} bp/$USDC  [{lo:+.2f}, {hi:+.2f}]")
lo, hi = boot_ratio(J.sum_parts, J.usdc_usd)
print(f"  {'合计':<46} ${I.sum_parts.sum():>8.2f}   {I.sum_parts.sum() / U * 1e4:+6.2f} bp/$USDC  [{lo:+.2f}, {hi:+.2f}]")
print(f"  核对:各项之和 − 中价结算净值 = {abs(I.sum_parts - I.net_mid).max():.2e}(应为 0);中价结算 ${I.net_mid.sum():.2f} 对 引擎净值(已校返佣)${I.engine_net_corr.sum():.2f},逐小时最大差 ${(I.net_mid - I.engine_net_corr).abs().max():.2f}")
disp = -(I.B_hedge_touch.sum() + I.C_fee_hedge.sum() + I.E_direction.sum()) / U * 1e4
dlo, dhi = boot_ratio(-(J.B_hedge_touch + J.C_fee_hedge + J.E_direction), J.usdc_usd)
print(f"  实现的处置成本(−B − C2 − E)= {disp:+.2f} bp [{dlo:+.2f}, {dhi:+.2f}];策略先验 c_own = {C_PRIOR} bp")
print(f"  按策略自己的口径:实现边际 = A + D(成交价相对之后的基差)= {(I.A_usdc_spread.sum() + I.D_basis.sum()) / U * 1e4:+.2f} bp;减处置成本 {disp:.2f},加返佣 我方费率 → {(I.sum_parts.sum()) / U * 1e4:+.2f}")
top = J.sort_values("sum_parts", ascending=False)
print(f"  集中度:最赚的 3 个小时合计 ${top.sum_parts.head(3).sum():.2f}({top.sum_parts.head(3).sum() / I.sum_parts.sum():.0%}),其余 {len(J) - 3} 个有成交小时 ${top.sum_parts.iloc[3:].sum():.2f}")

# ============================================================ V2
print("\n" + "=" * 30, f"V2 成交条件收益按状态拆({len(F)} 笔 USDC 成交;r(h) = 对冲后的 markout,bp;成交额加权;区间按小时重抽样)")
print("  报价边际 m(成交价离公允价)额加权均值 %.2f bp;成交价离成交前 USDC 中价 e0 %.2f bp" % (np.average(F.m, weights=F.usd), np.average(F.e0, weights=F.usd)))
row = "  全部".ljust(34) + f"n {len(F):>3}  "
for h in HS:
    m, lo, hi = wmean_ci(F[f"r{h}"], F.usd, F.feed)
    row += f"r{h}s {m:+.2f} [{lo:+.2f},{hi:+.2f}]  "
print(row)


def by(col, bins=None, labels=None, name=None):
    X = F.copy()
    key = pd.cut(X[col], bins=bins, labels=labels) if bins is not None else X[col]
    print(f"  -- 按 {name or col}")
    for k, G in X.groupby(key, observed=True):
        s = f"     {str(k):<28} n {len(G):>3} ${G.usd.sum():>8,.0f}  m {np.average(G.m, weights=G.usd):5.2f}  "
        for h in (5, 30, 300, 1800):
            m, lo, hi = wmean_ci(G[f"r{h}"], G.usd, G.feed)
            s += f"r{h} {m:+6.2f} [{lo:+6.2f},{hi:+6.2f}]  "
        print(s)


by("trigger", name="触发这笔成交的吃单类型")
by("lvl", name="档位(1 = 靠前一档,2 = 两倍量的远档)")
by("adds", name="这笔成交是加仓(True)还是减仓")
by("pre500", [-np.inf, -0.3, 0.3, np.inf], ["USDT 逆向≥0.3bp(原紧急信号)", "平", "USDT 顺向≥0.3bp"], "成交前 500 ms USDT 走势(对新仓位)")
by("m", list(F.m.quantile([0, 1 / 3, 2 / 3, 1]).values + np.array([-1e-9, 0, 0, 1e-9])), ["边际低三分位", "中", "高"], "报价边际 m 三分位")
by("taker_usd", list(F.taker_usd.quantile([0, 1 / 3, 2 / 3, 1]).values + np.array([-1e-9, 0, 0, 1e-9])), ["吃单小", "中", "大"], "打到我方的那张吃单的总额")
by("rng60", list(F.rng60.quantile([0, 1 / 3, 2 / 3, 1]).values + np.array([-1e-9, 0, 0, 1e-9])), ["USDT 波动低", "中", "高"], "成交前 60 s USDT 振幅")
by("hh", name="小时(UTC)")

# ============================================================ V3
print("\n" + "=" * 30, "V3 基差滤波校准")
W = pd.read_csv(os.path.join(OUT, f"{tag}_walcheck.csv")).diff_bp.abs()
print(f"  复现精度:|离线复现 − 订单日志反推| 中位 {W.median():.3f} bp,90% {W.quantile(.9):.3f},99% {W.quantile(.99):.3f}(n = {len(W)})")
print("  (a) 模型:成交价偏离公允价 m 的部分应当回来 → r(h) 对 m 的斜率 → 1,r(h) 的均值 → m 的均值")
w = F.usd.values
for h in HS:
    y, x = F[f"r{h}"].values, F.m.values
    b = np.cov(x, y, aweights=w)[0, 1] / np.cov(x, x, aweights=w)[0, 1]
    bs = []
    feeds = F.feed.unique()
    for _ in range(2000):
        pick = rng.choice(feeds, len(feeds))
        G = pd.concat([F[F.feed == f] for f in pick])
        bs.append(np.cov(G.m, G[f"r{h}"], aweights=G.usd)[0, 1] / np.cov(G.m, G.m, aweights=G.usd)[0, 1])
    m, lo, hi = wmean_ci(F[f"r{h}"], F.usd, F.feed)
    print(f"      h = {h:>4} s:r 均值 {m:+.2f} [{lo:+.2f}, {hi:+.2f}] / m 均值 {np.average(x, weights=w):.2f} = {m / np.average(x, weights=w):.2f};斜率 {b:+.2f} [{np.percentile(bs, 2.5):+.2f}, {np.percentile(bs, 97.5):+.2f}]")
print("  (b) 成交之后慢基差 D̂ 的移动(对我方仓位:+ 有利 / − 不利,bp)与 USDT 的移动(不对冲时的盈亏)")
for h in HS:
    d, dlo, dhi = wmean_ci(F[f"dD{h}"], F.usd, F.feed); a, alo, ahi = wmean_ci(F[f"dA{h}"], F.usd, F.feed)
    print(f"      h = {h:>4} s:ΔD̂ {d:+.2f} [{dlo:+.2f}, {dhi:+.2f}]    USDT {a:+.2f} [{alo:+.2f}, {ahi:+.2f}]")
print("  (c) 对照:全部时刻(5 s 网格)USDC 中价相对公允价的缺口 gap = D̂ − z,之后 h 秒基差的变化 Δz 对 gap 的斜率(完全回归 = 1)")
for h in (30, 300, 1800):
    G = GR[np.isfinite(GR[f"dz{h}"])]
    b = np.cov(G.gap, G[f"dz{h}"])[0, 1] / G.gap.var()
    big = G[G.gap.abs() >= 3]
    bb = np.cov(big.gap, big[f"dz{h}"])[0, 1] / big.gap.var() if len(big) > 50 else np.nan
    print(f"      h = {h:>4} s:斜率 {b:+.2f}(全部,gap 标准差 {G.gap.std():.2f} bp);|gap| ≥ 3 bp 时 {bb:+.2f}(n = {len(big)})")

# ============================================================ N
print("\n" + "=" * 30, "N  为什么一半小时没有成交")
real = TK[~TK.pair]
print(f"  32 小时合计:USDC 吃单 {len(TK)} 张 ${TK.usd.sum():,.0f},其中成对打印 {TK.usd[TK.pair].sum() / TK.usd.sum():.0%};真实吃单 {len(real)} 张 ${real.usd.sum():,.0f}(每小时中位 {int(H.real_takers.median())} 张、${H.real_usd.median():,.0f})")
print(f"  真实吃单打穿深度(最远成交价离公允价,bp):中位 {real.depth.median():.2f},75% {real.depth.quantile(.75):.2f},90% {real.depth.quantile(.9):.2f},99% {real.depth.quantile(.99):.2f}")
q = real[np.isfinite(real.our_dist)]
print(f"  同一时刻我方最靠前报价离公允价(bp):中位 {q.our_dist.median():.2f},10% {q.our_dist.quantile(.1):.2f},90% {q.our_dist.quantile(.9):.2f};USDC 半点差中位 {H.usdc_half_spr.median():.2f} bp")
print(f"  够得着我方报价的真实吃单:{int((q.short_by <= 1e-9).sum())} / {len(real)} 张({(q.short_by <= 1e-9).sum() / len(real):.1%});没够着的,差距中位 {q.short_by[q.short_by > 0].median():.2f} bp")
for thr in (1, 2, 3, 4, 6):
    print(f"     打穿深度 ≥ {thr} bp 的真实吃单:{int((real.depth >= thr).sum())} 张,分布在 {real[real.depth >= thr].feed.nunique()}/32 个小时")
H["fills_gt0"] = H.our_fills > 0
g = H.groupby("fills_gt0").agg(hours=("feed", "size"), real_takers=("real_takers", "median"), real_usd=("real_usd", "median"), depth_p90=("depth_p90", "median"),
                               depth_max=("depth_max", "median"), our_dist=("our_dist_med", "median"), reach=("reach", "sum"), ge6=("real_ge6", "sum"),
                               usdt_rng60=("usdt_rng60", "median"), pres_b1=("pres_b1", "median"), pres_a1=("pres_a1", "median"), orders=("orders", "median"))
print("  有成交 / 无成交小时的对比(中位数;reach、ge6 为合计):"); print(g.round(2).to_string())
print("  按 UTC 小时:"); print(H.groupby("hh").agg(hours=("feed", "size"), with_fills=("fills_gt0", "sum"), our_fills=("our_fills", "sum"), net=("net", "sum"), real_takers=("real_takers", "sum"),
                                              depth_max=("depth_max", "max"), usdt_rng60=("usdt_rng60", "median")).round(2).to_string())
print("  逐小时:"); print(H[["feed", "our_fills", "our_usd", "net", "orders", "real_takers", "real_usd", "depth_p90", "depth_max", "our_dist_med", "reach", "short_by_min", "usdc_half_spr", "usdt_rng60"]].round(2).to_string(index=False))

# ============================================================ E
print("\n" + "=" * 30, "E  (探索性,仅训练小时;无库存上限、假设我方是该价位最靠前的单)报价常挂在离公允价 δ bp 处")
print("  每张真实吃单:成交额 = min($5k, 它在我方价或更差处成交的额);收益 = 对冲后 markout;净 = 收益 + 我方费率 返佣 − 实现处置成本 %.2f bp" % disp)
R = TR[~TR.pair.astype(bool)]
key = TK.set_index(["feed", "ts", "sgn"])
out = []
for dlt in (0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10):
    x = R[R.d >= dlt].groupby(["feed", "ts", "sgn"]).usd.sum().clip(upper=CLIP).rename("f").reset_index()
    if not len(x):
        continue
    x = x.join(key[["f0", "a0", "U30", "A30", "U300", "A300", "U1800", "A1800"]], on=["feed", "ts", "sgn"])
    s = -x.sgn.values
    p = x.f0.values * (1 + x.sgn.values * dlt / 1e4)
    rec = dict(delta=dlt, fills=len(x), hours=x.feed.nunique(), usd_per_h=x.f.sum() / 32)
    for h in (30, 300, 1800):
        x[f"r{h}"] = s * ((x[f"U{h}"].values - p) / p - (x[f"A{h}"].values - x.a0.values) / x.a0.values) * 1e4
        m, lo, hi = wmean_ci(x[f"r{h}"], x.f, x.feed)
        rec[f"net{h}"] = m + REB - disp; rec[f"lo{h}"] = lo + REB - disp; rec[f"hi{h}"] = hi + REB - disp
    rec["usd_profit_per_h_300"] = rec["net300"] / 1e4 * rec["usd_per_h"]
    out.append(rec)
E = pd.DataFrame(out)
print(E.round(2).to_string(index=False))
print("  注:δ 小于盘口半点差时我方会成为最优价,真实挂单方与成对打印的反应不在回放里;没有库存上限,也没有撤单与改价的延迟。只说明流量在哪,不是可成交的收益。")
