#!/usr/bin/env python3
"""失败分析:成对打印的"挂单 → 吃单"间隔分布与体量,按日(事件 parquet 口径,9 月购买数据)。
成对 = 某侧最优价向内改善(新单价 P、量 Z)后 ≤ 20 ms 被等量吃掉(先显示后成交);另计"成交价好于显示盘口"(新单与成交同毫秒或晚显示)的吃单额。"""
import os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pair_intercept_sim as PI

BINS = [-1, 0.5, 1.5, 2.5, 3.5, 4.5, 6.5, 10.5, 21]; LAB = ["0", "1", "2", "3", "4", "5-6", "7-10", "11-20"]


def one(a):
    tag, day = a
    try:
        q, t, tick, mult, sym = PI.load_qt(tag, day)
        t["usd"] = t.price * t.amount * mult; t["sg"] = np.where(t.side == "buy", 1, -1)
        g = t.groupby(["timestamp", "sg"]).agg(pmin=("price", "min"), pmax=("price", "max"), qty=("amount", "sum"), usd=("usd", "sum")).reset_index()
        qts = q.timestamp.values.astype(np.int64); out = dict(sym=sym, day=day, taker=float(g.usd.sum()), inside=0.0, **{f"g{l}": 0.0 for l in LAB})
        for ds, px, sz in ((1, q.bid_price.values, q.bid_amount.values), (-1, q.ask_price.values, q.ask_amount.values)):
            ev = np.where(np.r_[False, (np.diff(px) * ds) > 0])[0]; et, ep, ez = qts[ev], px[ev], sz[ev]
            tk = g[g.sg == -ds]; ts = tk.timestamp.values.astype(np.int64); fpx = tk.pmax.values if ds > 0 else tk.pmin.values
            i0 = np.searchsorted(qts, ts, side="left") - 1; ok0 = i0 >= 0
            touch = px[np.clip(i0, 0, len(px) - 1)]
            out["inside"] += float(tk.usd.values[ok0 & (ds * (fpx - touch) > tick * 0.5)].sum())            # 成交价好于显示的最优价
            if not len(ev):
                continue
            j = np.searchsorted(et, ts, side="left") - 1; ok = j >= 0; jj = np.where(ok, j, 0)             # 严格早于成交的最近改善事件
            m = ok & (ts - et[jj] <= 20000) & (np.abs(fpx - ep[jj]) < tick * 0.5) & (tk.qty.values == ez[jj])
            gap = (ts[m] - et[jj[m]]) / 1000.0; u = tk.usd.values[m]
            h = np.histogram(gap, bins=BINS, weights=u)[0]
            for l, v in zip(LAB, h):
                out[f"g{l}"] += float(v)
        return out
    except Exception as e:  # noqa: BLE001
        return dict(sym=tag, day=day, error=repr(e)[:100])


if __name__ == "__main__":
    syms = sys.argv[1].split(","); days = sys.argv[2].split(",")
    jobs = [(s, d) for s in syms for d in days if PI.has_data(s, d)]
    with ProcessPoolExecutor(6) as ex:
        R = pd.DataFrame(list(ex.map(one, jobs)))
    if "error" in R:
        R = R[R.error.isna()]
    pd.set_option("display.width", 220)
    g = R.groupby("day").sum(numeric_only=True)
    o = pd.DataFrame({"吃单额$": g.taker, "显示后成交的成对额占比": g[[f"g{l}" for l in LAB]].sum(axis=1) / g.taker, "成交价好于显示(同毫秒)占比": g.inside / g.taker})
    for l in LAB:
        o[f"间隔{l}ms"] = g[f"g{l}"] / g.taker
    o["可拦截(间隔≥3ms)占比"] = g[["g3", "g4", "g5-6", "g7-10", "g11-20"]].sum(axis=1) / g.taker
    print(o.round(3).T.to_string())
