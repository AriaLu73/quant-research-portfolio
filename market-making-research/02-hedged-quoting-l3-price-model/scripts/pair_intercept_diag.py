#!/usr/bin/env python3
"""MIDCAP-6 体检:拦截成交按中价 +5 bp、回合结算却为负——查买卖两侧各自的成交价相对"稳健参考价"的位置、买卖不平衡与库存。"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import touch_mm_replay as R
tag, day, L = sys.argv[1], sys.argv[2], float(sys.argv[3]); H_MS = 20
d = R.find(tag, day); sym = tag[3:].upper() + "USDTM"; mult = float(R.SPECS[sym]["mult"]); tick = float(R.SPECS[sym]["tick"])
q = pd.read_csv(os.path.join(d, f"quotes-{tag}-{day}.csv.gz"), usecols=["timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"])
q = q[(q.bid_price > 0) & (q.ask_price > q.bid_price)]
t = pd.read_csv(os.path.join(d, f"trades-{tag}-{day}.csv.gz"), usecols=["timestamp", "side", "price", "amount"])
t["usd"] = t.price * t.amount * mult; t["sg"] = np.where(t.side == "buy", 1, -1)
g = t.groupby(["timestamp", "sg"]).agg(pmin=("price", "min"), pmax=("price", "max"), usd=("usd", "sum"), qty=("amount", "sum")).reset_index()
qts = q.timestamp.values.astype(np.int64); ap, bp = q.ask_price.values, q.bid_price.values; aq, bq = q.ask_amount.values, q.bid_amount.values
mid = (ap + bp) / 2
# 稳健参考价:时间加权中价的 60 s 滚动中位(按 1 s 网格)
grid = np.arange(qts[0], qts[-1], 1_000_000); mg = mid[np.clip(np.searchsorted(qts, grid, side="right") - 1, 0, len(qts) - 1)]
ref = pd.Series(mg).rolling(121, center=True, min_periods=1).median().values       # ±60 s 中位(事后量,仅作体检用)
fills = []
for ds in (+1, -1):
    px = bp if ds > 0 else ap; sz = bq if ds > 0 else aq
    ev = np.where(np.r_[False, (np.diff(px) * ds) > 0])[0]
    ours = px[ev] + ds * tick; opp = ap[ev] if ds > 0 else bp[ev]
    ok = ds * (opp - ours) > tick * 0.5; ev, ours = ev[ok], ours[ok]
    et, ep, ez = qts[ev], px[ev], sz[ev]
    tk = g[g.sg == -ds]; ts = tk.timestamp.values.astype(np.int64); fpx = tk.pmax.values if ds > 0 else tk.pmin.values
    j = np.searchsorted(et, ts - int((L + 1) * 1000), side="right") - 1
    ok = j >= 0; jj = np.where(ok, j, 0); ok &= (ts - et[jj]) <= (L + H_MS) * 1000; ok &= ds * (ours[jj] - fpx) >= -tick * 0.5
    k = np.where(ok)[0]; _, first = np.unique(jj[k], return_index=True); k = k[first]; e = jj[k]
    i0 = np.searchsorted(qts, et[e], side="left") - 1
    fills.append(pd.DataFrame(dict(ts=ts[k], d=ds, px=ours[e], usd=np.minimum(R.CLIP, tk.usd.values[k]), bid0=bp[i0], ask0=ap[i0],
                                   pair=(np.abs(fpx[k] - ep[e]) < tick * 0.5) & (tk.qty.values[k] == ez[e]))))
f = pd.concat(fills).sort_values("ts").reset_index(drop=True)
f["ref"] = ref[np.clip(((f.ts.values - qts[0]) // 1_000_000).astype(int), 0, len(ref) - 1)]
f["pos_in_spread"] = (f.px - f.bid0) / (f.ask0 - f.bid0)          # 0 = 事件前买一,1 = 事件前卖一
f["vs_ref_bp"] = f.d * (f.ref - f.px) / f.px * 1e4                # >0:相对 ±60 s 中位价是好价
f["spr_bp"] = (f.ask0 - f.bid0) / f.px * 1e4
pd.set_option("display.width", 220)
print(sym, day, "L", L, "fills", len(f), "usd", round(f.usd.sum()))
for ds, nm in ((1, "我方买"), (-1, "我方卖")):
    x = f[f.d == ds]
    w = x.usd / x.usd.sum()
    print(f"{nm}: 笔 {len(x)} 额 ${x.usd.sum():,.0f} 成对占比 {x.usd[x.pair].sum() / x.usd.sum():.2f} 在点差中的位置(额加权均值){(x.pos_in_spread * w).sum():.2f} "
          f"分位 10/50/90% {x.pos_in_spread.quantile(.1):.2f}/{x.pos_in_spread.median():.2f}/{x.pos_in_spread.quantile(.9):.2f} 相对±60s中位价 {(x.vs_ref_bp * w).sum():+.2f} bp 事件前点差 {(x.spr_bp * w).sum():.1f} bp")
# 配对结算:把买卖按时间顺序做 FIFO 无上限配对的毛利(每万 U)
buy = f[f.d > 0]; sell = f[f.d < 0]
vwap_b = (buy.px * buy.usd).sum() / buy.usd.sum(); vwap_s = (sell.px * sell.usd).sum() / sell.usd.sum()
print(f"全日买入均价 {vwap_b:.6g} 卖出均价 {vwap_s:.6g} 差 {(vwap_s / vwap_b - 1) * 1e4:+.2f} bp(含价格漂移);首末中价 {mid[0]:.6g} → {mid[-1]:.6g}")
f["hour"] = ((f.ts - qts[0]) // 3_600_000_000).astype(int)
h = f.groupby("hour").apply(lambda x: pd.Series(dict(buy=x.usd[x.d > 0].sum(), sell=x.usd[x.d < 0].sum(), vs_ref=(x.vs_ref_bp * x.usd).sum() / x.usd.sum())), include_groups=False)
print(h.round(1).T.to_string())
# ---- 回合结算核对 ----
mid_end = mid[-1]
nocap = float((f.d * (mid_end - f.px) / f.px * f.usd).sum())
print(f"\n无上限、期末中价结算 = ${nocap:,.1f};其中净头寸 ${float((f.d * f.usd).sum()):,.0f}")
for h in (30, 300, 1800, 7200):
    mh = mid[np.clip(np.searchsorted(qts, f.ts.values + h * 1_000_000, side="right") - 1, 0, len(qts) - 1)]
    e = f.d * (mh - f.px) / f.px * f.usd
    print(f"  markout {h:>5}s: 合计 ${e.sum():,.1f}  买 {e[f.d > 0].sum() / f.usd[f.d > 0].sum() * 1e4:+.2f} bp  卖 {e[f.d < 0].sum() / f.usd[f.d < 0].sum() * 1e4:+.2f} bp")
pos = cash = 0.0; path = []
for ts_, d_, p_, u_ in zip(f.ts.values, f.d.values, f.px.values, f.usd.values):
    if (d_ > 0 and pos * p_ >= 3 * R.CLIP - 1e-9) or (d_ < 0 and pos * p_ <= -3 * R.CLIP + 1e-9):
        continue
    pos += d_ * u_ / p_; cash -= d_ * u_; path.append((ts_, pos * p_, cash + pos * p_))
P = pd.DataFrame(path, columns=["ts", "pos_usd", "eq"])
P["hour"] = ((P.ts - qts[0]) // 3_600_000_000).astype(int)
print("带上限(3 clip):期末权益 $%.1f;各小时末 库存$ / 权益$(按最后成交价估值):" % (cash + pos * mid_end))
print(P.groupby("hour").agg(pos=("pos_usd", "last"), eq=("eq", "last"), pos_mean=("pos_usd", "mean")).round(0).T.to_string())
