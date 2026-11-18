#!/usr/bin/env python3
"""research3:BTC 单笔规模阶梯(训练 32 小时,清洗后的切片,队首排队、1.8 ms)的对照表(只读)。
每档:净值、两腿成交、USDC 成交、每 USDC$ 净 bp、亏损小时、最差小时、单腿持仓峰值、风控拦截 / 被拒、已跑小时数。
用法:Python314/python.exe -X utf8 scripts/research3/uh_size_ladder.py"""
import json, os
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS = os.path.join(ROOT, "data", "research5", "runs")
LADDER = [("R3FV5P1_train32", "近 5k + 远 25k(现在)"), ("R3C5P1n10_train32", "近 10k + 远 25k"), ("R3C6S15_train32", "近 7.5k + 远 37.5k"),
          ("R3C6S20_train32", "近 10k + 远 49k"), ("R3C6S30_train32", "近 15k + 远 49k")]


def peak_leg(out_dir):
    fp = os.path.join(out_dir, "fills.parquet")
    if not os.path.exists(fp):
        return 0.0
    F = pd.read_parquet(fp)
    if not len(F):
        return 0.0
    F = F.assign(px=F.price.astype(float), q=F.qty.astype(float), s=np.where(F.side == "buy", 1, -1)).sort_values("ts_ns")
    u = F[F.symbol == "BTC-USDC"]
    return float(np.abs(np.cumsum(u.s.values * u.q.values) * u.px.values).max()) if len(u) else 0.0


base = None
print(f"{'档位':<22}{'小时':>4}{'净值':>9}{'两腿成交':>11}{'USDC 成交':>11}{'bp/USDC$':>9}{'亏损小时':>6}{'最差':>8}{'持仓峰值':>9}{'拦截':>5}{'被拒':>5}")
for tag, name in LADDER:
    p = os.path.join(RUNS, tag + ".json")
    if not os.path.exists(p):
        print(f"{name:<22} 未开始"); continue
    R = [x for x in json.load(open(p, encoding="utf-8")) if "net" in x]
    if not R:
        print(f"{name:<22} 未出结果"); continue
    net = sum(x["net_corr"] for x in R); usdc = sum(x["usdc_usd"] for x in R)
    ref = sum(x["stats"].get("refused", 0) for x in R if x.get("stats"))
    print(f"{name:<22}{len(R):>4}{net:>10.2f}{sum(x['vol'] for x in R):>12,.0f}{usdc:>12,.0f}{net / usdc * 1e4 if usdc else 0:>9.2f}{sum(x['net_corr'] < -1e-9 for x in R):>7}"
          f"{min(x['net_corr'] for x in R):>9.2f}{max(peak_leg(x['out_dir']) for x in R):>10,.0f}{sum(x['blocked'] for x in R):>5}{ref:>5}")
