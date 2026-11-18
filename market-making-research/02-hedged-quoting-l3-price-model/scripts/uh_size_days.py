#!/usr/bin/env python3
"""research3:BTC 20 天回测,新单笔(C6S15:近 7.5k + 远 37.5k)与基准(C5P1:近 5k + 远 25k)逐日对比(只读;只列两边都跑完 24 小时的日子)。
用法:Python314/python.exe -X utf8 scripts/research3/uh_size_days.py"""
import glob, json, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS = os.path.join(ROOT, "data", "research5", "runs")


def days(prefix):
    out = {}
    for p in sorted(glob.glob(os.path.join(RUNS, prefix + "_2026*.json"))):
        R = [x for x in json.load(open(p, encoding="utf-8")) if "net" in x]
        if len(R) == 24:
            out[os.path.basename(p)[len(prefix) + 1:-5]] = R
    return out


A, B = days("C6S15"), days("C5P1")
f = lambda R: (sum(x["net_corr"] for x in R), sum(x["vol"] for x in R), min(x["net_corr"] for x in R), sum(x["blocked"] for x in R))
print("日期        新单笔 净    成交      最差小时  拦截 审计 |  基准 净    成交")
ta = tb = va = vb = 0.0; n = 0
for d in sorted(A):
    na, voa, wa, ba = f(A[d])
    lp = os.path.join(ROOT, "logs", f"r3_C6S15_{d}_behaviour.txt")
    ok = "过" if os.path.exists(lp) and "BEHAVIOUR PASS" in open(lp, encoding="utf-8").read() else "未过"
    line = f"{d}  {na:>9.2f} {voa:>10,.0f} {wa:>9.2f} {ba:>5} {ok:>3} |"
    if d in B:
        nb, vob, _, _ = f(B[d]); line += f" {nb:>8.2f} {vob:>10,.0f}"
        ta += na; tb += nb; va += voa; vb += vob; n += 1
    print(line)
if n:
    print(f"两边都有的 {n} 天:新单笔 净 {ta:.2f}(日均 {ta / n:.2f})成交 {va:,.0f} | 基准 净 {tb:.2f}(日均 {tb / n:.2f})成交 {vb:,.0f} | 利润 {ta / tb - 1:+.0%} 成交 {va / vb - 1:+.0%}")
allA = [x for R in A.values() for x in R]
if allA:
    nd = len(A); net = sum(x["net_corr"] for x in allA); vol = sum(x["vol"] for x in allA)
    print(f"新单笔已完成 {nd} 天:净 {net:.2f},日均 {net / nd:.2f},日均两腿成交 {vol / nd:,.0f} → {vol / nd * 30 / 1e6:.1f}M/月、净 {net / nd * 30:,.0f}/月;亏损日 {sum(sum(x['net_corr'] for x in R) < 0 for R in A.values())};最差小时 {min(x['net_corr'] for x in allA):.2f}")
