#!/usr/bin/env python3
"""两因子撤单门槛扫描的汇总(用户 10-17:"做")。只读。

选优标准(跑之前定好):成交那一下的净收益 = Σ 成交额 × (成交后 100 毫秒 markout + 返佣 我方费率),单位美元。
       不用总盈亏选,因为 100 毫秒之后的持仓盈亏几个小时内主要是行情方向(之前的回放里正负来回)。
用法   .venv/Scripts/python.exe scripts/research7/scan_summary_20261017.py <日> <时,时,...> <标签...>
"""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
day, hours, tags = sys.argv[1], sys.argv[2].split(","), sys.argv[3:]
bb = np.concatenate([np.load(os.path.join(ROOT, "data", "research7", "market", "XBTUSDTM_%s_%s.npz" % (day, h.zfill(2))))["bbo"] for h in hours])
bb = bb[np.argsort(bb[:, 0], kind="stable")]
bt, mid = bb[:, 0], (bb[:, 1] + bb[:, 2]) / 2.0 * 0.1
rows = []
for t in tags:
    F = pd.read_csv(os.path.join(ROOT, "data", "research7", "l3_strategy", "%s_%s_fills.csv" % (t, day)))
    F = F[F["maker"] == 1]
    d = json.load(open(os.path.join(ROOT, "data", "research7", "l3_strategy", "%s_%s.json" % (t, day)), encoding="utf-8"))
    px = F["tick"].to_numpy() * 0.1
    sg = np.where(F["sd"] == 0, 1.0, -1.0)
    w = F["size"].to_numpy() * 0.001 * px
    ts = F["ts"].to_numpy(np.int64)
    r = dict(tag=t, fills=len(F), notional=w.sum(), pnl=d.get("pnl_usd", 0.0), rebate=-d["strategy_stats"]["fee"])
    for tau in (1, 10, 100, 1000):
        k = np.searchsorted(bt, ts + tau * 1_000_000, side="right") - 1
        mo = sg * (mid[k] - px) / px * 1e4
        r["mo%d" % tau] = float(np.average(mo, weights=w)) if len(w) else np.nan
        if tau == 100:
            r["edge100_usd"] = float(((mo + 0.7) * w).sum() / 1e4)
    r["hold_usd"] = r["pnl"] - r["edge100_usd"]
    rows.append(r)
D = pd.DataFrame(rows).sort_values("edge100_usd", ascending=False)
print("%s %s 时;按'成交那一下的净收益'(100 ms markout + 返佣,美元)排序" % (day, hours))
print("  %-14s %5s %9s | %6s %6s %6s %6s | %10s %10s %9s" % ("方案", "成交", "成交额$", "1ms", "10ms", "100ms", "1000ms", "成交净收益$", "之后持仓$", "总盈亏$"))
for _, r in D.iterrows():
    print("  %-14s %5d %9.0f | %+6.2f %+6.2f %+6.2f %+6.2f | %+10.1f %+10.1f %+9.1f" % (r.tag, r.fills, r.notional, r.mo1, r.mo10, r.mo100, r.mo1000,
                                                                                      r.edge100_usd, r.hold_usd, r.pnl))
