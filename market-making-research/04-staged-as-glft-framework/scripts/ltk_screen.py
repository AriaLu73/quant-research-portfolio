#!/usr/bin/env python3
"""research7 大 tick 品种初筛:贴最优价的假想报价,在队首与排到队尾两个口径下每笔净值是多少、一天能成交多少。离线,不含策略回放。

起因      用户 2026-10-08:BTC / ETH 上抢不过机构,改找大 tick 品种。阶段 4–6 的结论是 BTC 最优价处的盈亏由排队位置决定、
          而一个 tick 只有 0.012 bp;大 tick 品种贴盘口成交先赚半个 tick。本脚本用与阶段 4 相同的联合估计口径在别的品种上量一遍。
所属阶段  阶段 4 方法在其它品种上的应用(研究六"跨品种"的第一步);不改变 BTC 线任何已有结论。
对应公式  不改报价公式;回答"在哪个品种上最优价处的每笔净值为正"。
样本      每 5 秒在买卖两侧各放一张固定在同侧最优价的假想报价,存活 LIFE_S 秒不撤(与阶段 4 相同的做法;存活期另列 60 秒,因为这些品种成交稀)。
成交口径  队首(上界):对侧吃单成交价到达或穿过即成交。排到队尾(下界):我方之后该价位累计被吃的量 ≥ 放置时的同侧最优价挂单量,或该档被扫穿。
          不按盘口成交的打印已在 L2 仿真器里剔除。真实位置在两者之间,要用逐笔委托裁决(下一步)。
变量      eps = ε;P 报价价格;m0 成交前中间价;e_h = ε·(m_h − P) / m0 × 1e4(bp);每笔净值 = e_h + 返佣;
          half = ε·(m0 − P)(bp):成交那一刻相对中间价的优势(= 半个价差,大 tick 品种的收入来源);a_h = −ε·(m_h − m0):不利变动。
返佣      TradFi 合约(金属、大宗、股票)挂单 我方费率,加密 USDT 合约 我方费率:KuCoin Market Maker Program Ver. April 2026,我方费率档(项目记录 memory kucoin-mm-offer)。
用法      .venv/Scripts/python.exe scripts/research7/ltk_screen.py build <SYM> <YYYYMMDD>
          .venv/Scripts/python.exe scripts/research7/ltk_screen.py report <SYM> [<SYM> ...]
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calib as C
import l2_market

ROOT = C.ROOT
MKT = os.path.join(ROOT, "data", "research7", "market_l2")
OUT = os.path.join(ROOT, "data", "research7", "ltk")
EVERY_S = 5                        # 每 5 秒放一组:与阶段 4 相同
LIVES = (10, 60)                   # 存活期(秒):10 秒同阶段 4;60 秒为成交稀疏的品种另列(ASSUMPTION)
HS = (10, 60, 300)                 # 成交后的时间窗(秒):这些品种更慢,加 5 分钟(ASSUMPTION)
GAP_S = 30.0                       # 盘口超过 30 秒不变视为空档(这些品种更新慢,不能沿用 BTC 的 5 秒;ASSUMPTION)
ORDER_USD = 2000.0                 # 折算每天美元时假设的每单名义金额(ASSUMPTION:小于多数品种最优价处的挂单量,见报告里的"最优价挂单量中位")
REBATE = {"default": 0.7, "tradfi": 0.8}
TRADFI = ("XAG", "BZ", "NATGAS", "CL", "XAUT", "PAXG", "XPT", "COPPER", "NVDA", "TSLA", "AMD", "MSTR", "SPY", "QQQ")
COLS = ("hour", "side", "life", "spr", "qbest_usd", "fillU", "fillQ", "through", "half", "e10", "e60", "e300", "a10", "a60", "a300", "imb_s")


def spec(sym):
    j = json.load(open(os.path.join(ROOT, "data", "research5", "kucoin_contracts_20261002.json"), encoding="utf8"))
    for c in (j["data"] if isinstance(j, dict) else j):
        if c["symbol"] == sym:
            return float(c["tickSize"]), float(c["multiplier"])
    raise KeyError(sym)


def rebate(sym):
    return REBATE["tradfi"] if sym.startswith(TRADFI) else REBATE["default"]


def build(sym, day):
    f = os.path.join(MKT, f"{sym}_{day}.npz")
    if not os.path.exists(f):
        l2_market.build(day, sym)                               # 从 L2 事件重建买一卖一变化与吃单明细
    z = np.load(f)
    b, sw = z["bbo"], z["sw"]
    tick, mult = spec(sym)
    if len(b) < 100:
        print(f"ltk {sym} {day}: 盘口数据太少,跳过  LTK_BUILD_DONE", flush=True)
        return
    t, bb, ba, qb, qa = b[:, 0], b[:, 1], b[:, 2], b[:, 3].astype(float), b[:, 4].astype(float)
    mid2 = bb + ba
    per_side = [(sw[sw[:, 1] == s][:, 0], sw[sw[:, 1] == s][:, 2].astype(float), sw[sw[:, 1] == s][:, 4]) for s in (0, 1)]
    rows = []
    NS = 10**9
    t_last = t[-1] - (max(LIVES) + max(HS) + 1) * NS
    for t0 in range(int(t[0] // NS + 60) * NS, int(t_last), EVERY_S * NS):
        i0 = int(np.searchsorted(t, t0, side="right")) - 1        # 放置时刻之前最后一次盘口变化(只用过去)
        if i0 < 0 or t0 - t[i0] > GAP_S * NS or bb[i0] >= ba[i0]:
            continue
        m_ref = mid2[i0] / 2.0
        spr = int(ba[i0] - bb[i0])
        imb = (qb[i0] - qa[i0]) / max(qb[i0] + qa[i0], 1.0)
        for s in (0, 1):
            ts_s, q_s, last_s = per_side[s]
            eps = 1 if s == 0 else -1
            p = bb[i0] if s == 0 else ba[i0]
            q_best = qb[i0] if s == 0 else qa[i0]
            for life in LIVES:
                lo, hi = np.searchsorted(ts_s, (t0, t0 + life * NS), side="right")
                fU = fQ = thr = 0
                jf, cum = -1, 0.0
                for j in range(lo, hi):
                    if not ((last_s[j] <= p) if s == 0 else (last_s[j] >= p)):
                        continue
                    through = (last_s[j] < p) if s == 0 else (last_s[j] > p)
                    if jf < 0:
                        jf, fU, thr = j, 1, int(through)
                    cum += q_s[j]
                    if through or cum >= q_best:
                        fQ = 1
                        break
                e = [np.nan] * 3
                a = [np.nan] * 3
                half = np.nan
                if jf >= 0:
                    tf = int(ts_s[jf])
                    it = int(np.searchsorted(t, tf, side="left")) - 1                 # 成交前的盘口
                    if it >= 0 and tf - t[it] <= GAP_S * NS:
                        m0 = mid2[it] / 2.0
                        half = eps * (m0 - p) / m0 * 1e4
                        for k, h in enumerate(HS):
                            ih = int(np.searchsorted(t, tf + h * NS, side="right")) - 1
                            if tf + h * NS - t[ih] <= max(GAP_S, h) * NS:
                                mh = mid2[ih] / 2.0
                                e[k], a[k] = eps * (mh - p) / m0 * 1e4, -eps * (mh - m0) / m0 * 1e4
                rows.append((t0 // (3600 * NS), s, life, spr, q_best * mult * m_ref * tick, fU, fQ, thr, half, *e, *a, eps * imb))
    A = np.asarray(rows, np.float64)
    os.makedirs(OUT, exist_ok=True)
    # 当天的概况:价差分布、成交额
    dur = (t[-1] - t[0]) / NS
    w = np.diff(t, append=t[-1]).astype(float)
    sp = (ba - bb)
    meta = dict(tick_bp=float(tick / (np.mean(mid2) / 2.0 * tick) * 1e4), spr1=float(w[sp == 1].sum() / w.sum()), spr_med=float(np.median(sp)),
                usd=float(np.sum(sw[:, 2] * mult * sw[:, 3] * tick)), hours=dur / 3600.0)
    np.savez_compressed(os.path.join(OUT, f"{sym}_{day}.npz"), rows=A.astype(np.float32), **meta)
    print(f"ltk {sym} {day}: 假想报价 {len(A):,};1 tick = {meta['tick_bp']:.2f} bp;价差 = 1 tick 的时间占比 {meta['spr1']:.0%};成交额 ${meta['usd'] / 1e6:.2f}M  LTK_BUILD_DONE", flush=True)


def block(x, hour):
    m = np.isfinite(x)
    if m.sum() < 20:
        return float("nan"), float("nan"), int(m.sum())
    bl = np.array([x[m][hour[m] == h].mean() for h in np.unique(hour[m])])
    mu, t, _ = C.nw_t(bl)
    return float(np.mean(x[m])), t, int(m.sum())


def report(syms):
    L = []
    P = lambda s="": (L.append(s), print(s, flush=True))
    P("大 tick 品种初筛:贴同侧最优价的假想报价(每 5 秒两侧各一张,固定价格不撤),队首(上界)与排到队尾(下界)两个口径")
    P(f"每笔净值 = ε·(m_h − P) + 返佣;每天美元按每单 ${ORDER_USD:,.0f}、每侧同一时刻只有一张折算。训练 08-26…09-07,验证 09-10…09-24")
    for sym in syms:
        rb = rebate(sym)
        for seg, days in (("训练", C.TRAIN_DAYS), ("验证", C.VALID_DAYS)):
            Z = [np.load(os.path.join(OUT, f"{sym}_{d}.npz")) for d in days if os.path.exists(os.path.join(OUT, f"{sym}_{d}.npz"))]
            if not Z:
                continue
            A = np.vstack([z["rows"].astype(np.float64) for z in Z])
            D = {c: A[:, i] for i, c in enumerate(COLS)}
            nd = len(Z)
            P(f"\n== {sym}  {seg}({nd} 天):1 tick = {np.mean([z['tick_bp'] for z in Z]):.2f} bp;价差 = 1 tick 的时间占比 {np.mean([z['spr1'] for z in Z]):.0%}(中位 {np.median([z['spr_med'] for z in Z]):.0f} tick);"
              f"成交额 ${np.mean([z['usd'] for z in Z]) / 1e6:.2f}M/天;最优价挂单量中位 ${np.median(D['qbest_usd']):,.0f};返佣 {rb} bp")
            for life in LIVES:
                m = D["life"] == life
                nq = m.sum()
                for lab, key in (("队首", "fillU"), ("排到队尾", "fillQ")):
                    f = m & (D[key] == 1)
                    out = []
                    for h in ("e10", "e60", "e300"):
                        mu, t, n = block(np.where(f, D[h], np.nan) + rb, D["hour"])
                        out.append(f"{mu:+.2f}(t {t:+.1f})")
                    half = np.nanmean(D["half"][f]) if f.sum() else float("nan")
                    a60 = np.nanmean(D["a60"][f]) if f.sum() else float("nan")
                    # 每侧同一时刻一张:假想报价每 5 秒放一张、存活 life 秒,同时在簿里的有 life / 5 张 → 成交数除以这个重叠倍数
                    per_day = f.sum() / nd / (life / EVERY_S)
                    e60 = np.nanmean(D["e60"][f]) + rb if f.sum() else float("nan")
                    P(f"   存活 {life:>2d}s {lab:<5} 成交率 {f.sum() / nq:6.2%}  成交时优势 {half:+.2f}  60 秒不利变动 {a60:+.2f} | 每笔净值 10s / 60s / 300s:{' / '.join(out)}"
                      f" | 约 {per_day:,.0f} 笔/天 → ${per_day * ORDER_USD:,.0f}/天成交额,按 60 秒净值 ${per_day * ORDER_USD * e60 / 1e4:+.2f}/天")
            # 按放置时的价差分组(存活 60 秒,队尾口径,60 秒净值)
            m = (D["life"] == 60)
            parts = []
            for lab, k in (("价差 1 tick", D["spr"] == 1), ("价差 2 tick", D["spr"] == 2), ("价差 ≥ 3 tick", D["spr"] >= 3)):
                f = m & k & (D["fillQ"] == 1)
                mu, t, n = block(np.where(f, D["e60"], np.nan) + rb, D["hour"])
                parts.append(f"{lab}:{mu:+.2f}(t {t:+.1f},n {n},占放置 {(m & k).sum() / max(m.sum(), 1):.0%})")
            P("   排到队尾、存活 60s、60 秒净值,按放置时的价差:" + ";".join(parts))
    open(os.path.join(OUT, "ltk_report_" + "_".join(s[:4] for s in syms) + ".txt"), "w", encoding="utf8").write("\n".join(L))


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2], sys.argv[3])
    else:
        report(sys.argv[2:])
