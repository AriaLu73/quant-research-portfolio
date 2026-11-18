#!/usr/bin/env python3
"""research3:γ 网格(v6、单笔 S15、清洗后的训练 32 小时)的对照表(只读)。选法事先写在 docs/research3/uh_fv2_v4_and_fv3_2026-10-02.md 第 3 节:
每小时净值的夏普最高者;差在 0.05 以内保持 s1。用法:Python314/python.exe -X utf8 scripts/research3/uh_gamma_grid.py"""
import json, os
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS = os.path.join(ROOT, "data", "research5", "runs")
GRID = [("s0.5", "R3C6S15g0.5_train32"), ("s1(现用)", "R3C6S15_train32"), ("s2", "R3C6S15g2_train32"), ("s4", "R3C6S15g4_train32"), ("s0.25", "R3C6S15g0.25_train32"), ("s8", "R3C6S15g8_train32")]
print(f"{'档':<10}{'小时':>4}{'净值':>9}{'夏普/小时':>9}{'两腿成交':>12}{'亏损小时':>6}{'最差':>8}{'吃单对冲':>7}{'到仓位上限撤单':>8}{'拦截':>5}")
for name, tag in GRID:
    p = os.path.join(RUNS, tag + ".json")
    if not os.path.exists(p):
        continue
    R = [x for x in json.load(open(p, encoding="utf-8")) if "net" in x]
    if not R:
        continue
    net = np.array([x["net_corr"] for x in R]); st = lambda k: sum((x.get("stats") or {}).get(k, 0) for x in R)
    sh = net.mean() / net.std(ddof=1) if len(net) > 1 and net.std(ddof=1) > 0 else float("nan")
    print(f"{name:<10}{len(R):>4}{net.sum():>10.2f}{sh:>10.3f}{sum(x['vol'] for x in R):>13,.0f}{int((net < -1e-9).sum()):>7}{net.min():>9.2f}{st('hedge_market'):>8}{st('cancel_cap'):>10}{sum(x['blocked'] for x in R):>7}")
