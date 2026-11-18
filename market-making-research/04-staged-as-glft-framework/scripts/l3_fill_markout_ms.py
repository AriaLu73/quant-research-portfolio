#!/usr/bin/env python3
"""L3 回放成交的毫秒级 markout(用户 10-16:"只准研究毫秒级别")。只读,线下。

输入   data/research7/l3_strategy/<标签>_<日>_fills.csv(l3_strategy_replay.py 的输出)
       data/research7/market/XBTUSDTM_<日>_<时>.npz 的 bbo(L3 重建的买一卖一,每次变化一行,交易所时间,毫秒精度)
markout = 挂单方向 × (成交后 τ 的中间价 − 成交价)/ 成交价 × 1e4(bp),τ = 1、2、5、10、20、50、100 毫秒;按成交额加权。不含返佣(我方费率)。
       交易所时间戳只有毫秒精度,1–2 毫秒的值只作参考。
另报   进簿时前面排了多少张、进簿到成交等了多少毫秒(中位、10% / 90% 分位)。
用法   .venv/Scripts/python.exe scripts/research7/l3_fill_markout_ms.py 20261014 13,14 FAST V21
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
day, hours, tags = sys.argv[1], [h.zfill(2) for h in sys.argv[2].split(",")], sys.argv[3:]
TAUS = (1, 2, 5, 10, 20, 50, 100)
bb = np.concatenate([np.load(os.path.join(ROOT, "data", "research7", "market", "XBTUSDTM_%s_%s.npz" % (day, h)))["bbo"] for h in hours])
bb = bb[np.argsort(bb[:, 0], kind="stable")]
bt, mid = bb[:, 0], (bb[:, 1] + bb[:, 2]) / 2.0 * 0.1
print("%s %s 时 UTC,BTC-USDT;markout 单位 bp(按成交额加权,不含返佣 我方费率);排队 = 进簿时同价位排在我们前面的张数(1 张 = 0.001 BTC)" % (day, hours))
print("  %-6s %5s %9s | %s | %8s %10s %10s" % ("方案", "成交", "成交额$", " ".join("%7s" % ("%dms" % t) for t in TAUS), "排队中位", "等待中位ms", "等待90%ms"))
for tag in tags:
    F = pd.read_csv(os.path.join(ROOT, "data", "research7", "l3_strategy", "%s_%s_fills.csv" % (tag, day)))
    F = F[F["maker"] == 1]
    px = F["tick"].to_numpy() * 0.1
    sg = np.where(F["sd"] == 0, 1.0, -1.0)
    w = F["size"].to_numpy() * 0.001 * px
    ts = F["ts"].to_numpy(np.int64)
    cells = []
    for t in TAUS:
        k = np.searchsorted(bt, ts + t * 1_000_000, side="right") - 1
        cells.append("%+7.2f" % np.average(sg * (mid[k] - px) / px * 1e4, weights=w))
    print("  %-6s %5d %9.0f | %s | %8.0f %10.0f %10.0f" % (tag, len(F), w.sum(), " ".join(cells), F["ahead0"].median(),
                                                         F["wait_ms"].median(), F["wait_ms"].quantile(0.9)))
