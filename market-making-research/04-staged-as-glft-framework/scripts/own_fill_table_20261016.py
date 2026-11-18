#!/usr/bin/env python3
"""方案 (a):逆向跳 J 改用我们自己的成交来估(用户 10-16:"两个一起试跑对比")。只读,线下。

成交   快速版在 10-14 的 15、16、17 时的 L3 回放成交(标签 COL:两侧一直贴最优价,只有排队上限 0.1 BTC,不按任何因子撤单,
       所以各种状态下都有成交)。这三个小时和检验用的 13、14 时不重叠。
状态   每一侧 9 格:自己的买一卖一失衡三分位 × 本侧 tox_bnpush 三分位(买单看买侧值,卖单看卖侧值);分位边界用 10-13 定。
       取成交之前最后一个 10 毫秒网格的值。
e      e_side(格) = 0.7 + 我们这一侧在这一格的成交,成交后 1,000 毫秒的 markout(按成交额加权;1,000 毫秒 = 10-13 上因子 IC 最高的时长)。
       格内少于 15 笔时用这一侧全部成交的平均。
输出   屏幕 + data/research7/own_fill_table_20261016.json(给快速版 fm_cells9 用的参数)
用法   .venv/Scripts/python.exe scripts/research7/own_fill_table_20261016.py
"""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research7"))
import factor_reeval_eval as E      # noqa: E402

H = 100                              # 1,000 毫秒 = 100 个 10 毫秒网格


def load(day):
    g = np.load(os.path.join(E.GRID, "XBTUSDTM_%s.npz" % day))
    ok = g["ok"] & (g["ap"] > g["bp"])
    mid = pd.Series(np.where(ok, (g["ap"] + g["bp"]) / 2.0 * float(g["tick"]), np.nan)).ffill().to_numpy()
    bq, aq = g["bs"][:, 0].astype(float), g["as_"][:, 0].astype(float)
    tx = np.load(os.path.join(E.TOX1, "%s.npz" % day))
    return dict(t0=int(g["t0"]), n=len(ok), ok=ok, mid=mid, obi=np.where(bq + aq > 0, (bq - aq) / (bq + aq), np.nan),
                bnA=tx["tox_bnpush_ask"][:, 0].astype(float), bnB=tx["tox_bnpush_bid"][:, 0].astype(float))


tr = load("20261013")
m = tr["ok"] & np.isfinite(tr["obi"])
ed = dict(obi=np.nanquantile(tr["obi"][m], [1 / 3, 2 / 3]).tolist(),
          bnA=np.nanquantile(tr["bnA"][np.isfinite(tr["bnA"])], [1 / 3, 2 / 3]).tolist(),
          bnB=np.nanquantile(tr["bnB"][np.isfinite(tr["bnB"])], [1 / 3, 2 / 3]).tolist())
te = load("20261014")
F = pd.read_csv(os.path.join(ROOT, "data", "research7", "l3_strategy", "COL_20261014_fills.csv"))
F = F[F["maker"] == 1].reset_index(drop=True)
r = ((F["ts"].to_numpy(np.int64) - te["t0"] - 1) // E.STEP).astype(np.int64)
keep = (r >= 0) & (r < te["n"] - H - 2)
F, r = F[keep].reset_index(drop=True), r[keep]
px = F["tick"].to_numpy() * 0.1
sd = F["sd"].to_numpy()
sg = np.where(sd == 0, 1.0, -1.0)
w = F["size"].to_numpy() * 0.001 * px
mo = sg * (te["mid"][r + 1 + H] - px) / px * 1e4
a = np.searchsorted(ed["obi"], te["obi"][r], side="right")
own_bn = np.where(sd == 0, te["bnB"][r], te["bnA"][r])
b = np.where(sd == 0, np.searchsorted(ed["bnB"], own_bn, side="right"), np.searchsorted(ed["bnA"], own_bn, side="right"))
cellv = a * 3 + b
out = dict(edges=ed, horizon_ms=1000)
print("我们自己的成交(COL,10-14 15–17 时):%d 笔;成交后 1,000 毫秒 markout(bp)与 e = 0.7 + markout,按格:" % len(F))
names = ["失衡低", "失衡中", "失衡高"]
for s, nm in ((0, "bid"), (1, "ask")):
    sel = sd == s
    tot = float(np.average(mo[sel], weights=w[sel]))
    e, n = [], []
    for c in range(9):
        ss = sel & (cellv == c)
        n.append(int(ss.sum()))
        e.append(0.7 + (float(np.average(mo[ss], weights=w[ss])) if ss.sum() >= 15 else tot))
    out["e_" + nm], out["n_" + nm] = e, n
    print("  %s单:全部 %d 笔,平均 markout %+.2f" % ("买" if s == 0 else "卖", int(sel.sum()), tot))
    for c in range(9):
        print("     %s × 本侧 tox_bnpush %s:%4d 笔  e %+.2f" % (names[c // 3], ["低", "中", "高"][c % 3], n[c], e[c]))
json.dump(out, open(os.path.join(ROOT, "data", "research7", "own_fill_table_20261016.json"), "w"), indent=1)
f = lambda v: ",".join("%.6g" % x for x in v)
print("ARGS fm_cells9=1 fm9_ed_obi=%s fm9_ed_bna=%s fm9_ed_bnb=%s fm9_e_bid=%s fm9_e_ask=%s" % (f(ed["obi"]), f(ed["bnA"]), f(ed["bnB"]), f(out["e_bid"]), f(out["e_ask"])))
