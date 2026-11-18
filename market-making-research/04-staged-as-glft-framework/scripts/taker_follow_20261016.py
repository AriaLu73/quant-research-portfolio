#!/usr/bin/env python3
""""打不过就加入":吃单跟着扫单进场、马上挂单出场(用户 10-16:"能不能开发一个打不过就加入,反正每次成交都被逆向,
那我直接taker单去打我原来想做的maker单然后成交了就赶紧挂maker单走人")。只读,线下。

触发  每一侧"马上要被扫"的两个分数(tox_bnpush、tox_deepecho 的本侧值,RD 原代码算好的 data/factors/tox1)。
      分数换成当天 12–18 时的分位(0–1;同一天的分布,有一点"事先知道"),取两者较大的 S。
      卖盘要被扫(价格要往上冲)→ 吃单买入;买盘要被扫 → 吃单卖出。S 从门槛下方穿到上方的那一刻触发;同一侧两次触发至少隔 1 秒。
      门槛分 0.8 / 0.9 / 0.95 / 0.99 四档;另报"再要求自己的盘口失衡同向"的子集。
进场  触发后 LAT_MS 毫秒,按当时对面最优价吃单(买入用卖一),付吃单费 我方费率。
出场  进场后立刻在对面挂单(买入后挂卖单在卖一;排队 / 穿价判定同 unwind_sim_20261016.py,保守界),
      τ 秒内没成交就按当时的最优价吃单平掉。τ = 1 / 3 / 10 秒。
一回合(bp,按进场价)= 方向 × (出场价 − 进场价)/进场价 × 1e4 − 1.8 + (挂单出场 +0.7 / 吃单出场 −1.8)
另报  进场后 50 毫秒 / 1 秒 / 10 秒的中间价走势(方向 × (中间价 − 进场价),bp):这是原始的可得空间。
用法  Python314/python.exe scripts/research7/taker_follow_20261016.py <小时> <小时>
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research7"))
import factor_reeval_eval as E                                      # noqa: E402
import unwind_sim_20261016 as U                                     # noqa: E402

DAY = "20261014"
LAT_MS = 5
THRS = (0.8, 0.9, 0.95, 0.99)
TMAXS = (1, 3, 10)
TAKER, REBATE = OUR_FEE, 0.7
hours = [int(x) for x in sys.argv[1:]] or [13, 14]


def pct(x):
    s = pd.Series(x)
    return s.rank(pct=True).to_numpy()


rows = []
for sym, (nat, j) in E.SYMS.items():
    z = np.load(os.path.join(E.GRID, "%s_%s.npz" % (nat, DAY)))
    t0, n, tick = int(z["t0"]), len(z["ok"]), float(z["tick"])
    bp, ap, ok = z["bp"].astype(np.int64), z["ap"].astype(np.int64), z["ok"]
    # 10-16 修:无效行(ok = False)的买一卖一是 0,出场按 0 价平仓会算出 ±10000 bp;改用之前最后一个有效行
    good = ok & (ap > bp) & (bp > 0)
    keep = np.maximum.accumulate(np.where(good, np.arange(n), 0))
    bp, ap = bp[keep], ap[keep]
    _, mid = E.grid_mid(DAY, nat)
    tox = np.load(os.path.join(E.TOX1, "%s.npz" % DAY))
    obi = E.load_factor(DAY, "obi_l1")[:, j]
    S = {}
    for side, suf in ((1, "_ask"), (0, "_bid")):                    # 1 = 卖盘要被扫(往上),0 = 买盘要被扫(往下)
        a = pct(tox["tox_bnpush" + suf][:, j].astype(float))
        b = pct(tox["tox_deepecho" + suf][:, j].astype(float))
        S[side] = np.fmax(a, b)
    ev = U.load_events(nat, DAY)
    hrow = (np.arange(n) * E.STEP + t0) // 3_600_000_000_000 % 24
    for side in (1, 0):
        s_dir = 1.0 if side == 1 else -1.0                          # 往上冲 → 买入
        for thr in THRS:
            cross = np.flatnonzero((S[side][1:] >= thr) & (S[side][:-1] < thr)) + 1
            last = -10**9
            for r in cross:
                if not (np.isin(hrow[r], hours)) or r < 1000 or r + 1200 >= n or not ok[r]:
                    continue
                if r - last < 100:
                    continue
                last = r
                te = t0 + r * E.STEP + LAT_MS * 1_000_000
                re_ = int((te - t0) // E.STEP)
                P = (ap[re_] if s_dir > 0 else bp[re_]) * tick       # 吃单进场价
                row = dict(sym=sym, side="买入" if s_dir > 0 else "卖出", thr=thr, obi_same=bool(np.sign(obi[r]) == s_dir) if np.isfinite(obi[r]) else False)
                for d, k in ((50, "m50"), (1000, "m1s"), (10000, "m10s")):
                    kk = min(int((te + d * 1_000_000 - t0) // E.STEP), n - 1)
                    row[k] = s_dir * (mid[kk] - P) / P * 1e4
                # 出场:买入后挂卖单在卖一(卖盘一侧 sd = 1),卖出后挂买单在买一
                exit_up = s_dir > 0
                sd = 1 if exit_up else 0
                L = ap[re_] if exit_up else bp[re_]
                offs = z["ao"][re_] if exit_up else z["bo"][re_]
                sizes = z["as_"][re_] if exit_up else z["bs"][re_]
                Q = 0.0
                for kx in range(offs.shape[0]):
                    if offs[kx] == 0:
                        Q = float(sizes[kx])
                cons10, _ = U.sim_exit(ev, sd, L, Q, te, te + max(TMAXS) * 1_000_000_000, U.LOTS[sym], exit_up)   # 只模拟一次,各时限由成交时刻推出
                for tmax in TMAXS:
                    tend = te + tmax * 1_000_000_000
                    cons = cons10 if (cons10 is not None and cons10 <= tend) else None
                    if cons is not None:
                        pnl = s_dir * (L * tick - P) / P * 1e4 - TAKER + REBATE
                    else:
                        kk = min(int((tend - t0) // E.STEP), n - 1)
                        px = (bp[kk] if exit_up else ap[kk]) * tick
                        pnl = s_dir * (px - P) / P * 1e4 - TAKER - TAKER
                    row["fill_%ds" % tmax] = cons is not None
                    row["pnl_%ds" % tmax] = pnl
                rows.append(row)
    print("  %s 完成" % sym, flush=True)

df = pd.DataFrame(rows)
df.to_csv(os.path.join(ROOT, "data", "research7", "taker_follow_%s_%s.csv" % (DAY, "_".join(map(str, hours)))), index=False, encoding="utf-8-sig")
print("\n10-14 %s 时 UTC:吃单跟扫单进场、挂单出场(一回合含吃单费 我方费率 和返佣 我方费率;盈亏平衡约需走 1.1 bp)" % hours)
print("%-4s %-5s %-8s %5s | %7s %7s %7s | %13s %13s %13s" % ("合约", "门槛", "失衡同向", "次数", "走势50ms", "1s", "10s", "1s出场:成交率/回合", "3s", "10s"))
for (sym, thr), g in df.groupby(["sym", "thr"]):
    for lab, h in (("全部", g), ("同向", g[g["obi_same"]])):
        if len(h) < 5:
            continue
        print("%-4s %-5s %-8s %5d | %+7.2f %+7.2f %+7.2f | %5.0f%% %+6.2f %5.0f%% %+6.2f %5.0f%% %+6.2f" % (
            sym, thr, lab, len(h), h["m50"].mean(), h["m1s"].mean(), h["m10s"].mean(),
            100 * h["fill_1s"].mean(), h["pnl_1s"].mean(), 100 * h["fill_3s"].mean(), h["pnl_3s"].mean(), 100 * h["fill_10s"].mean(), h["pnl_10s"].mean()))
