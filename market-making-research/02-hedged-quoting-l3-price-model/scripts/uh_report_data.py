#!/usr/bin/env python3
"""research3:量化策略报告用的数字(只读 research5 的回测输出)。
用法:Python314/python.exe -X utf8 scripts/research3/uh_report_data.py TAG [TAG ...]
对每个 run_hours 结果集(一小时一行):净值、逐小时分布、Sharpe、回撤(小时序列 + 小时内分钟权益)、换手、成交率、库存、对冲等待。"""
import json, math, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS = os.path.join(ROOT, "data", "research5", "runs")
CLIP = 5000.0


def load(tag):
    return [r for r in json.load(open(os.path.join(RUNS, tag + ".json"), encoding="utf-8")) if "net" in r]


def slice_detail(r):
    out = dict(intra_dd=0.0, peak_inv_usd=0.0, mean_inv_usd=0.0, hedge_waits=[], net_exposure_peak=0.0)
    ep = os.path.join(r["out_dir"], "equity_curve.parquet")
    if os.path.exists(ep):
        e = pd.read_parquet(ep).equity.astype(float).values
        out["intra_dd"] = float((np.maximum.accumulate(e) - e).max()) if len(e) else 0.0
    fp = os.path.join(r["out_dir"], "fills.parquet")
    if os.path.exists(fp):
        F = pd.read_parquet(fp)
        if len(F):
            F = F.assign(px=F.price.astype(float), q=F.qty.astype(float), s=np.where(F.side == "buy", 1, -1)).sort_values("ts_ns")
            u = F[F.symbol == "BTC-USDC"]; h = F[F.symbol != "BTC-USDC"]
            if len(u):
                pos = np.cumsum(u.s.values * u.q.values) * u.px.values
                out["peak_inv_usd"] = float(np.abs(pos).max())
                t = u.ts_ns.values; t1 = t[0] - (t[0] % 3_600_000_000_000) + 3_600_000_000_000
                dt = np.diff(np.r_[t, t1]) / 1e9
                out["mean_inv_usd"] = float((np.abs(pos) * dt).sum() / 3600.0)
            # 两腿合计净敞口的峰值与对冲等待:每次净敞口离开 0 到回到 |净敞口| < 半个对冲最小单位 的时间
            net = np.cumsum(F.s.values * F.q.values); px = F.px.values; ts = F.ts_ns.values
            out["net_exposure_peak"] = float(np.abs(net * px).max())
            open_t = None
            for i in range(len(F)):
                flat = abs(net[i]) < 0.0005
                if not flat and open_t is None:
                    open_t = ts[i]
                elif flat and open_t is not None:
                    out["hedge_waits"].append((ts[i] - open_t) / 1e9); open_t = None
    return out


