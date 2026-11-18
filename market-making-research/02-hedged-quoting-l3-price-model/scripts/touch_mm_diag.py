#!/usr/bin/env python3
"""MIDCAP-4(阶段 9 queue/fill 的体检):回放结果是不是撮合假设的假象?
① 参与率 = 我方成交额 / 全市场吃单成交额(队首口径下的上限;真实份额要除以同价位竞争者数)。
② 吃单到达时刻距该侧最优价上次变动的时间分布(解释 3→10 ms 的断崖)。
③ 盘口价位寿命:最优价每分钟变动次数、向内改善(penny)事件占比——别的做市商是否已经在互相抢一档。
④ 吃单聚合口径:同一毫秒 vs 相邻 2 ms 内同向连续 id 合并,订单数差多少。"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import touch_mm_replay as R

rows = []
for tag in sys.argv[1].split(","):
    for day in sys.argv[2].split(","):
        if not R.find(tag, day):
            continue
        d = R.find(tag, day); sym = tag[3:].upper() + "USDTM"; mult = float(R.SPECS[sym]["mult"]); tick = float(R.SPECS[sym]["tick"])
        q = pd.read_csv(os.path.join(d, f"quotes-{tag}-{day}.csv.gz"), usecols=["timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"])
        q = q[(q.bid_price > 0) & (q.ask_price > q.bid_price)]
        t = pd.read_csv(os.path.join(d, f"trades-{tag}-{day}.csv.gz"), usecols=["timestamp", "id", "side", "price", "amount"])
        t["usd"] = t.price * t.amount * mult; t["sg"] = np.where(t.side == "buy", 1, -1)
        tot = t.usd.sum()
        r0 = R.replay(tag, day, 3, None, "touch", 0.0); r1 = R.replay(tag, day, 3, None, "penny", 0.0)
        qts = q.timestamp.values; ap, bp = q.ask_price.values, q.bid_price.values
        ca = np.r_[True, np.diff(ap) != 0]; cb = np.r_[True, np.diff(bp) != 0]
        la = np.maximum.accumulate(np.where(ca, qts, qts[0])); lb = np.maximum.accumulate(np.where(cb, qts, qts[0]))
        g = t.groupby(["timestamp", "sg"]).usd.sum().reset_index()
        i0 = np.searchsorted(qts, g.timestamp.values, side="left") - 1; ok = i0 >= 0; g = g[ok]; i0 = i0[ok]
        age = (g.timestamp.values - np.where(g.sg.values > 0, la[i0], lb[i0])) / 1000.0     # ms
        w = g.usd.values
        def share(lo, hi):
            return float(w[(age >= lo) & (age < hi)].sum() / w.sum())
        hrs = (qts[-1] - qts[0]) / 3.6e9
        imp_a = int((np.diff(ap) < 0).sum()); imp_b = int((np.diff(bp) > 0).sum()); wor_a = int((np.diff(ap) > 0).sum()); wor_b = int((np.diff(bp) < 0).sum())
        # 聚合口径:相邻成交 同向 且 时间差 ≤ 2 ms → 同一张吃单
        ts = t.timestamp.values; same = (np.diff(ts) <= 2000) & (np.diff(t.sg.values) == 0)
        n_ord2 = int(1 + (~same).sum()); n_ord1 = len(g)
        rows.append(dict(sym=sym, day=day, taker_usd=tot, n_trades=len(t), n_ord_ms=n_ord1, n_ord_2ms=n_ord2,
                         part_touch=r0["vol"] / tot, part_penny=r1["vol"] / tot, med_order_usd=float(np.median(w)),
                         age_lt1=share(0, 1), age_1_3=share(1, 3), age_3_10=share(3, 10), age_10_50=share(10, 50), age_50_1s=share(50, 1000), age_gt1s=share(1000, 1e12),
                         px_chg_per_min=(ca.sum() + cb.sum()) / (hrs * 60), improve_share=(imp_a + imp_b) / max(1, imp_a + imp_b + wor_a + wor_b),
                         spr_ticks=r0["spread_med_ticks"], tick_bp=r0["tick_bp"]))
        print(rows[-1], flush=True)
D = pd.DataFrame(rows); pd.set_option("display.width", 260)
print(D.round(3).to_string(index=False))
D.to_csv(os.path.join(R.ROOT, "data", "research3", "touch_mm_diag.csv"), index=False)
