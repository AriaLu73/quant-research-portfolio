#!/usr/bin/env python3
"""因子在"我们被成交的那一刻"有没有用(用户 10-17:"高频策略17个小时还不够你用吗？" → 只用 10-14 的 17 个小时)。只读,线下。

成交   快速版 L3 回放里我们自己的挂单成交:两侧一直贴最优价,只有排队上限 0.1 BTC,不按任何因子撤单(各种状态下都有成交)。
       估计组 = 04–09 时、15–17 时(COLA、COLB、COLC);检验组 = 10–14 时(COLD、COLE)。分组前先定,不看检验组的结果改任何东西。
状态   成交那一刻策略自己看到的值(回放时记录):自己的买一卖一失衡 obi、tox_bnpush 卖侧值 bnA、买侧值 bnB。
       注意:这是成交那一刻的值,不是提前 2–15 毫秒(撤单要的提前量)的值,所以是"用于撤单"的上限。
因子(按挂单方向对齐,高 = 对这笔挂单有利的预测)
       dir_obi   = 买单 obi,卖单 −obi                        (盘口失衡站在我们这边)
       own_tox   = 买单 bnB,卖单 bnA                         (本侧要被扫,高 = 危险)
       opp_tox   = 买单 bnA,卖单 bnB                         (对面要被扫)
       bn_dir    = 买单 bnA − bnB,卖单 bnB − bnA             (V2.1 用的"两侧之差",按挂单方向取号)
markout 挂单方向 × (成交后 τ 的中间价 − 成交价)/ 成交价 × 1e4,τ = 10、50、100、500、1,000 毫秒(mid24 10 毫秒网格)。
报告   ① 各组的秩 IC(因子 vs markout);② 按估计组的五分位边界分组,每组平均 markout(按成交额加权);
       ③ 撤单用法:在估计组定方向和门槛(去掉最不利的 20%),检验组里剩下成交的 markout 改善多少 bp、去掉了几成成交额。
用法   .venv/Scripts/python.exe scripts/research7/factor_on_fills_20261017.py
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EST, TEST = ("COLA", "COLB", "COLC"), ("COLD", "COLE")
TAUS = (10, 50, 100, 500, 1000)
m = np.load(os.path.join(ROOT, "data", "research7", "mid24", "XBTUSDTM_20261014.npz"))
mid = pd.Series(np.where(m["ok"], (m["bp"] + m["ap"]) / 2.0 * float(m["tick"]), np.nan)).ffill().to_numpy()
t0 = int(m["t0"])


def load(tags):
    F = pd.concat([pd.read_csv(os.path.join(ROOT, "data", "research7", "l3_strategy", "%s_20261014_fills.csv" % t)) for t in tags])
    F = F[(F["maker"] == 1) & F["obi"].notna() & F["bnA"].notna()].reset_index(drop=True)
    buy = F["sd"].to_numpy() == 0
    F["dir_obi"] = np.where(buy, F["obi"], -F["obi"])
    F["own_tox"] = np.where(buy, F["bnB"], F["bnA"])
    F["opp_tox"] = np.where(buy, F["bnA"], F["bnB"])
    F["bn_dir"] = np.where(buy, F["bnA"] - F["bnB"], F["bnB"] - F["bnA"])
    px = F["tick"].to_numpy() * 0.1
    sg = np.where(buy, 1.0, -1.0)
    ts = F["ts"].to_numpy(np.int64)
    for tau in TAUS:
        k = np.clip((ts + tau * 1_000_000 - t0) // 10_000_000, 0, len(mid) - 1)
        F["mo%d" % tau] = sg * (mid[k] - px) / px * 1e4
    F["w"] = F["size"] * 0.001 * px
    F["hr"] = (ts // 3_600_000_000_000) % 24
    return F


def ric(x, y):
    return float(np.corrcoef(pd.Series(x).rank(), pd.Series(y).rank())[0, 1])


def wmean(g, c):
    return float(np.average(g[c], weights=g["w"])) if len(g) else np.nan


E, T = load(EST), load(TEST)
print("我们的挂单成交:估计组 %d 笔(%s 时),检验组 %d 笔(%s 时)" % (len(E), sorted(E["hr"].unique()), len(T), sorted(T["hr"].unique())))
print("全部成交的平均 markout(bp):估计组 " + "  ".join("%dms %+.2f" % (t, wmean(E, "mo%d" % t)) for t in TAUS))
print("                            检验组 " + "  ".join("%dms %+.2f" % (t, wmean(T, "mo%d" % t)) for t in TAUS))
FACT = (("dir_obi", "盘口失衡站在我们这边"), ("own_tox", "本侧要被扫"), ("opp_tox", "对面要被扫"), ("bn_dir", "币安两侧之差(V2.1 用法)"))
print("\n① 秩 IC(因子 vs 成交后 markout):估计组 / 检验组")
for f, nm in FACT:
    print("  %-8s %-22s " % (f, nm) + "  ".join("%dms %+.3f/%+.3f" % (t, ric(E[f], E["mo%d" % t]), ric(T[f], T["mo%d" % t])) for t in TAUS))
print("\n② 按估计组五分位分组的平均 markout(bp,100 ms / 1,000 ms;估计组 → 检验组)")
for f, nm in FACT:
    ed = np.quantile(E[f], [0.2, 0.4, 0.6, 0.8])
    qe, qt = np.searchsorted(ed, E[f], side="right"), np.searchsorted(ed, T[f], side="right")
    cells = []
    for q in range(5):
        a, b = E[qe == q], T[qt == q]
        cells.append("Q%d %+.2f/%+.2f→%+.2f/%+.2f(%d)" % (q + 1, wmean(a, "mo100"), wmean(a, "mo1000"), wmean(b, "mo100"), wmean(b, "mo1000"), len(b)))
    print("  %-8s " % f + "  ".join(cells))
print("\n③ 撤单用法:估计组定方向和门槛,去掉最不利的 20%;检验组剩下的成交 markout 改善(bp)与去掉的成交额比例")
for f, nm in FACT:
    good_high = ric(E[f], E["mo100"]) > 0
    thr = np.quantile(E[f], 0.2 if good_high else 0.8)
    keepT = (T[f] > thr) if good_high else (T[f] < thr)
    out = "  ".join("%dms %+.2f" % (t, wmean(T[keepT], "mo%d" % t) - wmean(T, "mo%d" % t)) for t in TAUS)
    print("  %-8s 方向 %s,门槛 %.3f:去掉 %4.1f%% 成交额 | %s" % (f, "高好" if good_high else "高坏", thr, 100 * T.loc[~keepT, "w"].sum() / T["w"].sum(), out))