def main():
    pd.set_option("display.width", 220)
    for tag in sys.argv[1:]:
        R = load(tag)
        D = pd.DataFrame([{k: r[k] for k in ("feed", "net_corr", "vol", "usdc_usd", "usdc_fills", "fills", "orders", "blocked")} for r in R])
        det = [slice_detail(r) for r in R]
        D["intra_dd"] = [d["intra_dd"] for d in det]; D["peak_inv"] = [d["peak_inv_usd"] for d in det]; D["mean_inv"] = [d["mean_inv_usd"] for d in det]
        D["net_exp_peak"] = [d["net_exposure_peak"] for d in det]
        waits = np.array([w for d in det for w in d["hedge_waits"]])
        D["hh"] = D.feed.str[-2:]; D["day"] = D.feed.str[-11:-3]
        n = len(D); net = D.net_corr.values
        eq = np.cumsum(net); dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
        mu, sd = net.mean(), net.std(ddof=1)
        act = D[D.usdc_fills > 0]
        st = {}
        for r in R:
            for k, v in (r.get("stats") or {}).items():
                st[k] = st.get(k, 0) + v
        print("=" * 20, tag, f"({n} 小时)")
        print(f"净利 ${net.sum():.2f};两腿成交额 ${D.vol.sum():,.0f}(USDC 腿 ${D.usdc_usd.sum():,.0f});每美元 {net.sum() / D.vol.sum() * 1e4:.2f} bp(两腿)/ {net.sum() / D.usdc_usd.sum() * 1e4:.2f} bp(USDC 腿)")
        print(f"小时:正 {int((net > 1e-9).sum())} / 负 {int((net < -1e-9).sum())} / 无成交 {int((D.usdc_fills == 0).sum())};逐小时 均值 ${mu:.2f} 标准差 ${sd:.2f} 最好 ${net.max():.2f} 最差 ${net.min():.2f};中位 ${np.median(net):.2f}")
        print(f"Sharpe:逐小时 {mu / sd:.2f};若各小时独立同分布,日(24 h){mu / sd * math.sqrt(24):.1f}、年 {mu / sd * math.sqrt(8760):.0f};均值的 t 值 {mu / sd * math.sqrt(n):.2f}")
        ds = D.groupby("day").net_corr.sum()
        print(f"按日(每天 4 个抽样小时):{ds.round(2).to_dict()};日口径 Sharpe(8 个点){ds.mean() / ds.std(ddof=1):.2f}")
        print(f"回撤:抽样小时依次相接的最大回撤 ${dd:.2f};小时内(分钟权益)最大回撤 ${D.intra_dd.max():.2f}(中位 ${D.intra_dd[D.usdc_fills > 0].median():.2f},有成交小时)")
        print(f"集中度:最赚 1 / 3 / 5 个小时占 {np.sort(net)[::-1][:1].sum() / net.sum():.0%} / {np.sort(net)[::-1][:3].sum() / net.sum():.0%} / {np.sort(net)[::-1][:5].sum() / net.sum():.0%}")
        print(f"换手:两腿 ${D.vol.sum() / n:,.0f}/小时 → ${D.vol.sum() / n * 24:,.0f}/天、${D.vol.sum() / n * 720 / 1e6:.1f}M/月(按抽样小时外推);相对库存上限(约 5 clip = $25k)每小时周转 {D.vol.sum() / n / 25000:.2f} 次")
        print(f"库存:USDC 腿峰值 ${D.peak_inv.max():,.0f}(有成交小时中位 ${act.peak_inv.median():,.0f}),时间加权均值 ${act.mean_inv.mean():,.0f};两腿净敞口峰值 ${D.net_exp_peak.max():,.0f}")
        print(f"成交率:报单 {int(D.orders.sum()):,} 张,USDC 成交 {int(D.usdc_fills.sum())} 笔 → 每笔成交 {D.orders.sum() / max(1, D.usdc_fills.sum()):.0f} 张报单;每小时报单 中位 {int(D.orders.median())} 最大 {int(D.orders.max())};风控拦截 {int(D.blocked.sum())}")
        if len(waits):
            print(f"对冲:净敞口从出现到抹平 {len(waits)} 次,等待 中位 {np.median(waits):.1f} s、均值 {waits.mean():.1f} s、90% {np.quantile(waits, .9):.1f} s、最长 {waits.max():.0f} s;吃单对冲 {st.get('hedge_market', st.get('hedge_market_urgent', 0) + st.get('hedge_market_fallback', 0))} 次")
        print("计数器:", {k: v for k, v in st.items() if k.startswith(("cancel", "hedge", "no_d", "moved"))})
        print("按 UTC 小时:"); print(D.groupby("hh").agg(hours=("feed", "size"), with_fills=("usdc_fills", lambda x: int((x > 0).sum())), net=("net_corr", "sum"), usdc_usd=("usdc_usd", "sum"),
                                                     orders=("orders", "sum"), worst=("net_corr", "min")).round(2).to_string())
        print("最差 5 小时:", D.sort_values("net_corr").head(5)[["feed", "net_corr", "usdc_usd", "orders"]].round(2).values.tolist())
        print("最好 5 小时:", D.sort_values("net_corr", ascending=False).head(5)[["feed", "net_corr", "usdc_usd", "orders"]].round(2).values.tolist())


if __name__ == "__main__":
    main()
