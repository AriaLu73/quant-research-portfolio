#!/usr/bin/env python3
"""快速消库存的出场模拟(用户 10-16:"进了就赶紧想办法消库存吃反佣……目的不是持仓而是快速消库存";"记得把因子带上")。只读,线下。

样本  我们真实的每一笔挂单成交当作一次"进场"(一张单):十天回测(第三轮实盘组)+ 10-14 实盘,只取 12–18 时 UTC(有逐行因子值的时段)。
出场  进场成交后 JOIN_MS 毫秒,在对面挂一张平仓单(多仓卖、空仓买),几种挂法:
        d0  挂在出场那一侧的最优价(和最优价同价,排在已有挂单后面)
        d1 / d2  最优价后 1 / 2 跳
        in  价差 ≥ 2 跳时挂进价差里一跳(成为新的最优价,前面没人);价差只有 1 跳时同 d0
        taker  立刻吃单(对面最优价,付吃单费)
      挂上之后不动;到 TMAX 秒还没成交就吃单平掉(兜底)。
成交判定(只用 L2 逐笔 + 逐笔成交;data/research7/l2/<合约>_<日>.npz)
      穿价:有主动单打到比挂价更深的价位 → 全部成交。
      排队:挂上时该价位已有 Q 张排在前面(取自 10 毫秒网格的前五档);挂价上的成交先消耗前面的量,再轮到我们,累计到我们的单量就算成交。
        保守界  撤单都发生在我们后面(Q 只被成交消耗)
        乐观界  撤单都发生在我们前面(Q 不超过该价位当前的公共量)
一回合盈亏(bp,按进场价) = 方向 × (出场价 − 进场价)/进场价 × 1e4 + 进场返佣 我方费率 + 出场(挂单 +0.7 / 吃单 −1.8)
因子(进场成交那一刻之前的最后一个 10 毫秒网格行):
      obi      自己的买一卖一失衡 × 仓位方向(正 = 顺仓位方向,对出场不利的方向是负)
      tox_out  出场那一侧"马上要被扫"(多仓看 _ask:卖一被买方扫 = 我们的卖单会被成交):tox_deepecho / tox_bnpush / tox_bnunmatched
      tox_adv  逆风那一侧"马上要被扫"(多仓看 _bid)
      rls      rls_lag15_hl5min × 仓位方向
      rv       rv_ewm_10s
输出  data/factors/reeval/出场模拟_20261016.csv(逐样本)、.txt(汇总)
用法  Python314/python.exe scripts/research7/unwind_sim_20261016.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research7"))
import factor_reeval_eval as E                                      # noqa: E402

JOIN_MS = 5
TMAXS = (3, 10)
POLICIES = ("d0", "d1", "d2", "in")
REBATE, TAKER = 0.7, 1.8
LOTS = {"BTC": 30, "ETH": 100}                                      # 每张单 = 多少"张"(BTC 0.03 / 0.001;ETH 1.0 / 0.01)
TOX = ("tox_deepecho", "tox_bnpush", "tox_bnunmatched")


def load_events(nat, day):
    z = np.load(os.path.join(ROOT, "data", "research7", "l2", "%s_%s.npz" % (nat, day)))
    ts, kind, side, tk, sz = z["ts"], z["kind"], z["side"], z["tick"].astype(np.int64), z["size"].astype(np.int64)
    ev = {}
    for sd in (0, 1):                                                # 挂单方一侧:0 买盘、1 卖盘
        tr = (kind == 0) & (side == sd)
        lv = (kind == 1) & (side == sd)
        o = np.lexsort((ts[lv], tk[lv]))
        ev[sd] = dict(tr_ts=ts[tr], tr_tk=tk[tr], tr_sz=sz[tr],
                      lv_tk=tk[lv][o], lv_ts=ts[lv][o], lv_sz=sz[lv][o])
    return ev


def sim_exit(ev, sd, L, Q0, t_join, t_end, qty, exit_up):
    """在挂单方一侧 sd 的价位 L 挂 qty 张,t_join 起看到 t_end。exit_up = True:卖单(主动买打到 ≥ L 才成交)。
    返回 (保守界成交时刻, 乐观界成交时刻),没成交为 None。"""
    e = ev[sd]
    a, b = np.searchsorted(e["tr_ts"], t_join, side="right"), np.searchsorted(e["tr_ts"], t_end, side="right")
    tts, ttk, tsz = e["tr_ts"][a:b], e["tr_tk"][a:b], e["tr_sz"][a:b]
    deeper = (ttk > L) if exit_up else (ttk < L)
    t_thr = tts[deeper][0] if deeper.any() else None
    # 本价位的公共量变化(乐观界用)
    lo, hi = np.searchsorted(e["lv_tk"], L, side="left"), np.searchsorted(e["lv_tk"], L, side="right")
    lts, lsz = e["lv_ts"][lo:hi], e["lv_sz"][lo:hi]
    m = (lts > t_join) & (lts <= t_end)
    lts, lsz = lts[m], lsz[m]
    at = ttk == L
    trs_t, trs_s = tts[at], tsz[at]
    res = []
    for optimistic in (False, True):
        q, got, t_fill = float(Q0), 0.0, None
        i = j = 0
        while i < len(trs_t) or j < len(lts):                       # 按时间合并本价位的成交和公共量更新
            if j >= len(lts) or (i < len(trs_t) and trs_t[i] <= lts[j]):
                v = float(trs_s[i]); t = trs_t[i]; i += 1
                use = min(q, v); q -= use; v -= use
                if v > 0:
                    got += v
                    if got >= qty:
                        t_fill = t
                        break
            else:
                if optimistic:
                    q = min(q, float(lsz[j]))
                j += 1
        if t_thr is not None and (t_fill is None or t_thr < t_fill):
            t_fill = t_thr
        res.append(t_fill)
    return res


def run(sample, fills):
    rows = []
    for day in sorted(fills["day"].unique()):
        names = set(E.factor_names(day))
        for sym, (nat, j) in E.SYMS.items():
            f = fills[(fills["symbol"] == sym) & (fills["day"] == day) & fills["maker"]].sort_values("ts_ns")
            if not len(f):
                continue
            z = np.load(os.path.join(E.GRID, "%s_%s.npz" % (nat, day)))
            t0, n, tick = int(z["t0"]), len(z["ok"]), float(z["tick"])
            bp, ap, ok = z["bp"].astype(np.int64), z["ap"].astype(np.int64), z["ok"]
            _, mid = E.grid_mid(day, nat)
            rv1, rvew, _ = E.rv_feats(mid)
            ev = load_events(nat, day)
            fac = {"obi": E.load_factor(day, "obi_l1")[:, j], "rls": E.load_factor(day, "rls_lag15_hl5min")[:, j]}
            for tname in TOX:
                if tname + "_ask" in names:
                    fac[tname + "_ask"] = E.load_factor(day, tname + "_ask")[:, j]
                    fac[tname + "_bid"] = E.load_factor(day, tname + "_bid")[:, j]
            for r in f.itertuples():
                t, s, P = int(r.ts_ns), float(r.s), float(r.px)
                tj = t + JOIN_MS * 1_000_000
                rj = int((tj - t0) // E.STEP)                         # 挂上时刻所在网格行(含此刻及以前的更新)
                r0 = int(np.ceil((t - t0) / E.STEP)) - 1              # 进场成交之前的最后一行(因子用)
                if r0 < 1000 or rj + 1100 >= n or not ok[rj]:
                    continue
                exit_up = s > 0                                       # 多仓 → 卖出 → 挂在卖盘(sd = 1)
                sd = 1 if exit_up else 0
                best = ap[rj] if exit_up else bp[rj]
                opp = bp[rj] if exit_up else ap[rj]
                spread = int(ap[rj] - bp[rj])
                offs = z["ao"][rj] if exit_up else z["bo"][rj]
                sizes = z["as_"][rj] if exit_up else z["bs"][rj]
                row = dict(sample=sample, day=day, sym=sym, s=s, spread=spread,
                           obi=s * fac["obi"][r0], rls=s * fac["rls"][r0], rv=rvew[r0])
                for tname in TOX:
                    if tname + "_ask" in fac:
                        row[tname + "_out"] = fac[tname + ("_ask" if exit_up else "_bid")][r0]
                        row[tname + "_adv"] = fac[tname + ("_bid" if exit_up else "_ask")][r0]
                # 立刻吃单
                row["pnl_taker"] = s * (opp * tick - P) / P * 1e4 + REBATE - TAKER
                for pol in POLICIES:
                    if pol == "in":
                        d = -1 if spread >= 2 else 0
                    else:
                        d = int(pol[1])
                    L = best + d if exit_up else best - d
                    Q = 0.0
                    if d >= 0:
                        for k in range(offs.shape[0]):
                            if offs[k] == d:
                                Q = float(sizes[k])
                    for tmax in TMAXS:
                        te = tj + tmax * 1_000_000_000
                        cons, opti = sim_exit(ev, sd, L, Q, tj, te, LOTS[sym], exit_up)
                        re_ = min(int((te - t0) // E.STEP), n - 1)
                        fb = s * ((bp[re_] if exit_up else ap[re_]) * tick - P) / P * 1e4 + REBATE - TAKER   # 到点吃单兜底
                        mk = s * (L * tick - P) / P * 1e4 + 2 * REBATE                                       # 挂单出场
                        for tag, tf in (("c", cons), ("o", opti)):
                            k = "%s_%ds_%s" % (pol, tmax, tag)
                            row["fill_" + k] = tf is not None
                            row["wait_" + k] = (tf - tj) / 1e9 if tf is not None else np.nan
                            row["pnl_" + k] = mk if tf is not None else fb
                rows.append(row)
            print("  %s %s %s 进场 %d 笔" % (sample, day, sym, len(f)), flush=True)
    return pd.DataFrame(rows)


def summarize(df):
    L = []
    P = L.append
    keys = [("%s_%ds_%s" % (p, t, c)) for t in TMAXS for p in POLICIES for c in ("c", "o")]
    for (smp, sym), g in df.groupby(["sample", "sym"]):
        P("\n[%s %s] 进场 %d 笔;一回合盈亏 bp(含两次返佣/吃单费);立刻吃单 %+.2f" % (smp, sym, len(g), g["pnl_taker"].mean()))
        P("  %-14s %8s %10s %10s" % ("挂法_时限_界", "成交率", "等待中位秒", "回合盈亏"))
        for k in keys:
            P("  %-14s %7.0f%% %10.2f %+10.2f" % (k, 100 * g["fill_" + k].mean(), g["wait_" + k].median(), g["pnl_" + k].mean()))
        facs = [c for c in ("obi", "rls", "rv") + tuple(t + "_out" for t in TOX) + tuple(t + "_adv" for t in TOX) if c in g]
        for k in ("d0_10s_c", "d0_10s_o", "d0_3s_c"):
            P("  因子五分组(%s):各组 成交率 / 回合盈亏 bp(因子从低到高);IC = 因子 vs 回合盈亏 秩相关" % k)
            for c in facs:
                x = g[c].to_numpy()
                m = np.isfinite(x)
                if m.sum() < 50:
                    continue
                q = pd.qcut(pd.Series(x[m]).rank(method="first"), 5, labels=False).to_numpy()
                fr = [g["fill_" + k].to_numpy()[m][q == i].mean() for i in range(5)]
                pn = [g["pnl_" + k].to_numpy()[m][q == i].mean() for i in range(5)]
                tk = [g["pnl_taker"].to_numpy()[m][q == i].mean() for i in range(5)]
                ic = np.corrcoef(pd.Series(x[m]).rank(), pd.Series(g["pnl_" + k].to_numpy()[m]).rank())[0, 1]
                P("    %-22s IC %+.3f | 成交率 %s | 回合 %s | 立刻吃单 %s" % (c, ic, " ".join("%3.0f%%" % (100 * v) for v in fr),
                                                                       " ".join("%+5.2f" % v for v in pn), " ".join("%+5.2f" % v for v in tk)))
    return "\n".join(L)


if __name__ == "__main__":
    # 用户 10-16:"不需要十天啊…跑那么两个小时看一下效果就可以了" → 只用 10-14 实盘、命令行给的小时(UTC,在 12–17 之间)
    hours = [int(x) for x in sys.argv[1:]] or [13, 14]
    lv = E.live_fills()
    lv = lv[lv["hour"].isin(hours)]
    print("10-14 实盘,小时:", hours, flush=True)
    df = run("实盘1014", lv)
    df.to_csv(os.path.join(E.RE, "出场模拟_20261016_%s.csv" % "_".join(map(str, hours))), index=False, encoding="utf-8-sig")
    txt = summarize(df)
    open(os.path.join(E.RE, "出场模拟_20261016_%s.txt" % "_".join(map(str, hours))), "w", encoding="utf-8").write(txt)
    print(txt)
