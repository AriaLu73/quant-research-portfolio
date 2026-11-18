#!/usr/bin/env python3
"""research3:领先-滞后关系(用户 2026-10-02 代码评审第 4 点;只读测量,不是回测)。
  a KuCoin BTC-USDT → KuCoin BTC-USDC:USDT 中价在 1 秒内动了 ≥ 1 bp 之后,USDC 中价在其后各时点已经跟了多少。
  b Binance BTC-USDT 永续 → KuCoin BTC-USDT:10 ms 网格收益的互相关(Binance 领先 L 毫秒),以及 Binance 在 100 ms 内动 ≥ 0.5 bp 后 KuCoin 的跟随。
时间戳:KuCoin 用交易所时间;Binance 用文件里的交易所时间 ts(另有本地接收时间 lts,不用)。两个交易所的钟未对齐核实,b 的毫秒级结论只作量级参考。
用法:Python314/python.exe -X utf8 scripts/research3/uh_leadlag.py [day=20260901]"""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
day = sys.argv[1] if len(sys.argv) > 1 else "20260901"
EV = os.path.join(ROOT, "data", "research2", "events")
at = lambda ts, v, t: v[np.clip(np.searchsorted(ts, t, "right") - 1, 0, len(v) - 1)]
a = pd.read_parquet(os.path.join(EV, f"book_BTC_B_{day}.parquet"), columns=["ts", "bb", "ba"]); ats = a.ts.values.astype(np.int64); am = (a.bb.values + a.ba.values) / 2 * 0.1
u = pd.read_parquet(os.path.join(EV, f"book_XBTUSDCM_{day}.parquet"), columns=["ts", "bb", "ba"]); uts = u.ts.values.astype(np.int64); um = (u.bb.values + u.ba.values) / 2 * 0.1
t0, t1 = max(ats[0], uts[0]) + 60_000_000, min(ats[-1], uts[-1]) - 700_000_000
print(f"== a  KuCoin USDT → KuCoin USDC({day})==")
g = np.arange(t0, t1, 1_000_000)                                  # 1 秒网格上找 USDT 的"跳"
r = (at(ats, am, g + 1_000_000) / at(ats, am, g) - 1) * 1e4
for thr in (1.0, 2.0, 4.0):
    k = np.where(np.abs(r) >= thr)[0]
    if not len(k):
        continue
    s = np.sign(r[k]); tk = g[k] + 1_000_000                       # 跳完成的时刻
    u0 = at(uts, um, g[k]); a0 = at(ats, am, g[k])
    row = []
    for h in (0, 1, 2, 5, 10, 30, 60, 300):
        du = s * (at(uts, um, tk + h * 1_000_000) / u0 - 1) * 1e4; da = s * (at(ats, am, tk + h * 1_000_000) / a0 - 1) * 1e4
        row.append(f"{h}s {np.mean(du) / np.mean(da):.0%}")
    print(f"USDT 1 秒内动 ≥ {thr:g} bp:{len(k)} 次,平均 {np.mean(np.abs(r[k])):.2f} bp;USDC 已跟上的比例(USDC 位移 / USDT 位移):" + "  ".join(row))
p = os.path.join(ROOT, "data", "research2", "lead", f"binance_BTC_{day}.parquet")
if os.path.exists(p):
    print(f"== b  Binance → KuCoin USDT({day})==")
    L = pd.read_parquet(p); bts = L.ts.values.astype(np.int64); o = np.argsort(bts, kind="stable"); bts = bts[o]; bm = ((L.bid.values + L.ask.values) / 2)[o]
    g = np.arange(max(t0, bts[0] + 1_000_000), min(t1, bts[-1] - 1_000_000), 10_000)       # 10 ms
    rb = np.diff(np.log(at(bts, bm, g))); rk = np.diff(np.log(at(ats, am, g)))
    rb -= rb.mean(); rk -= rk.mean(); den = np.sqrt((rb ** 2).sum() * (rk ** 2).sum())
    out = []
    for lag in (-20, -10, -5, -2, -1, 0, 1, 2, 5, 10, 20, 50):      # lag > 0:Binance 领先 lag × 10 ms
        c = (rb[:len(rb) - lag] * rk[lag:]).sum() / den if lag >= 0 else (rb[-lag:] * rk[:len(rk) + lag]).sum() / den
        out.append(f"{lag * 10:+d}ms {c:.3f}")
    print("10 ms 收益互相关(正 = Binance 领先):" + "  ".join(out))
    g2 = np.arange(g[0], g[-1], 100_000)
    r = (at(bts, bm, g2 + 100_000) / at(bts, bm, g2) - 1) * 1e4
    for thr in (0.5, 1.0):
        k = np.where(np.abs(r) >= thr)[0]
        if not len(k):
            continue
        s = np.sign(r[k]); b0 = at(bts, bm, g2[k]); k0 = at(ats, am, g2[k]); tk = g2[k] + 100_000
        row = []
        for h_ms in (0, 10, 20, 50, 100, 200, 500, 1000):
            dk = s * (at(ats, am, tk + h_ms * 1000) / k0 - 1) * 1e4; db = s * (at(bts, bm, tk + h_ms * 1000) / b0 - 1) * 1e4
            row.append(f"{h_ms}ms {np.mean(dk) / np.mean(db):.0%}")
        print(f"Binance 100 ms 内动 ≥ {thr:g} bp:{len(k)} 次;KuCoin USDT 已跟上的比例:" + "  ".join(row))
