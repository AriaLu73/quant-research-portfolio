#!/usr/bin/env python3
"""research7 宽价差合约:8–9 月回放(ltk_live_replay.py)的盈亏归因。只读已有的成交记录,不新跑回放。

用途      回答"我们的设计里是哪一步在亏钱":把每笔成交拆成 价差 + markout + 返佣,再按 正常单 / 离场单、开仓 / 平仓、合约 分组;
          再把成交配成一开一平的来回(先进先出),看来回的盈亏、持有时间、由哪种单平掉。
所属阶段  阶段 8 探针的补充检验;失败分析(用户 2026-10-03:失败报告写"我们的设计哪步亏钱、下一版改什么")。
恒等式    每笔净值(到 h 秒)= 价差 + markout(h)+ 返佣,其中
            价差      = ε·(m0 − P)/P            m0 = 成交前最近一个整秒采样的别人中间价
            markout(h)= ε·(m_h − m0)/P          m_h = 成交后 h 秒的中间价
            ε = +1 买入,−1 卖出;全部乘 1e4 以 bp 计,按成交额加权
          当天盈亏 = Σ 每笔净值(60 秒)× 成交额 + 60 秒之后的持仓盈亏(余项)。
来回      同一合约同一天内先进先出配对;来回盈亏 = (卖价 − 买价)× 数量 + 两边返佣;持有时间 = 平仓成交时间 − 开仓成交时间。
用法      .venv/Scripts/python.exe scripts/research7/ltk_live_attrib.py [vol|fix]
"""
import os
import sys

import numpy as np

import ltk_live_replay as R

REBATE_BP = OUR_FEE
HS = (1, 10, 60, 300)


def load(sym, day, name):
    f = os.path.join(R.OUT, "%s_%s_%s.npz" % (sym, day, name))
    if not os.path.exists(f):
        return None
    z = np.load(f)
    fl, m, p = z["fills"], z["mids"], z["pnl"]
    if not len(fl) or not len(m):
        return None
    ts, eps, px, q, pos, ex = fl[:, 0], fl[:, 1], fl[:, 2], fl[:, 3], fl[:, 4], fl[:, 5]
    sec = ts // 10**9
    i0 = np.clip(np.searchsorted(m[:, 0], sec, side="left") - 1, 0, len(m) - 1)       # 成交所在秒之前的最近采样
    m0 = m[i0, 1]
    d = dict(usd=px * q, half=eps * (m0 - px) / px * 1e4, exit=ex > 0.5, open=np.abs(pos) > np.abs(pos - eps * q) + 1e-12,
             pnl=float(p[-1, 1]), ts=ts, eps=eps, px=px, q=q)
    for h in HS:
        ih = np.clip(np.searchsorted(m[:, 0], sec + h, side="left"), 0, len(m) - 1)
        d["mk%d" % h] = eps * (m[ih, 1] - m0) / px * 1e4
    # 来回:先进先出
    lots, trips = [], []                                                              # lots: [方向, 价, 剩余量, 时间]
    for k in range(len(ts)):
        left = q[k]
        while left > 1e-12 and lots and lots[0][0] != eps[k]:
            lot = lots[0]
            x = min(left, lot[2])
            gross = (px[k] - lot[1]) * x * lot[0]                                     # 多头:卖价 − 买价;空头相反
            reb = REBATE_BP / 1e4 * (px[k] + lot[1]) * x
            trips.append((gross + reb, (ts[k] - lot[3]) / 1e9, bool(ex[k] > 0.5), (px[k] + lot[1]) / 2 * x))
            lot[2] -= x
            left -= x
            if lot[2] <= 1e-12:
                lots.pop(0)
        if left > 1e-12:
            lots.append([eps[k], px[k], left, ts[k]])
    d["trips"] = trips
    return d


def wavg(x, w):
    return float((x * w).sum() / w.sum()) if w.sum() > 0 else float("nan")


