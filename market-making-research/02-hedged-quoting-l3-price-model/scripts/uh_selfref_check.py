#!/usr/bin/env python3
"""research3:自引用检查(用户 2026-10-02 代码评审第 1 点)。回测里策略看到的盘口只有公共挂单(engine/backtest/runner.py _book_view 只导出 public_qty),
实盘的 L2 推送包含我方挂单。本脚本只读地量:回测中我方 USDC 报价有多少时间比公共买一/卖一更优(= 实盘里它自己就是买一/卖一),
以及"含我方挂单的中价"相对"公共中价"偏了多少 bp(实盘里基差观测会被带偏的量)。1 秒网格,订单生效 = 下单后 1.8 ms 到撤单后 1.8 ms / 成交完。
用法:Python314/python.exe -X utf8 scripts/research3/uh_selfref_check.py <结果集 tag> [USDC 合约=BTC-USDC]"""
import gzip, json, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tag = sys.argv[1]; sym = sys.argv[2] if len(sys.argv) > 2 else "BTC-USDC"
R = [x for x in json.load(open(os.path.join(ROOT, "data", "research5", "runs", tag + ".json"), encoding="utf-8")) if "net" in x]
LAT = 1_800_000
tot = dict(n=0, bid_in=0, ask_in=0, both_in=0, any_in=0); shifts = []; shift_when = []
for r in R:
    feed, day = r["feed"], r["feed"].split("/")[1].split("_")[0]
    p = os.path.join(ROOT, "data", "oos", feed, "kucoin", "swap", sym, "feed_raw", f"depth_deltas-{day}.jsonl.gz")
    B, A, ts, bb, ba = {}, {}, [], [], []
    with gzip.open(p, "rt") as f:
        for l in f:
            o = json.loads(l)
            if o.get("snapshot"):
                B.clear(); A.clear()
            for side, book in (("bids", B), ("asks", A)):
                for px, q in o[side]:
                    if float(q) == 0:
                        book.pop(float(px), None)
                    else:
                        book[float(px)] = 1
            if B and A:
                ts.append(o["ts_ns"]); bb.append(max(B)); ba.append(min(A))
    ts, bb, ba = np.array(ts), np.array(bb), np.array(ba)
    orders, qty = {}, {}
    for l in open(os.path.join(r["out_dir"], "broker_sim_wal.jsonl"), encoding="utf-8"):
        o = json.loads(l)
        if o["t"] == "order" and o["symbol"] == sym and o.get("price"):
            orders[o["id"]] = [o["side"], float(o["price"]), o["ts_ns"] + LAT, None]; qty[o["id"]] = float(o["qty"])
        elif o["t"] == "cancel" and o["id"] in orders and orders[o["id"]][3] is None:
            orders[o["id"]][3] = o["ts_ns"] + LAT
        elif o["t"] == "fill" and o["id"] in orders:
            qty[o["id"]] -= float(o["qty"])
            if qty[o["id"]] <= 1e-12 and orders[o["id"]][3] is None:
                orders[o["id"]][3] = o["ts_ns"]
    g = np.arange(ts[0] + 120_000_000_000, ts[0] + 3_600_000_000_000, 1_000_000_000)
    i = np.clip(np.searchsorted(ts, g, "right") - 1, 0, len(ts) - 1); pb, pa = bb[i], ba[i]
    ob = np.full(len(g), -np.inf); oa = np.full(len(g), np.inf)
    for side, px, t0, t1 in orders.values():
        a, b = np.searchsorted(g, t0, "left"), np.searchsorted(g, t1 if t1 is not None else g[-1] + 1, "left")
        if b > a:
            if side == "buy":
                ob[a:b] = np.maximum(ob[a:b], px)
            else:
                oa[a:b] = np.minimum(oa[a:b], px)
    bi, ai = ob > pb, oa < pa
    mid_pub = (pb + pa) / 2; mid_live = (np.maximum(pb, ob) + np.minimum(pa, oa)) / 2
    sh = (mid_live - mid_pub) / mid_pub * 1e4
    tot["n"] += len(g); tot["bid_in"] += int(bi.sum()); tot["ask_in"] += int(ai.sum()); tot["both_in"] += int((bi & ai).sum()); tot["any_in"] += int((bi | ai).sum())
    shifts.append(sh); shift_when.append(sh[bi | ai])
sh = np.concatenate(shifts); sw = np.concatenate(shift_when); n = tot["n"]
print(f"{tag}:{len(R)} 小时,{n} 秒")
print(f"我方买价比公共买一更优的时间 {tot['bid_in'] / n:.1%};卖价更优 {tot['ask_in'] / n:.1%};任一侧 {tot['any_in'] / n:.1%};两侧同时 {tot['both_in'] / n:.1%}")
print(f"含我方挂单的中价 − 公共中价(bp):全部时间 |偏移| 均值 {np.abs(sh).mean():.3f}、90% {np.quantile(np.abs(sh), .9):.2f}、99% {np.quantile(np.abs(sh), .99):.2f}、最大 {np.abs(sh).max():.1f}")
if len(sw):
    print(f"  我方在盘口内的那些秒:|偏移| 中位 {np.median(np.abs(sw)):.2f}、90% {np.quantile(np.abs(sw), .9):.2f};|偏移| > 0.5 bp 的时间占全部 {float((np.abs(sh) > 0.5).mean()):.1%},> 1 bp {float((np.abs(sh) > 1).mean()):.1%},> 2 bp {float((np.abs(sh) > 2).mean()):.1%}")
