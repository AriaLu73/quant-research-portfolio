#!/usr/bin/env python3
"""VPIN 能不能拦住我们的毒单(用户 10-17:"还是拦不住，试一下VPIN")。只读,线下;先在我们自己的成交上量,有用再放进策略回放。

VPIN   Easley、López de Prado、O'Hara (2012) "Flow Toxicity and Liquidity in a High-Frequency World"(RFS 25(5)):
       按成交量切桶,每桶 V;VPIN = 最近 n 个桶里 |买方吃单量 − 卖方吃单量| 之和 ÷ (n × V)。
       原文用"批量分类"推断买卖方向;我们的逐笔数据直接带吃单方向,用真实方向(原文也说有方向时可直接用)。
       原文的 V = 日成交量 / 50、n = 50 是日内分钟级的设定;这里 V、n 不拍,扫描:
         V ∈ {0.5, 2, 10, 50} BTC,n ∈ {10, 50};数据源两种:KuCoin XBTUSDTM 逐笔、币安 BTCUSDT 永续逐笔。
       另做一个带方向的版本 sVPIN = 最近 n 桶的 (买 − 卖) 之和 ÷ (n × V),按我们挂单的方向取号(买单:卖压大为负)。
取值   成交前 10 毫秒那一刻已经走完的最后一个桶(撤单要提前量;只用当时以前的数据)。币安成交按撮合时间 + 2 毫秒。
成交   同 factor_on_fills_20261017.py:快速版、两侧贴最优价、只有排队上限、不按因子撤单的 L3 回放成交;
       估计组 04–09、15–17 时,检验组 10–14 时。
报告   ① 秩 IC(VPIN / sVPIN vs 成交后 10 / 100 / 1,000 ms markout),估计组 / 检验组;
       ② 增量:先用本侧 tox_bnpush 和失衡(现在的两个撤单因子)对 markout 做秩回归,再看 VPIN 和残差的秩相关;
       ③ 撤单用法:估计组定方向与门槛(去掉最不利 20%),检验组剩下成交的 100 ms markout 改善与去掉的成交额。
用法   .venv/Scripts/python.exe scripts/research7/vpin_on_fills_20261017.py
"""
import os, zipfile
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EST, TEST = ("COLA", "COLB", "COLC"), ("COLD", "COLE")
LEAD_NS = 10_000_000
VS, NS_ = (0.5, 2.0, 10.0, 50.0), (10, 50)


def trades_ku():
    L = np.load(os.path.join(ROOT, "data", "research7", "l2", "XBTUSDTM_20261014.npz"))
    k = L["kind"] == 0
    ts = L["ts"][k].astype(np.int64)
    q = L["size"][k].astype(float) * 0.001
    sgn = np.where(L["side"][k] == 1, 1.0, -1.0)              # side = 被打的一侧:1 = 卖盘被打 = 买方吃单
    o = np.argsort(ts, kind="stable")
    return ts[o], q[o], sgn[o]


def trades_bn():
    z = zipfile.ZipFile(os.path.join(ROOT, "data", "research5", "binance_hist", "BTCUSDT-aggTrades-2026-10-14.zip"))
    B = pd.read_csv(z.open(z.namelist()[0]))
    ts = B["transact_time"].to_numpy(np.int64) * 1_000_000 + 2_000_000
    sgn = np.where(B["is_buyer_maker"].astype(str).str.lower() == "true", -1.0, 1.0)
    return ts, B["quantity"].to_numpy(float), sgn


def buckets(ts, q, sgn, V):
    """切桶:每桶正好 V(跨桶的成交按量拆开)。返回每个桶走完的时刻、桶内 (买 − 卖)。"""
    cum = np.cumsum(q)
    cb = np.cumsum(q * sgn)
    edges = np.arange(V, cum[-1], V)
    i = np.searchsorted(cum, edges)                            # 第 i 笔成交把累计量推过桶边界
    t_end = ts[i]
    # 桶边界处的 (买 − 卖) 累计:按边界处那笔成交的方向线性拆分
    over = cum[i] - edges
    imb_at = cb[i] - over * sgn[i]
    imb = np.diff(np.concatenate([[0.0], imb_at]))
    return t_end, imb


def vpin_at(t_end, imb, V, n, t_query):
    a = np.abs(imb)
    ca, cs = np.concatenate([[0.0], np.cumsum(a)]), np.concatenate([[0.0], np.cumsum(imb)])
    j = np.searchsorted(t_end, t_query, side="right")          # t_query 之前走完的桶数
    ok = j >= n
    if len(t_end) < n:
        return np.full(len(t_query), np.nan), np.full(len(t_query), np.nan)
    jj = np.clip(j, n, len(t_end))
    v = np.where(ok, (ca[jj] - ca[jj - n]) / (n * V), np.nan)
    s = np.where(ok, (cs[jj] - cs[jj - n]) / (n * V), np.nan)
    return v, s