def main(name):
    lines = []

    def P(s=""):
        lines.append(s)
        print(s, flush=True)

    D = {}
    for sym, day in R.JOBS:
        o = load(sym, day, name)
        if o is not None:
            D.setdefault(sym, []).append(o)
    P("盈亏归因 —— 方案 %s;8–9 月回放的全部成交;bp 均按成交额加权" % name)
    P()
    P("== 1 每笔成交:价差 + markout + 返佣(bp);余项 = 当天盈亏 − 60 秒口径合计 = 60 秒之后的持仓盈亏")
    P("%-8s %7s %10s | %6s %6s %6s %6s %6s | %7s %7s | %8s %8s %8s" % ("合约", "成交", "成交额$", "价差", "mk1", "mk10", "mk60", "mk300", "净60", "净300", "盈亏$", "60秒口径$", "余项$"))
    for sym in R.SYMS:
        if sym not in D:
            continue
        c = {k: np.concatenate([o[k] for o in D[sym]]) for k in ("usd", "half", "mk1", "mk10", "mk60", "mk300")}
        w = c["usd"]
        n60 = wavg(c["half"] + c["mk60"], w) + REBATE_BP
        n300 = wavg(c["half"] + c["mk300"], w) + REBATE_BP
        pnl = sum(o["pnl"] for o in D[sym])
        P("%-8s %7d %10.0f | %+6.2f %+6.2f %+6.2f %+6.2f %+6.2f | %+7.2f %+7.2f | %+8.2f %+8.2f %+8.2f" % (
            sym[:-5], len(w), w.sum(), wavg(c["half"], w), wavg(c["mk1"], w), wavg(c["mk10"], w), wavg(c["mk60"], w), wavg(c["mk300"], w), n60, n300,
            pnl, n60 * w.sum() / 1e4, pnl - n60 * w.sum() / 1e4))
    P()
    P("== 2 按单子类型:正常单(过了公允价规则)对 离场单(持仓超时 / 亏损线后,不看公允价)—— 成交额占比 | 价差 | mk60 | 净60(bp)| 净值美元")
    for sym in R.SYMS:
        if sym not in D:
            continue
        c = {k: np.concatenate([o[k] for o in D[sym]]) for k in ("usd", "half", "mk60", "exit", "open")}
        row = []
        for lab, m in (("正常-开仓", ~c["exit"] & c["open"]), ("正常-平仓", ~c["exit"] & ~c["open"]), ("离场单", c["exit"])):
            w = c["usd"][m]
            if w.sum() <= 0:
                row.append("%s  —" % lab)
                continue
            n = wavg(c["half"][m] + c["mk60"][m], w) + REBATE_BP
            row.append("%s %3.0f%% %+6.2f %+6.2f %+6.2f $%+7.2f" % (lab, 100 * w.sum() / c["usd"].sum(), wavg(c["half"][m], w), wavg(c["mk60"][m], w), n, n * w.sum() / 1e4))
        P("%-8s %s" % (sym[:-5], " | ".join(row)))
    P()
    P("== 3 来回(一开一平,先进先出):由正常单平掉的 对 由离场单平掉的 —— 个数 | 盈亏美元 | 每个来回 bp | 持有时间中位数(秒)| 盈利的占比")
    for sym in R.SYMS:
        if sym not in D:
            continue
        t = [x for o in D[sym] for x in o["trips"]]
        if not t:
            continue
        a = np.asarray([(x[0], x[1], x[2], x[3]) for x in t], float)
        row = []
        for lab, m in (("正常平", a[:, 2] < 0.5), ("离场平", a[:, 2] > 0.5)):
            if not m.any():
                row.append("%s  —" % lab)
                continue
            row.append("%s %5d $%+8.2f %+6.2f bp %6.0f 秒 %3.0f%%" % (lab, int(m.sum()), a[m, 0].sum(), a[m, 0].sum() / a[m, 3].sum() * 1e4, float(np.median(a[m, 1])), 100 * float((a[m, 0] > 0).mean())))
        hold = a[:, 1]
        P("%-8s %s | 持有时间分位 25/50/75/95:%.0f / %.0f / %.0f / %.0f 秒" % (sym[:-5], " | ".join(row), *np.percentile(hold, [25, 50, 75, 95])))
    P()
    P("== 4 来回盈亏按持有时间分组(全部合约合并)—— 个数 | 盈亏美元 | 每个来回 bp")
    a = np.asarray([(x[0], x[1], x[2], x[3]) for s in D for o in D[s] for x in o["trips"]], float)
    for lo, hi in ((0, 10), (10, 60), (60, 300), (300, 900), (900, 3600), (3600, 1e9)):
        m = (a[:, 1] >= lo) & (a[:, 1] < hi)
        if m.any():
            P("   %5.0f–%-6s 秒:%6d 个  $%+8.2f  %+6.2f bp   其中离场单平掉 %3.0f%%" % (lo, "%.0f" % hi if hi < 1e9 else "以上", int(m.sum()), a[m, 0].sum(), a[m, 0].sum() / a[m, 3].sum() * 1e4, 100 * float(a[m, 2].mean())))
    P("   合计 %d 个来回,$%+.2f;当天未平的仓位按末尾中间价计,不在来回里" % (len(a), a[:, 0].sum()))
    open(os.path.join(R.OUT, "live_attrib_%s.txt" % name), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "vol")
