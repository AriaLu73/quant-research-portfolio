#!/usr/bin/env python3
"""进场成交之后价格怎么走(用户 10-17:"先不看出场看一下markout到底怎么样再思考如何出去")。只读,线下,不跑回放。

成交   L3 回放里我们自己的挂单成交,按成交前后的仓位分成"进场"(空仓开仓或加仓,|仓位| 变大)和"减仓"(|仓位| 变小)。
       版本:毒性 90% + 失衡 ≤ 0、不加库存管理(SC_t90_o0 = 15–17 时;VT_t90_o0_A / _B = 10–12 / 13–14 时);
       对照:两侧一直贴最优价、不按因子撤单(COLC = 15–17 时;COLD / COLE = 10–12 / 13–14 时)。
中间价 data/research7/market 的逐毫秒买一卖一(L3 重建,交易所时间)。
markout = 挂单方向 × (成交后 τ 的中间价 − 成交价)/ 成交价 × 1e4(bp),不含返佣 我方费率。按笔报平均、中位数、为正的比例;平均另报按成交额加权。
        τ = 1、2、5、10、20、50、100、200、500、1,000 毫秒;2、5 秒只用来看逆向走势会不会回来。
用法   .venv/Scripts/python.exe scripts/research7/entry_markout_20261017.py
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TAUS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000)
bb = np.concatenate([np.load(os.path.join(ROOT, "data", "research7", "market", "XBTUSDTM_20261014_%02d.npz" % h))["bbo"] for h in range(10, 18)])
bb = bb[np.argsort(bb[:, 0], kind="stable")]
bt, mid = bb[:, 0], (bb[:, 1] + bb[:, 2]) / 2.0 * 0.1


def load(tags):
    out = []
    for t in tags:
        F = pd.read_csv(os.path.join(ROOT, "data", "research7", "l3_strategy", "%s_20261014_fills.csv" % t)).sort_values("ts")
        F = F[F["maker"] == 1].copy()
        d = np.where(F["sd"] == 0, 1.0, -1.0) * F["size"].to_numpy() * 0.001
        q1 = np.cumsum(d)
        q0 = q1 - d
        F["kind"] = np.where(np.abs(q1) > np.abs(q0) + 1e-12, "进场", "减仓")
        out.append(F)
    F = pd.concat(out)
    px = F["tick"].to_numpy() * 0.1
    sg = np.where(F["sd"] == 0, 1.0, -1.0)
    ts = F["ts"].to_numpy(np.int64)
    for tau in TAUS:
        k = np.searchsorted(bt, ts + tau * 1_000_000, side="right") - 1
        F["mo%d" % tau] = sg * (mid[k] - px) / px * 1e4
    F["w"] = F["size"] * 0.001 * px
    return F


lines = []
P = lambda s="": (lines.append(s), print(s, flush=True))
P("10-14 的 10–17 时 UTC,BTC-USDT;markout 单位 bp,不含返佣 我方费率;平均 / 中位数 / 为正的比例(%);'加权' = 按成交额加权的平均")
for name, tags in (("毒性 90% + 失衡 ≤ 0(不加库存管理)", ("SC_t90_o0", "VT_t90_o0_A", "VT_t90_o0_B")),
                   ("对照:不按因子撤单", ("COLC", "COLD", "COLE"))):
    F = load(tags)
    P("\n== %s:共 %d 笔(进场 %d,减仓 %d)" % (name, len(F), (F["kind"] == "进场").sum(), (F["kind"] == "减仓").sum()))
    P("  %-6s %6s | " % ("类别", "τ") + " ".join("%8s" % ("%dms" % t if t < 1000 else "%gs" % (t / 1000)) for t in TAUS))
    for kind in ("进场", "减仓"):
        G = F[F["kind"] == kind]
        if not len(G):
            continue
        P("  %-6s %6s | " % (kind, "平均") + " ".join("%+8.2f" % G["mo%d" % t].mean() for t in TAUS))
        P("  %-6s %6s | " % ("", "加权") + " ".join("%+8.2f" % np.average(G["mo%d" % t], weights=G["w"]) for t in TAUS))
        P("  %-6s %6s | " % ("", "中位数") + " ".join("%+8.2f" % G["mo%d" % t].median() for t in TAUS))
        P("  %-6s %6s | " % ("", "为正%") + " ".join("%8.0f" % (100 * (G["mo%d" % t] > 0).mean()) for t in TAUS))
        P("  %-6s %6s | " % ("", "为零%") + " ".join("%8.0f" % (100 * (G["mo%d" % t].abs() < 1e-9).mean()) for t in TAUS))
open(os.path.join(ROOT, "data", "research7", "entry_markout_20261017.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
