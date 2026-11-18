#!/usr/bin/env python3
"""research3:FV2 的基差中位数需要近 60 秒内 ≥ 30 个观测(USDC 盘口每次更新取一个,最密每秒一个)。本脚本只读地统计:
各小时里"观测不足 30 个"的秒数占比 —— 不足时 v1–v3 的 _quote 直接返回、已挂的单没人管(2026-10-02 在 ETH 09-02 10 时发现)。
用法:Python314/python.exe -X utf8 scripts/research3/uh_basis_obs_scan.py <USDC 合约> day1,day2,..."""
import gzip, json, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sym, days = sys.argv[1], sys.argv[2].split(",")
for day in days:
    out = []
    for h in range(24):
        p = os.path.join(ROOT, "data", "oos", "ku_buy", f"{day}_{h:02d}", "kucoin", "swap", sym, "feed_raw", f"depth_deltas-{day}.jsonl.gz")
        if not os.path.exists(p):
            continue
        obs, last = [], -1e30
        with gzip.open(p, "rt") as f:
            for l in f:
                i = l.find('"ts_ns":') + 8; t = int(l[i:l.find(",", i)])
                if t - last >= 1e9:
                    obs.append(t); last = t
        obs = np.array(obs); g = np.arange(obs[0] + 60e9, obs[0] + 3600e9, 1e9)
        n = np.searchsorted(obs, g, "right") - np.searchsorted(obs, g - 60e9, "right")
        out.append((h, float((n < 30).mean() * 100)))
    bad = [(h, round(x, 1)) for h, x in out if x > 0]
    print(day, sym, f"小时数 {len(out)};有观测不足的小时 {len(bad)} 个;全天不足秒数占比 {np.mean([x for _, x in out]):.2f}%;明细(小时, %):", bad, flush=True)