def load(tags):
    F = pd.concat([pd.read_csv(os.path.join(ROOT, "data", "research7", "l3_strategy", "%s_20261014_fills.csv" % t)) for t in tags])
    F = F[(F["maker"] == 1) & F["obi"].notna() & F["bnA"].notna()].reset_index(drop=True)
    buy = F["sd"].to_numpy() == 0
    F["dir_obi"] = np.where(buy, F["obi"], -F["obi"])
    F["own_tox"] = np.where(buy, F["bnB"], F["bnA"])
    m = np.load(os.path.join(ROOT, "data", "research7", "mid24", "XBTUSDTM_20261014.npz"))
    mid = pd.Series(np.where(m["ok"], (m["bp"] + m["ap"]) / 2.0 * float(m["tick"]), np.nan)).ffill().to_numpy()
    t0 = int(m["t0"])
    px = F["tick"].to_numpy() * 0.1
    ts = F["ts"].to_numpy(np.int64)
    for tau in (10, 100, 1000):
        k = np.clip((ts + tau * 1_000_000 - t0) // 10_000_000, 0, len(mid) - 1)
        F["mo%d" % tau] = np.where(buy, 1.0, -1.0) * (mid[k] - px) / px * 1e4
    F["w"] = F["size"] * 0.001 * px
    return F


def ric(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    k = np.isfinite(x) & np.isfinite(y)
    return float(np.corrcoef(pd.Series(x[k]).rank(), pd.Series(y[k]).rank())[0, 1]) if k.sum() > 30 else np.nan


def resid(F):
    """markout 的秩对 (本侧 tox_bnpush 的秩, 失衡的秩) 做线性回归后的残差。"""
    X = np.column_stack([np.ones(len(F)), F["own_tox"].rank(), F["dir_obi"].rank()])
    y = F["mo100"].rank().to_numpy()
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    return y - X @ b


E, T = load(EST), load(TEST)
rE, rT = resid(E), resid(T)
print("成交:估计组 %d 笔,检验组 %d 笔;VPIN 取成交前 10 毫秒已走完的桶" % (len(E), len(T)))
print("%-6s %5s %3s | %-28s | %-28s | %-15s | %s" % ("来源", "V(BTC)", "n", "VPIN 秩 IC 10/100/1000ms(估/验)", "sVPIN 秩 IC 10/100/1000ms(估/验)",
                                                   "增量 VPIN/sVPIN(估/验)", "撤单:去掉成交额 / 检验组 100ms 改善"))
for src, (ts, q, sg) in (("KuCoin", trades_ku()), ("币安", trades_bn())):
    for V in VS:
        t_end, imb = buckets(ts, q, sg, V)
        dur = np.median(np.diff(t_end)) / 1e6
        for n in NS_:
            res = {}
            for nm, F in (("E", E), ("T", T)):
                v, s = vpin_at(t_end, imb, V, n, F["ts"].to_numpy(np.int64) - LEAD_NS)
                F["vpin"], F["svpin"] = v, np.where(F["sd"] == 0, s, -s)
                res[nm] = F[["vpin", "svpin"]].copy()
            ic_v = " ".join("%+.2f/%+.2f" % (ric(res["E"]["vpin"], E["mo%d" % t]), ric(res["T"]["vpin"], T["mo%d" % t])) for t in (10, 100, 1000))
            ic_s = " ".join("%+.2f/%+.2f" % (ric(res["E"]["svpin"], E["mo%d" % t]), ric(res["T"]["svpin"], T["mo%d" % t])) for t in (10, 100, 1000))
            inc = "%+.2f/%+.2f %+.2f/%+.2f" % (ric(res["E"]["vpin"], rE), ric(res["T"]["vpin"], rT), ric(res["E"]["svpin"], rE), ric(res["T"]["svpin"], rT))
            # 撤单:用 VPIN 和 sVPIN 里估计组 IC 绝对值大的那个
            col = "vpin" if abs(ric(res["E"]["vpin"], E["mo100"])) >= abs(ric(res["E"]["svpin"], E["mo100"])) else "svpin"
            xe, xt = res["E"][col].to_numpy(), res["T"][col].to_numpy()
            hi_good = ric(xe, E["mo100"]) > 0
            thr = np.nanquantile(xe, 0.2 if hi_good else 0.8)
            keep = (xt > thr) if hi_good else (xt < thr)
            keep = keep | ~np.isfinite(xt)
            wT = T["w"].to_numpy()
            imp = np.average(T["mo100"][keep], weights=wT[keep]) - np.average(T["mo100"], weights=wT)
            print("%-6s %5.1f %3d | %-28s | %-28s | %-15s | %s:%4.1f%% / %+.2f bp(每桶约 %.0f ms)" % (
                src, V, n, ic_v, ic_s, inc, col, 100 * wT[~keep].sum() / wT.sum(), imp, dur))
