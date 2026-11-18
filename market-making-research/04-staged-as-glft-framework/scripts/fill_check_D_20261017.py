#!/usr/bin/env python3
"""成交检查 D:现有信号能不能在可成交的价格上创造净收益——用 10-17 已经跑完的门槛扫描画"成交额 对 每笔净收益"的取舍。只读。

数据   估计组(15–17 时):门槛扫描 SC_*(本侧 tox_bnpush 门槛 × 失衡门槛)与"不按因子撤单"COLC;
       检验组(10–14 时):VT_t90_o0(选出的组合)、VT_t90_ooff、COLD / COLE(不撤)。
净收益 = 成交额 × (成交后 100 ms markout + 返佣 我方费率);markout 用逐毫秒买一卖一。只算"成交那一下",不含之后持仓。
用法   .venv/Scripts/python.exe scripts/research7/fill_check_D_20261017.py
"""
import glob, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = os.path.join(ROOT, "data", "research7", "l3_strategy")


def mids(hours):
    bb = np.concatenate([np.load(os.path.join(ROOT, "data", "research7", "market", "XBTUSDTM_20261014_%02d.npz" % h))["bbo"] for h in hours])
    bb = bb[np.argsort(bb[:, 0], kind="stable")]
    return bb[:, 0], (bb[:, 1] + bb[:, 2]) / 2.0 * 0.1


def stat(tags, hours):
    bt, mid = mids(hours)
    F = pd.concat([pd.read_csv(os.path.join(D, "%s_20261014_fills.csv" % t)) for t in tags])
    F = F[F["maker"] == 1]
    px = F["tick"].to_numpy() * 0.1
    sg = np.where(F["sd"] == 0, 1.0, -1.0)
    w = F["size"].to_numpy() * 0.001 * px
    k = np.searchsorted(bt, F["ts"].to_numpy(np.int64) + 100_000_000, side="right") - 1
    mo = sg * (mid[k] - px) / px * 1e4
    return len(F), w.sum() / len(hours), float(np.average(mo, weights=w)) + 0.7 if len(w) else np.nan, float(((mo + 0.7) * w).sum() / 1e4)


lines = []
P = lambda s="": (lines.append(s), print(s, flush=True))
P("D:成交额 对 每笔净收益(100 ms markout + 返佣 我方费率);只算成交那一下")
P("  %-18s %-12s %6s %12s %14s %10s" % ("方案", "时段", "成交", "每小时成交额$", "每笔净收益 bp", "合计 $"))
rows = []
for f in sorted(glob.glob(os.path.join(D, "SC_*_20261014.json"))) + [os.path.join(D, "COLC_20261014.json")]:
    t = os.path.basename(f)[:-len("_20261014.json")]
    n, nph, e, tot = stat([t], (15, 16, 17))
    rows.append((t, "估计 15–17", n, nph, e, tot))
for t, tags, hrs in (("VT_t90_o0", ("VT_t90_o0_A", "VT_t90_o0_B"), (10, 11, 12, 13, 14)), ("VT_t90_ooff", ("VT_t90_ooff_A", "VT_t90_ooff_B"), (10, 11, 12, 13, 14)),
                     ("不撤(COLD+E)", ("COLD", "COLE"), (10, 11, 12, 13, 14))):
    n, nph, e, tot = stat(list(tags), hrs)
    rows.append((t, "检验 10–14", n, nph, e, tot))
for r in sorted(rows, key=lambda r: (r[1], -r[3])):
    P("  %-18s %-12s %6d %12.0f %+14.2f %+10.1f" % r)
open(os.path.join(ROOT, "data", "research7", "fill_check", "fill_check_D.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
