#!/usr/bin/env python3
"""MIDCAP-7:成对打印的价格位置是不是"公允价"的信号?
成对打印 = 某侧最优价向内改善(新单,价 P、量 Z)后 ≤ 10 ms 内被一张等量吃单吃掉(首档价 = P、量 = Z);另把"比显示盘口好的成交"(行情流晚 1 ms)也算。
对每笔成对打印:x = (P − 事件前中价) / 事件前半点差 ∈ [−1, 1](−1 = 买一,+1 = 卖一)。
检验:未来 h 的中价变化(以事件前半点差为单位)对 x 的回归斜率 b_h 与相关;h = 1 s … 60 min。b ≈ 1 表示打印价就是未来中价(公允价),b ≈ 0 表示无信息。
同时给:拦截成交(我方在 P 内 1 tick)相对未来中价的收益随 h 的衰减。"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import touch_mm_replay as R

HS = [1, 5, 30, 60, 300, 900, 3600]
rows = []
for tag in sys.argv[1].split(","):
    for day in sys.argv[2].split(","):
        d = R.find(tag, day)
        if not d:
            continue
        sym = tag[3:].upper() + "USDTM"; mult = float(R.SPECS[sym]["mult"]); tick = float(R.SPECS[sym]["tick"])
        q = pd.read_csv(os.path.join(d, f"quotes-{tag}-{day}.csv.gz"), usecols=["timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"])
        q = q[(q.bid_price > 0) & (q.ask_price > q.bid_price)]
        t = pd.read_csv(os.path.join(d, f"trades-{tag}-{day}.csv.gz"), usecols=["timestamp", "side", "price", "amount"])
        t["usd"] = t.price * t.amount * mult; t["sg"] = np.where(t.side == "buy", 1, -1)
        g = t.groupby(["timestamp", "sg"]).agg(pmin=("price", "min"), pmax=("price", "max"), usd=("usd", "sum"), qty=("amount", "sum")).reset_index()
        qts = q.timestamp.values.astype(np.int64); ap, bp = q.ask_price.values, q.bid_price.values; aq, bq = q.ask_amount.values, q.bid_amount.values
        mid = (ap + bp) / 2
        # 稳定中价:取事件前 ≥ 200 ms 的那一帧(避开新单自身与抢一档的抖动)
        ts = g.timestamp.values.astype(np.int64); sg = g.sg.values
        i0 = np.searchsorted(qts, ts, side="left") - 1; ib = np.searchsorted(qts, ts - 200_000, side="left") - 1
        ok = ib >= 0; g, ts, sg, i0, ib = g[ok], ts[ok], sg[ok], i0[ok], ib[ok]
        fpx = np.where(sg > 0, g.pmin.values, g.pmax.values)
        m0 = mid[ib]; half = (ap[ib] - bp[ib]) / 2
        touch = np.where(sg > 0, ap[i0], bp[i0]); tsz = np.where(sg > 0, aq[i0], bq[i0])
        da = np.r_[0, np.diff(ap)]; db = np.r_[0, np.diff(bp)]
        la = np.maximum.accumulate(np.where(da != 0, np.arange(len(qts)), 0)); lb = np.maximum.accumulate(np.where(db != 0, np.arange(len(qts)), 0))
        j = np.where(sg > 0, la[i0], lb[i0]); age = (ts - qts[j]) / 1000.0
        imp = np.where(sg > 0, da[j] < 0, db[j] > 0)
        k = np.rint(sg * (fpx - touch) / tick)
        pairA = (k == 0) & (age <= 10) & imp & (g.qty.values == tsz)      # 显示过的新单被等量吃掉
        pairB = (k < 0)                                                     # 成交价好于显示盘口(新单没来得及显示)
        kind = np.select([pairA, pairB], ["pairA", "pairB"], "other")
        x = (fpx - m0) / half
        rec = dict(sym=sym, day=day, ts=ts, sg=sg, kind=kind, x=x, usd=g.usd.values, half_bp=half / m0 * 1e4)
        for h in HS:
            mh = mid[np.clip(np.searchsorted(qts, ts + h * 1_000_000, side="right") - 1, 0, len(qts) - 1)]
            rec[f"y{h}"] = (mh - m0) / half
            rec[f"valid{h}"] = ts + h * 1_000_000 <= qts[-1]
        rows.append(pd.DataFrame(rec))
G = pd.concat(rows); pd.set_option("display.width", 250)
G = G[(G.x.abs() <= 1.5) & (G.half_bp > 0)]
print("样本:", G.groupby("kind").agg(n=("usd", "size"), usd=("usd", "sum"), x_mean=("x", "mean"), absx=("x", lambda v: v.abs().mean()), half_bp=("half_bp", "median")).round(3).to_string())
print("\n成对打印在点差中的位置分布(x:−1 买一,0 中价,+1 卖一),按吃单方向:")
P = G[G.kind != "other"]
print(P.groupby("sg").x.describe(percentiles=[.1, .25, .5, .75, .9]).round(2).to_string())
print("\n回归 y_h = a + b·x(单位:事件前半点差);分 kind:")
out = []
for kind, X in G.groupby("kind"):
    for h in HS:
        v = X[X[f"valid{h}"]]; xx, yy = v.x.values, v[f"y{h}"].values
        ok = np.isfinite(xx) & np.isfinite(yy) & (np.abs(yy) < 50)
        xx, yy = xx[ok], yy[ok]
        b = np.cov(xx, yy)[0, 1] / np.var(xx); r = np.corrcoef(xx, yy)[0, 1]
        out.append(dict(kind=kind, h=h, n=len(xx), b=b, corr=r))
print(pd.DataFrame(out).pivot(index="h", columns="kind", values=["b", "corr"]).round(3).to_string())
print("\n按合约(pairA+pairB 合并)的 b_h:")
o2 = []
for s, X in P.groupby("sym"):
    r = dict(sym=s, n=len(X), half_bp=float(X.half_bp.median()))
    for h in HS:
        v = X[X[f"valid{h}"]]; xx, yy = v.x.values, v[f"y{h}"].values; ok = np.abs(yy) < 50
        r[f"b{h}"] = np.cov(xx[ok], yy[ok])[0, 1] / np.var(xx[ok])
    o2.append(r)
print(pd.DataFrame(o2).round(3).to_string(index=False))
G.to_parquet(os.path.join(R.ROOT, "data", "research3", "pair_print_signal.parquet"))
