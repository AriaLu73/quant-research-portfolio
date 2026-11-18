#!/usr/bin/env python3
"""方案 (a) 第二版:用更多小时、我们自己的成交估 9 格表(用户 10-16:"用更多小时估表,在没用过的小时上检验")。只读,线下。

成交   快速版(两侧一直贴最优价,只有排队上限 0.1 BTC,不按任何因子撤单)在 10-14 的 04–09 时、15–17 时的 L3 回放成交
       (标签 COLA = 04–06 时,COLB = 07–09 时,COLC = 15–17 时)。检验用 10、11、12 时,与这里不重叠。
状态   成交那一刻策略自己看到的值(回放时记录):自己的买一卖一失衡、tox_bnpush 卖侧值 / 买侧值。
       每一侧 9 格 = 失衡三分位 × 本侧 tox_bnpush 三分位;分位边界用 10-13 的 10 毫秒网格定(与上一版相同)。
e      e_side(格) = 0.7 + 这一侧这一格成交后 1,000 毫秒的 markout(按成交额加权;中间价用 mid24 的 10 毫秒网格)。
       格内少于 30 笔时用这一侧全部成交的平均。另报每格的 markout 按小时分开时同号的比例(稳定度)。
输出   屏幕 + data/research7/own_fill_table_v2_20261017.json;最后一行 ARGS 是给快速版的参数
用法   .venv/Scripts/python.exe scripts/research7/own_fill_table_v2_20261017.py
"""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research7"))
import factor_reeval_eval as E      # noqa: E402

TAGS = ("COLA", "COLB", "COLC")
NMIN = 30
g = np.load(os.path.join(E.GRID, "XBTUSDTM_20261013.npz"))
ok = g["ok"] & (g["ap"] > g["bp"])
bq, aq = g["bs"][:, 0].astype(float), g["as_"][:, 0].astype(float)
obi13 = np.where(ok & (bq + aq > 0), (bq - aq) / (bq + aq), np.nan)
tx = np.load(os.path.join(E.TOX1, "20261013.npz"))
fq = lambda a, q: np.nanquantile(a[np.isfinite(a)], q).tolist()
ed = dict(obi=fq(obi13, [1 / 3, 2 / 3]), bnA=fq(tx["tox_bnpush_ask"][:, 0].astype(float), [1 / 3, 2 / 3]),
          bnB=fq(tx["tox_bnpush_bid"][:, 0].astype(float), [1 / 3, 2 / 3]))
m = np.load(os.path.join(ROOT, "data", "research7", "mid24", "XBTUSDTM_20261014.npz"))
mid = pd.Series(np.where(m["ok"], (m["bp"] + m["ap"]) / 2.0 * float(m["tick"]), np.nan)).ffill().to_numpy()
t0 = int(m["t0"])
F = pd.concat([pd.read_csv(os.path.join(ROOT, "data", "research7", "l3_strategy", "%s_20261014_fills.csv" % t)) for t in TAGS])
F = F[(F["maker"] == 1) & F["obi"].notna() & F["bnA"].notna() & F["bnB"].notna()].reset_index(drop=True)
ts = F["ts"].to_numpy(np.int64)
k = np.clip((ts + 1_000_000_000 - t0) // 10_000_000, 0, len(mid) - 1)
px = F["tick"].to_numpy() * 0.1
sd = F["sd"].to_numpy()
mo = np.where(sd == 0, 1.0, -1.0) * (mid[k] - px) / px * 1e4
w = F["size"].to_numpy() * 0.001 * px
hr = (ts // 3_600_000_000_000) % 24
a = np.searchsorted(ed["obi"], F["obi"].to_numpy(), side="right")
own = np.where(sd == 0, F["bnB"].to_numpy(), F["bnA"].to_numpy())
b = np.where(sd == 0, np.searchsorted(ed["bnB"], own, side="right"), np.searchsorted(ed["bnA"], own, side="right"))
cellv = a * 3 + b
out = dict(edges=ed, horizon_ms=1000, hours=sorted(set(hr.tolist())), n=len(F))
print("我们自己的成交(%s,10-14 的 %s 时):%d 笔;成交后 1,000 毫秒 markout 与 e = 0.7 + markout(bp)" % ("+".join(TAGS), sorted(set(hr.tolist())), len(F)))
names = ["失衡低", "失衡中", "失衡高"]
for s, nm in ((0, "bid"), (1, "ask")):
    sel = sd == s
    tot = float(np.average(mo[sel], weights=w[sel]))
    e, n, stab = [], [], []
    for c in range(9):
        ss = sel & (cellv == c)
        n.append(int(ss.sum()))
        v = float(np.average(mo[ss], weights=w[ss])) if ss.sum() >= NMIN else tot
        e.append(0.7 + v)
        hs = [np.average(mo[ss & (hr == h)] + 0.7, weights=w[ss & (hr == h)]) for h in sorted(set(hr[ss].tolist())) if (ss & (hr == h)).sum() >= 5]
        stab.append("%d/%d 小时同号" % (sum(np.sign(x) == np.sign(e[-1]) for x in hs), len(hs)) if hs else "-")
    out["e_" + nm], out["n_" + nm] = e, n
    print("  %s单:全部 %d 笔,平均 markout %+.2f" % ("买" if s == 0 else "卖", int(sel.sum()), tot))
    for c in range(9):
        print("     %s × 本侧 tox_bnpush %s:%5d 笔  e %+.2f  %s%s" % (names[c // 3], ["低", "中", "高"][c % 3], n[c], e[c], stab[c],
                                                            "" if n[c] >= NMIN else "(笔数不足,用整侧平均)"))
json.dump(out, open(os.path.join(ROOT, "data", "research7", "own_fill_table_v2_20261017.json"), "w"), indent=1)
f = lambda v: ",".join("%.6g" % x for x in v)
print("ARGS fm_cells9=1 fm9_ed_obi=%s fm9_ed_bna=%s fm9_ed_bnb=%s fm9_e_bid=%s fm9_e_ask=%s" % (f(ed["obi"]), f(ed["bnA"]), f(ed["bnB"]), f(out["e_bid"]), f(out["e_ask"])))
