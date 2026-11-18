#!/usr/bin/env python3
"""成交检查 A / B / C(用户 10-17 给的检查清单)。只读,线下。

成交   快速版 L3 回放、两侧贴最优价、不按因子撤单(标签 CK1 = 10–12 时,CK2 = 13–14 时,CK3 = 15–17 时;10-14)。
       每笔:成交时刻、方向、价格、张数、决定挂单的时刻 born、进簿时刻 rest、进簿时前面的张数 ahead0、成交时前面还剩的张数、这次吃单总张数。
行情   data/research7/market 的逐毫秒买一卖一与买一 / 卖一张数(L3 重建,交易所时间);KuCoin 逐笔成交(data/research7/l2)。
markout 挂单方向 × (成交后 τ 的中间价 − 成交价)/ 成交价 × 1e4(bp),τ = 1、10、100、1,000 毫秒,按成交额加权;"+返佣" = 我方费率 ms markout + 0.7。
A 报价过时:成交前 X 毫秒到成交前 1 毫秒中间价的变化(按挂单方向取号,负 = 价格已经朝我们的单压过来),X = 5、20、100;
       从决定挂单到成交前中间价的变化;成交前 1 毫秒 microprice 与我们挂价之差(按方向取号,负 = 公允价已在我们挂价之外);成交前盘口失衡(按方向)。
B 排队筛选:进簿时前面张数、成交时前面还剩张数、进簿后前面被撤 / 吃走的比例、订单年龄(进簿到成交)、这次吃单总张数(相对我们的单量)。
C 市场状态:成交前 100 毫秒 / 1,000 毫秒的已实现波动、1,000 毫秒的趋势(按挂单方向)、100 毫秒的主动买卖失衡(按挂单方向)、点差是否 1 跳。
       每个状态分组另报"在这个状态里的时间"(每 10 毫秒取样),给出每小时成交额与每 $1 万成交额的净收益(100 ms markout + 返佣)。
用法   .venv/Scripts/python.exe scripts/research7/fill_check_20261017.py
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research7", "fill_check")
os.makedirs(OUT, exist_ok=True)
HOURS = range(10, 18)
bb = np.concatenate([np.load(os.path.join(ROOT, "data", "research7", "market", "XBTUSDTM_20261014_%02d.npz" % h))["bbo"] for h in HOURS])
bb = bb[np.argsort(bb[:, 0], kind="stable")]
bt = bb[:, 0]
bid, ask, bsz, asz = bb[:, 1].astype(float), bb[:, 2].astype(float), bb[:, 3].astype(float), bb[:, 4].astype(float)
mid = (bid + ask) / 2.0 * 0.1
micro = np.where(bsz + asz > 0, (bid * asz + ask * bsz) / (bsz + asz), (bid + ask) / 2.0) * 0.1
obi = np.where(bsz + asz > 0, (bsz - asz) / (bsz + asz), 0.0)
spr = ask - bid


def at(arr, t):
    k = np.searchsorted(bt, np.asarray(t, np.int64), side="right") - 1
    return arr[np.clip(k, 0, len(arr) - 1)]


# KuCoin 逐笔:主动方向(+1 买 / −1 卖)与张数
L = np.load(os.path.join(ROOT, "data", "research7", "l2", "XBTUSDTM_20261014.npz"))
k = L["kind"] == 0
tt, tq, tsg = L["ts"][k].astype(np.int64), L["size"][k].astype(float), np.where(L["side"][k] == 1, 1.0, -1.0)
o = np.argsort(tt, kind="stable")
tt, tq, tsg = tt[o], tq[o], tsg[o]
cflow = np.concatenate([[0.0], np.cumsum(tq * tsg)])


def flow(t, win_ms):
    t = np.asarray(t, np.int64)
    a, b = np.searchsorted(tt, t - win_ms * 1_000_000, side="right"), np.searchsorted(tt, t, side="right")
    return cflow[b] - cflow[a]


# 10 毫秒网格:已实现波动、趋势(给"在这个状态里的时间"和成交时刻共用)
G0, G1 = int(bt[0]) // 10_000_000 * 10_000_000 + 2_000_000_000, int(bt[-1]) // 10_000_000 * 10_000_000
grid = np.arange(G0, G1, 10_000_000, dtype=np.int64)
gm = at(mid, grid)
r2 = np.concatenate([[0.0], (np.diff(gm) / gm[:-1] * 1e4) ** 2])
cr2 = np.cumsum(r2)


def rv(t, win_ms):
    i = np.clip((np.asarray(t, np.int64) - G0) // 10_000_000, 0, len(grid) - 1)
    w = win_ms // 10
    return np.sqrt(cr2[i] - cr2[np.clip(i - w, 0, None)])


F = pd.concat([pd.read_csv(os.path.join(ROOT, "data", "research7", "l3_strategy", "%s_20261014_fills.csv" % t)) for t in ("CK1", "CK2", "CK3")])
F = F[F["maker"] == 1].reset_index(drop=True)
ts = F["ts"].to_numpy(np.int64)
px = F["tick"].to_numpy() * 0.1
sg = np.where(F["sd"] == 0, 1.0, -1.0)
F["w"] = F["size"] * 0.001 * px
for tau in (1, 10, 100, 1000):
    F["mo%d" % tau] = sg * (at(mid, ts + tau * 1_000_000) - px) / px * 1e4
pre = ts - 1_000_000                                            # 成交前 1 毫秒(交易所时间戳只有毫秒精度)
for X in (5, 20, 100):
    F["pre%d" % X] = sg * (at(mid, pre) - at(mid, ts - X * 1_000_000)) / px * 1e4
F["since_born"] = sg * (at(mid, pre) - at(mid, F["born_ns"].to_numpy(np.int64))) / px * 1e4
F["micro_gap"] = sg * (at(micro, pre) - px) / px * 1e4
F["obi_dir"] = sg * at(obi, pre)
F["ahead_gone"] = np.where(F["ahead0"] > 0, 1 - F["ahead_fill"] / F["ahead0"].where(F["ahead0"] > 0), np.nan)
F["age_ms"] = F["wait_ms"]
F["sweep_rel"] = F["sweep_qty"] / F["size"]
F["rv100"], F["rv1000"] = rv(pre, 100), rv(pre, 1000)
F["trend1000"] = sg * (at(mid, pre) - at(mid, ts - 1000 * 1_000_000)) / px * 1e4
F["flow100"] = sg * flow(pre, 100)
F["spread1"] = (at(spr, pre) <= 1).astype(int)
F.to_csv(os.path.join(OUT, "fills_with_state.csv"), index=False)

lines = []
P = lambda s="": (lines.append(s), print(s, flush=True))


def wm(g, c):
    return float(np.average(g[c], weights=g["w"])) if len(g) else np.nan


def table(title, col, edges, labels, rate=None):
    P("\n" + title)
    P("  %-22s %6s %10s | %7s %7s %7s %7s | %8s %s" % ("分组", "笔数", "成交额$", "1ms", "10ms", "100ms", "1000ms", "+返佣", "" if rate is None else "| 时间占比 每小时成交额$ 每$1万净收益$"))
    x = F[col].to_numpy(float)
    b = np.searchsorted(edges, x, side="right")
    for i, lab in enumerate(labels):
        g = F[(b == i) & np.isfinite(x)]
        if not len(g):
            continue
        s = "  %-22s %6d %10.0f | %+7.2f %+7.2f %+7.2f %+7.2f | %+8.2f" % (lab, len(g), g["w"].sum(), wm(g, "mo1"), wm(g, "mo10"), wm(g, "mo100"), wm(g, "mo1000"), wm(g, "mo100") + 0.7)
        if rate is not None:
            share = rate[i]
            hrs = share * len(grid) * 0.01 / 3600
            s += " | %7.1f%% %12.0f %12.2f" % (100 * share, g["w"].sum() / hrs if hrs > 0 else np.nan, (wm(g, "mo100") + 0.7))
        P(s)


P("成交检查 A / B / C:10-14 的 10–17 时 UTC,BTC-USDT,快速版、两侧贴最优价、不按因子撤单;共 %d 笔挂单成交,成交额 $%.0f" % (len(F), F["w"].sum()))
P("markout 单位 bp,按成交额加权;'+返佣' = 我方费率 ms markout + 我方费率(每笔平均净收益,bp)")
P("全部:1ms %+.2f  10ms %+.2f  100ms %+.2f  1000ms %+.2f" % (wm(F, "mo1"), wm(F, "mo10"), wm(F, "mo100"), wm(F, "mo1000")))
P("\n===== A 报价是不是总在过时(负 = 价格已经朝我们的挂单压过来 / 公允价已在我们挂价之外)")
for X in (5, 20, 100):
    table("A-%d 成交前 %d 毫秒内中间价变化(bp)" % (X, X), "pre%d" % X, [-0.5, -0.1, -1e-9, 1e-9, 0.1], ["≤ −0.5", "−0.5 … −0.1", "−0.1 … 0", "= 0(没动)", "0 … +0.1", "> +0.1"])
table("A-决定挂单到成交前,中间价变化(bp)", "since_born", [-1, -0.3, -1e-9, 1e-9, 0.3], ["≤ −1", "−1 … −0.3", "−0.3 … 0", "= 0", "0 … +0.3", "> +0.3"])
table("A-成交前 microprice 与我们挂价之差(bp,负 = 公允价已在挂价之外)", "micro_gap", [-0.01, 0, 0.005, 0.01], ["< −0.01", "−0.01 … 0", "0 … 0.005", "0.005 … 0.01", "≥ 0.01"])
table("A-成交前盘口失衡(按挂单方向)", "obi_dir", [-0.6, -0.2, 0.2, 0.6], ["≤ −0.6", "−0.6 … −0.2", "−0.2 … 0.2", "0.2 … 0.6", "> 0.6"])
P("\n===== B 成交是不是被排队位置筛选过")
table("B-进簿时前面的张数", "ahead0", [0.5, 50, 200, 500], ["0", "1–50", "51–200", "201–500", "> 500"])
table("B-成交时前面还剩的张数", "ahead_fill", [0.5, 50, 200, 500], ["0", "1–50", "51–200", "201–500", "> 500"])
table("B-进簿后前面被撤 / 吃走的比例", "ahead_gone", [0.25, 0.5, 0.75, 0.999], ["< 25%", "25–50%", "50–75%", "75–<100%", "100%"])
table("B-订单年龄(进簿到成交,毫秒)", "age_ms", [10, 100, 1000, 10000], ["< 10", "10–100", "100–1000", "1000–10000", "≥ 10000"])
table("B-这次吃单总量 ÷ 我们的单量", "sweep_rel", [1.0001, 3, 10, 30], ["≤ 1(只够吃我们)", "1–3", "3–10", "10–30", "> 30"])
# C:状态分组 + 时间占比
P("\n===== C 是不是在错误的市场状态下挂单(时间占比 = 这一状态占全部时间的比例;每小时成交额 = 在这一状态里平均每小时成交)")
gpre = grid
for col, f, edges, labels, title in (
        ("rv100", lambda t: rv(t, 100), None, None, "C-成交前 100 毫秒已实现波动(bp;没动单列,其余按全时段四分位)"),
        ("rv1000", lambda t: rv(t, 1000), None, None, "C-成交前 1,000 毫秒已实现波动(bp;没动单列,其余按全时段四分位)")):
    gv = f(gpre)
    e = [1e-9] + list(np.quantile(gv[gv > 1e-9], [0.25, 0.5, 0.75]))   # 大部分时间窗口内中间价没动(= 0),单列一组,其余按四分位
    lab = ["= 0(没动)", "Q1(最平静)", "Q2", "Q3", "Q4(最剧烈)"]
    share = np.bincount(np.searchsorted(e, gv, side="right"), minlength=5) / len(gv)
    table(title + " 分界 %s" % ", ".join("%.3f" % x for x in e), col, e, lab, share)
gt = np.abs(at(mid, gpre) - at(mid, gpre - 1000 * 1_000_000)) / at(mid, gpre) * 1e4
e = [1e-9] + list(np.quantile(gt[gt > 1e-9], [0.25, 0.5, 0.75]))
F["trend_abs"] = np.abs(F["trend1000"])
share = np.bincount(np.searchsorted(e, gt, side="right"), minlength=5) / len(gt)
table("C-成交前 1,000 毫秒趋势强度 |中间价变化|(bp;没动单列,其余四分位) 分界 %s" % ", ".join("%.2f" % x for x in e), "trend_abs", e, ["= 0(没动)", "Q1", "Q2", "Q3", "Q4(单边)"], share)
table("C-成交前 1,000 毫秒趋势方向(按挂单方向,负 = 逆着我们的单走)", "trend1000", [-1, -0.3, 0.3, 1], ["≤ −1", "−1 … −0.3", "−0.3 … 0.3", "0.3 … 1", "> 1"])
table("C-成交前 100 毫秒主动买卖失衡(张,按挂单方向;负 = 主动方在打我们这一侧)", "flow100", [-300, -30, 30, 300], ["≤ −300", "−300 … −30", "−30 … 30", "30 … 300", "> 300"])
gs = (at(spr, gpre) <= 1).astype(int)
share = np.bincount(gs, minlength=2) / len(gs)
table("C-点差", "spread1", [0.5], ["点差 > 1 跳", "点差 = 1 跳"], share)
open(os.path.join(OUT, "fill_check_ABC.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
