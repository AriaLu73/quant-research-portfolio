#!/usr/bin/env python3
"""tox_bnpush 信号亮起之后的 markout(用户 10-16:"我就问你信号亮起之后markout怎么样")。只读,线下。不算挂单 / 吃单盈亏。

日子   09-23、09-24、10-14,12–18 时 UTC;BTC、ETH。因子 = data/factors/tox1 的 tox_bnpush_ask / _bid(10 毫秒网格)。
亮起   某一侧的值从门槛下方穿到上方的那一格;门槛 = 当天这一侧值的 90 / 95 / 99 分位(同一天的分布,有一点"事先知道")。
       同一侧两次亮起至少隔 1 秒。卖侧亮 = 预测价格往上;买侧亮 = 预测往下。
markout = 预测方向 × (亮起后 τ 的中间价 − 亮起那一格的中间价)/ 中间价 × 1e4(bp),τ = 10、50、100 毫秒,1、10、60 秒。按事件等权平均。
对照   同样数量的随机时刻、随机方向(种子固定)。
用法   Python314/python.exe scripts/research7/bnpush_signal_markout_20261016.py
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAYS = ("20260923", "20260924", "20261014")
SYMS = {"BTC": ("XBTUSDTM", 0), "ETH": ("ETHUSDTM", 1)}
TAUS = (1, 5, 10, 100, 1000, 6000)                                   # 格数(10 毫秒一格)
LAB = ("10ms", "50ms", "100ms", "1s", "10s", "60s")
rng = np.random.default_rng(20261016)
rows = []
for sym, (nat, j) in SYMS.items():
    for day in DAYS:
        g = np.load(os.path.join(ROOT, "data", "factors", "grid", "%s_%s.npz" % (nat, day)))
        n = len(g["ok"])
        ok = g["ok"] & (g["ap"] > g["bp"])
        mid = pd.Series(np.where(ok, (g["ap"] + g["bp"]) / 2.0, np.nan)).ffill().to_numpy()
        tx = np.load(os.path.join(ROOT, "data", "factors", "tox1", "%s.npz" % day))
        for sname, d in (("卖侧亮(预测涨)", 1.0), ("买侧亮(预测跌)", -1.0)):
            f = tx["tox_bnpush_ask" if d > 0 else "tox_bnpush_bid"][:, j].astype(float)
            for pq in (90, 95, 99):
                thr = np.nanpercentile(f, pq)
                cr = np.flatnonzero((f[1:] >= thr) & (f[:-1] < thr)) + 1
                ev, last = [], -10**9
                for r in cr:
                    if r - last >= 100 and 100 <= r < n - 6001 and ok[r]:
                        ev.append(r)
                        last = r
                ev = np.array(ev)
                for k, lab in zip(TAUS, LAB):
                    rows.append(dict(sym=sym, day=day, side=sname, pq=pq, tau=lab, n=len(ev), mo=float(np.mean(d * (mid[ev + k] - mid[ev]) / mid[ev] * 1e4))))
        # 对照:随机时刻、随机方向
        ev = rng.integers(100, n - 6001, 3000)
        ev = ev[ok[ev]]
        d = rng.choice([-1.0, 1.0], len(ev))
        for k, lab in zip(TAUS, LAB):
            rows.append(dict(sym=sym, day=day, side="对照(随机)", pq=0, tau=lab, n=len(ev), mo=float(np.mean(d * (mid[ev + k] - mid[ev]) / mid[ev] * 1e4))))
R = pd.DataFrame(rows)
out = os.path.join(ROOT, "data", "research7", "bnpush_signal_markout_20261016.csv")
R.to_csv(out, index=False, encoding="utf-8-sig")
for sym in SYMS:
    print("\n%s:tox_bnpush 亮起后中间价朝预测方向走了多少(bp;三天各自的值,用 / 隔开;事件数 = 三天合计)" % sym)
    print("  %-14s %4s %6s | %s" % ("信号", "门槛", "事件数", " | ".join("%-20s" % l for l in LAB)))
    for (side, pq), x in R[R["sym"] == sym].groupby(["side", "pq"], sort=False):
        cells = []
        for lab in LAB:
            v = x[x["tau"] == lab].sort_values("day")["mo"].to_numpy()
            cells.append("%-20s" % " / ".join("%+.2f" % a for a in v))
        nev = int(x[x["tau"] == LAB[0]]["n"].sum())
        print("  %-14s %4s %6d | %s" % (side, ("%d%%" % pq) if pq else "-", nev, " | ".join(cells)))
print("\n写入", out)
