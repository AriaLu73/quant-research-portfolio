#!/usr/bin/env python3
"""H-W 的下单量问题:向内改善事件里只有 1–2% 是成对打印的挂单腿,其余是抢一档机器人。事件发生当时能否认出来?
对每个改善事件:新单量 Z;该量在过去 N=2000 个改善事件里出现的频率(滚动、只用过去);改善幅度(tick);是否随后 ≤ 20 ms 被等量吃掉(成对)。
输出:按"量的滚动频率"分桶的成对命中率与成对额覆盖率;按间隔(ms)的成对额分布。"""
import os, sys
from collections import Counter, deque
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import touch_mm_replay as R

rows = []; gaps = []
for tag in sys.argv[1].split(","):
    for day in sys.argv[2].split(","):
        d = R.find(tag, day)
        if not d:
            continue
        sym = tag[3:].upper() + "USDTM"; mult = float(R.SPECS[sym]["mult"]); tick = float(R.SPECS[sym]["tick"])
        q = pd.read_csv(os.path.join(d, f"quotes-{tag}-{day}.csv.gz"), usecols=["timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"])
        q = q[(q.bid_price > 0) & (q.ask_price > q.bid_price)]
        t = pd.read_csv(os.path.join(d, f"trades-{tag}-{day}.csv.gz"), usecols=["timestamp", "side", "price", "amount"])
        t["sg"] = np.where(t.side == "buy", 1, -1)
        g = t.groupby(["timestamp", "sg"]).agg(pmin=("price", "min"), pmax=("price", "max"), qty=("amount", "sum")).reset_index()
        qts = q.timestamp.values.astype(np.int64)
        for ds, px, sz in ((1, q.bid_price.values, q.bid_amount.values), (-1, q.ask_price.values, q.ask_amount.values)):
            ev = np.where(np.r_[False, (np.diff(px) * ds) > 0])[0]
            et, ep, ez = qts[ev], px[ev], sz[ev]; step = np.rint(np.abs(px[ev] - px[ev - 1]) / tick)
            tk = g[g.sg == -ds]; ts = tk.timestamp.values.astype(np.int64); fpx = tk.pmax.values if ds > 0 else tk.pmin.values; tq = tk.qty.values
            j = np.searchsorted(et, ts, side="right") - 1          # 成交前最近的改善事件(含同毫秒)
            ok = (j >= 0); jj = np.where(ok, j, 0)
            m = ok & (ts - et[jj] <= 20000) & (np.abs(fpx - ep[jj]) < tick * 0.5) & (tq == ez[jj])
            is_pair = np.zeros(len(ev), bool); is_pair[jj[m]] = True
            gap = np.full(len(ev), np.nan); gap[jj[m]] = (ts[m] - et[jj[m]]) / 1000.0
            # 滚动频率:该量在过去 2000 个事件中的占比
            win = deque(); cnt = Counter(); fr = np.zeros(len(ev))
            for i, z in enumerate(ez):
                fr[i] = cnt[z] / max(1, len(win))
                win.append(z); cnt[z] += 1
                if len(win) > 2000:
                    cnt[win.popleft()] -= 1
            rows.append(pd.DataFrame(dict(sym=sym, day=day, fr=fr, step=step, pair=is_pair, gap=gap, usd=ez * mult * ep)))
E = pd.concat(rows, ignore_index=True); E["pusd"] = np.where(E.pair, E.usd, 0.0); pd.set_option("display.width", 220)
print("事件总数", len(E), "成对事件", int(E.pair.sum()), f"({E.pair.mean():.2%});成对额 ${E.usd[E.pair].sum():,.0f}")
E["frb"] = pd.cut(E.fr, [-1, 0.001, 0.005, 0.02, 0.05, 0.2, 1.0], labels=["<0.1%", "0.1-0.5%", "0.5-2%", "2-5%", "5-20%", ">20%"])
a = E.groupby("frb", observed=True).agg(events=("pair", "size"), pairs=("pair", "sum"), pair_usd=("pusd", "sum"))
a["precision"] = a.pairs / a.events; a["event_share"] = a.events / len(E); a["pair_usd_share"] = a.pair_usd / E.usd[E.pair].sum()
print("\n按该挂单量在过去 2000 个改善事件里的出现频率分桶:"); print(a.round(4).to_string())
b = E.groupby(E.step.clip(upper=5)).agg(events=("pair", "size"), pairs=("pair", "sum")); b["precision"] = b.pairs / b.events
print("\n按改善幅度(tick,≥5 归 5):"); print(b.round(4).to_string())
P = E[E.pair]; P = P.assign(gb=pd.cut(P.gap, [-1, 0.5, 1.5, 2.5, 3.5, 4.5, 6.5, 10.5, 21], labels=["0", "1", "2", "3", "4", "5-6", "7-10", "11-20"]))
c = P.groupby("gb", observed=True).usd.sum() / P.usd.sum()
print("\n成对打印额按 挂单→吃单 间隔(ms,交易所时间戳)分布(仅先显示后成交的那部分):"); print(c.round(3).to_string())
for s, X in E.groupby("sym"):
    k = X[X.fr < 0.005]
    print(f"{s}: 事件/秒 {len(X) / X.day.nunique() / 86400:.1f} → 只跟频率 <0.5% 的量:{len(k) / X.day.nunique() / 86400:.2f}/秒,命中率 {k.pair.mean():.1%},覆盖成对额 {k.usd[k.pair].sum() / max(1, X.usd[X.pair].sum()):.0%}")
