#!/usr/bin/env python3
"""用户 10-16 设想:"信号亮起的时候直接maker第一档进去然后马上想办法maker出去"。先量进场这一步。只读,线下。

亮起   同 bnpush_signal_markout_20261016.py:本侧 tox_bnpush 穿过当天 99% / 95% 分位;同一侧至少隔 1 秒。
进场   亮起那一格,在预测方向的本侧最优价挂单:卖侧亮(预测涨)→ 买单挂在买一;买侧亮 → 卖单挂在卖一。价格不跟着改。
       之后 1 秒内,对面方向的吃单打到这个价(买单:卖方吃单打到 ≤ 我们的价)就算成交。两种排队假设:
         队首 = 吃单打到这个价就成交;队尾 = 吃单把这个价位打穿(打到更低一跳)才算成交(保守,近似排在已有挂单后面)。
       没有算下单延迟(从亮起那一格起算)。
报告   成交比例、成交前等了多久、成交后 0.1 / 1 / 10 秒的 markout(持仓方向 × (中间价 − 成交价)/成交价,bp;不含返佣)、
       对比:同一批事件里没成交的那些,1 秒后中间价朝预测方向走了多少。
用法   Python314/python.exe scripts/research7/bnpush_lit_maker_entry_20261016.py
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAYS = ("20260923", "20260924", "20261014")
SYMS = {"BTC": ("XBTUSDTM", 0), "ETH": ("ETHUSDTM", 1)}
STEP = 10_000_000
rows = []
for sym, (nat, j) in SYMS.items():
    for day in DAYS:
        g = np.load(os.path.join(ROOT, "data", "factors", "grid", "%s_%s.npz" % (nat, day)))
        t0, n = int(g["t0"]), len(g["ok"])
        ok = g["ok"] & (g["ap"] > g["bp"])
        bp, ap = g["bp"].astype(np.int64), g["ap"].astype(np.int64)
        mid = pd.Series(np.where(ok, (ap + bp) / 2.0, np.nan)).ffill().to_numpy()
        tx = np.load(os.path.join(ROOT, "data", "factors", "tox1", "%s.npz" % day))
        L = np.load(os.path.join(ROOT, "data", "research7", "l2", "%s_%s.npz" % (nat, day)))
        tr = L["kind"] == 0
        T, S, K = L["ts"][tr].astype(np.int64), L["side"][tr].astype(int), L["tick"][tr].astype(np.int64)
        for d, fname in ((1.0, "tox_bnpush_ask"), (-1.0, "tox_bnpush_bid")):
            f = tx[fname][:, j].astype(float)
            # 我们挂买单(d=+1)时,成交来自卖方吃单 = 买盘被打(side 0);挂卖单时来自卖盘被打(side 1)
            hit = S == (0 if d > 0 else 1)
            ht, hk = T[hit], K[hit]
            for pq in (95, 99):
                thr = np.nanpercentile(f, pq)
                cr = np.flatnonzero((f[1:] >= thr) & (f[:-1] < thr)) + 1
                last = -10**9
                for r in cr:
                    if r - last < 100 or r < 100 or r >= n - 1200 or not ok[r]:
                        continue
                    last = r
                    tE = t0 + r * STEP
                    P = bp[r] if d > 0 else ap[r]
                    a, b = np.searchsorted(ht, tE, "right"), np.searchsorted(ht, tE + 1_000_000_000, "right")
                    kk, tt = hk[a:b], ht[a:b]
                    reach = (kk <= P) if d > 0 else (kk >= P)
                    thru = (kk < P) if d > 0 else (kk > P)
                    row = dict(sym=sym, day=day, pq=pq, mv1=d * (mid[r + 100] - mid[r]) / mid[r] * 1e4)
                    for lab, m in (("front", reach), ("back", thru)):
                        if m.any():
                            tf = int(tt[m][0])
                            rf = (tf - t0) // STEP
                            row[lab] = True
                            row[lab + "_wait"] = (tf - tE) / 1e6
                            for tau, kk2 in (("01", 10), ("1", 100), ("10", 1000)):
                                row["%s_mo%s" % (lab, tau)] = d * (mid[min(rf + kk2, n - 1)] - P) / P * 1e4
                        else:
                            row[lab] = False
                    rows.append(row)
        print("  %s %s 完成" % (sym, day), flush=True)
D = pd.DataFrame(rows)
D.to_csv(os.path.join(ROOT, "data", "research7", "bnpush_lit_maker_entry_20261016.csv"), index=False, encoding="utf-8-sig")
for (sym, pq), x in D.groupby(["sym", "pq"]):
    print("\n%s 门槛 %d%%:亮起 %d 次(三天,平均每天 %d 次)。亮起后 1 秒中间价朝预测方向:全部 %+.2f bp" % (sym, pq, len(x), len(x) / 3, x["mv1"].mean()))
    for lab, name in (("front", "队首"), ("back", "队尾")):
        f = x[x[lab]]
        nf = x[~x[lab]]
        print("  %s:1 秒内成交 %5.1f%%(%d 次),成交前中位等待 %4.0f 毫秒 | 成交后 markout 0.1s %+.2f  1s %+.2f  10s %+.2f bp | 没成交的那些 1 秒后中间价朝预测方向 %+.2f bp"
              % (name, 100 * len(f) / len(x), len(f), f[lab + "_wait"].median() if len(f) else np.nan,
                 f[lab + "_mo01"].mean(), f[lab + "_mo1"].mean(), f[lab + "_mo10"].mean(), nf["mv1"].mean()))
