#!/usr/bin/env python3
"""tox_bnpush 能不能预测"被打穿几档"(用户 10-16:"tox_bnpush有没有测能被打多少挡?" → "测吧")。只读,线下。

日子   09-23、09-24、10-14(都没用来找过这个因子),每天 12–18 时 UTC;BTC(XBTUSDTM)、ETH(ETHUSDTM)。
吃单   data/research7/l2/<合约>_<日>.npz 的成交(kind 0),同一时刻、同一侧的成交并成一笔吃单(用户规矩:成交须按吃单聚合)。
       盘口用 data/factors/grid 的 10 毫秒网格,取吃单时刻之前最后一格(只含之前的事件)。
       打穿深度 = 这笔吃单打到的最远价离吃单前本侧最优价几跳(0 = 只吃了盘口那一档);另报打穿的价位数(不同价格个数)、总张数、
       离中间价多少 bp。打到盘口以内的成交(价格没到本侧最优价,例如成对打印)不算走盘口,剔除。
因子   data/factors/tox1/<日>.npz 的 tox_bnpush_ask / _bid(RD 原代码算好的 10 毫秒网格),取吃单前 10 毫秒、50 毫秒那一格。
       卖盘被打(买方吃单)看 _ask,买盘被打看 _bid;另报"对面一侧的值"当对照:如果对面的值预测得一样好,它只是活跃度,不分侧。
检验   ① 给定被扫:在全部吃单上,因子值 vs 打穿深度的秩 IC(按天),因子五分位的平均深度、打穿 ≥1 / ≥3 / ≥10 跳的比例。
       ② 不给定:每 100 毫秒一个时刻,之后 1 秒内本侧被打穿的最大深度(没有吃单记 −1),秩 IC 与五分位。
用法   Python314/python.exe scripts/research7/bnpush_sweep_depth_20261016.py
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAYS = ("20260923", "20260924", "20261014")
SYMS = {"BTC": ("XBTUSDTM", 0), "ETH": ("ETHUSDTM", 1)}
STEP = 10_000_000


def sic(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 50:
        return np.nan
    return float(np.corrcoef(pd.Series(x[m]).rank(), pd.Series(y[m]).rank())[0, 1])


rowsA, rowsB, ics = [], [], []
for sym, (nat, j) in SYMS.items():
    for day in DAYS:
        g = np.load(os.path.join(ROOT, "data", "factors", "grid", "%s_%s.npz" % (nat, day)))
        t0, n, tick = int(g["t0"]), len(g["ok"]), float(g["tick"])
        ok = g["ok"] & (g["ap"] > g["bp"])
        bp, ap = g["bp"].astype(np.int64), g["ap"].astype(np.int64)
        tx = np.load(os.path.join(ROOT, "data", "factors", "tox1", "%s.npz" % day))
        F = {1: tx["tox_bnpush_ask"][:, j].astype(float), 0: tx["tox_bnpush_bid"][:, j].astype(float)}
        L = np.load(os.path.join(ROOT, "data", "research7", "l2", "%s_%s.npz" % (nat, day)))
        tr = (L["kind"] == 0) & (L["ts"] > t0 + 1_000_000_000) & (L["ts"] < t0 + n * STEP - 2_000_000_000)
        df = pd.DataFrame(dict(ts=L["ts"][tr].astype(np.int64), side=L["side"][tr].astype(int), tk=L["tick"][tr].astype(np.int64),
                               sz=L["size"][tr].astype(float)))
        sw = df.groupby(["ts", "side"]).agg(tmax=("tk", "max"), tmin=("tk", "min"), nlv=("tk", "nunique"), sz=("sz", "sum")).reset_index()
        r = ((sw["ts"].to_numpy() - t0 - 1) // STEP).astype(np.int64)          # 吃单之前最后一格
        good = ok[r]
        sw, r = sw[good].reset_index(drop=True), r[good]
        s = sw["side"].to_numpy()
        far = np.where(s == 1, sw["tmax"].to_numpy(), sw["tmin"].to_numpy())
        best = np.where(s == 1, ap[r], bp[r])
        depth = np.where(s == 1, far - best, best - far)                      # 离本侧最优价几跳
        midr = (ap[r] + bp[r]) / 2.0
        keep = depth >= 0                                                     # 打到盘口以内的不算走盘口
        sw, r, s, depth, far, midr = sw[keep], r[keep], s[keep], depth[keep], far[keep], midr[keep]
        dbp = np.abs(far - midr) / midr * 1e4
        # ③ 被打之后走多远:挂单方不利方向为正(卖盘被打 → 之后涨为正),从吃单前的中间价算起;中间价无效的格子沿用之前的值
        midg = pd.Series(np.where(ok, (ap + bp) / 2.0, np.nan)).ffill().to_numpy()
        sg = np.where(s == 1, 1.0, -1.0)
        adv = {}
        for tau_ms in (100, 1000, 10000):
            k = np.minimum(r + tau_ms // 10, n - 1)
            adv[tau_ms] = sg * (midg[k] - midr) / midr * 1e4
        for lag in (10, 50):
            rl = r - lag // 10
            own = np.where(s == 1, F[1][rl], F[0][rl])
            opp = np.where(s == 1, F[0][rl], F[1][rl])
            ics.append(dict(sym=sym, day=day, lag=lag, n=len(depth), own_ic=sic(own, depth.astype(float)), opp_ic=sic(opp, depth.astype(float)),
                            own_ic_bp=sic(own, dbp), own_ic_lv=sic(own, sw["nlv"].to_numpy().astype(float)),
                            own_ic_sz=sic(own, sw["sz"].to_numpy())))
            if lag == 10:
                rowsA.append(pd.DataFrame(dict(sym=sym, day=day, own=own, opp=opp, depth=depth, dbp=dbp, a01=adv[100], a1=adv[1000], a10=adv[10000])))
        # ② 不给定被扫:每 100 毫秒,之后 1 秒内本侧被打穿的最大深度(−1 = 没被打)
        samp = np.arange(200, n - 200, 10)
        for side in (1, 0):
            mx = np.full(n, -1, np.int64)
            m = s == 1 if side == 1 else s == 0
            np.maximum.at(mx, r[m], depth[m])
            mb = np.full(n, -1.0)
            np.maximum.at(mb, r[m], dbp[m])
            futb = pd.Series(mb[::-1]).rolling(100, min_periods=1).max().to_numpy()[::-1]
            labb = np.r_[futb[1:], -1][samp]
            # 之后 1 秒(100 格)内的最大值:行 i 的标签 = max(mx[i+1 .. i+100])
            fut = pd.Series(mx[::-1]).rolling(100, min_periods=1).max().to_numpy()[::-1]
            lab = np.r_[fut[1:], -1][samp]
            f_own = F[side][samp - 1]
            rowsB.append(pd.DataFrame(dict(sym=sym, day=day, side=side, own=f_own, opp=F[1 - side][samp - 1], lab=lab, labb=labb, ok=ok[samp])))
        print("  %s %s 完成:吃单 %d 笔" % (sym, day, len(depth)), flush=True)

I = pd.DataFrame(ics)
print("\n① 给定被扫:因子(吃单前 10 / 50 毫秒)vs 打穿深度的秩 IC(按天)")
print("  %-4s %-9s %4s %7s | %8s %8s | %8s %8s %8s" % ("合约", "日", "提前", "吃单数", "本侧→跳数", "对面→跳数", "本侧→bp", "本侧→档数", "本侧→张数"))
for _, x in I.iterrows():
    print("  %-4s %-9s %3dms %7d | %+8.3f %+8.3f | %+8.3f %+8.3f %+8.3f" % (x.sym, x.day, x.lag, x.n, x.own_ic, x.opp_ic, x.own_ic_bp, x.own_ic_lv, x.own_ic_sz))
A = pd.concat(rowsA)
print("\n① 给定被扫:按本侧因子五分位(每天各自分),打穿深度(提前 10 毫秒)")
for sym, a in A.groupby("sym"):
    a = a.copy()
    a["q"] = a.groupby("day")["own"].transform(lambda v: pd.qcut(v.rank(method="first"), 5, labels=False))
    print("  %s  五分位   平均跳数   平均离中间价bp   ≥1跳   ≥3跳   ≥10跳" % sym)
    for q, b in a.groupby("q"):
        d = b["depth"]
        print("        %d   %8.2f   %10.2f   %5.1f%% %5.1f%% %5.1f%%" % (q + 1, d.mean(), b["dbp"].mean(), 100 * (d >= 1).mean(), 100 * (d >= 3).mean(), 100 * (d >= 10).mean()))
B = pd.concat(rowsB)
B = B[B["ok"]]
print("\n② 不给定被扫:每 100 毫秒,本侧因子 vs 之后 1 秒内本侧被打穿的最大深度(没被打 = −1)")
for sym, b in B.groupby("sym"):
    icd = [sic(c["own"].to_numpy(), c["lab"].to_numpy().astype(float)) for _, c in b.groupby("day")]
    ico = [sic(c["opp"].to_numpy(), c["lab"].to_numpy().astype(float)) for _, c in b.groupby("day")]
    print("  %s 秩 IC 本侧 %s | 对面 %s" % (sym, " ".join("%+.3f" % v for v in icd), " ".join("%+.3f" % v for v in ico)))
    b = b.copy()
    b["q"] = b.groupby("day")["own"].transform(lambda v: pd.qcut(v.rank(method="first"), 5, labels=False))
    print("     五分位   被打比例   被打时平均跳数   ≥3跳比例   ≥10跳比例 | 打到离中间价 ≥0.5bp  ≥1bp  ≥2bp")
    for q, c in b.groupby("q"):
        hit = c["lab"] >= 0
        print("        %d    %6.2f%%     %8.2f       %6.3f%%   %6.3f%%" % (q + 1, 100 * hit.mean(), c.loc[hit, "lab"].mean() if hit.any() else np.nan,
                                                                     100 * (c["lab"] >= 3).mean(), 100 * (c["lab"] >= 10).mean())
              + " | %8.3f%% %6.3f%% %6.3f%%" % (100 * (c["labb"] >= 0.5).mean(), 100 * (c["labb"] >= 1).mean(), 100 * (c["labb"] >= 2).mean()))

print("\n③ 被打之后走多远(bp,挂单方不利方向为正,从吃单前中间价算起;本侧因子取吃单前 10 毫秒)")
for sym, a in A.groupby("sym"):
    print("  %s 秩 IC(本侧因子 vs 之后 1 秒走势,按天):本侧 %s | 对面 %s" % (sym,
          " ".join("%+.3f" % sic(c["own"].to_numpy(), c["a1"].to_numpy()) for _, c in a.groupby("day")),
          " ".join("%+.3f" % sic(c["opp"].to_numpy(), c["a1"].to_numpy()) for _, c in a.groupby("day"))))
    a = a.copy()
    a["q"] = a.groupby("day")["own"].transform(lambda v: pd.qcut(v.rank(method="first"), 5, labels=False))
    print("     五分位 | 全部吃单:之后 0.1s   1s    10s | 打到 ≥0.5bp 的:笔数 挂在0.5bp的单 markout 1s  10s | 打到 ≥1bp 的:笔数 挂在1bp的单 markout 1s  10s")
    for q, b in a.groupby("q"):
        h5, h10 = b[b["dbp"] >= 0.5], b[b["dbp"] >= 1.0]
        print("        %d   |            %+6.2f %+6.2f %+6.2f |            %5d          %+6.2f %+6.2f |          %5d         %+6.2f %+6.2f" % (
            q + 1, b["a01"].mean(), b["a1"].mean(), b["a10"].mean(), len(h5), (0.5 - h5["a1"]).mean(), (0.5 - h5["a10"]).mean(),
            len(h10), (1.0 - h10["a1"]).mean(), (1.0 - h10["a10"]).mean()))
    print("     按打穿深度分(不分因子):")
    for lo, hi, lab in ((0, 0, "只吃盘口"), (1, 2, "1–2跳"), (3, 9, "3–9跳"), (10, 49, "10–49跳"), (50, 10**9, "≥50跳")):
        b = a[(a["depth"] >= lo) & (a["depth"] <= hi)]
        if len(b):
            print("        %-8s 笔数 %6d  之后 0.1s %+6.2f  1s %+6.2f  10s %+6.2f" % (lab, len(b), b["a01"].mean(), b["a1"].mean(), b["a10"].mean()))

print("\n④ 挂在盘口(本侧最优价)的单,被这笔吃单打到时的 markout(bp)= 半个价差 − 之后走势;只吃盘口那一档的吃单 / 全部吃单")
print("   注意:吃单只吃掉盘口一部分时,排在队尾的单不一定被打到;这里按'被打到'算,是排在队首的情形")
for sym, a in A.groupby("sym"):
    a = a.copy()
    a["q"] = a.groupby("day")["own"].transform(lambda v: pd.qcut(v.rank(method="first"), 5, labels=False))
    print("  %s 五分位 | 只吃盘口:笔数  1s   1s+返佣我方费率  10s+返佣 | 全部:1s+返佣  我方费率s+返佣" % sym)
    for q, b in a.groupby("q"):
        t = b[b["depth"] == 0]
        hs = 0.0                                                        # 半个价差在这两个合约上 ≤ 0.02 bp,忽略
        print("        %d    |      %6d %+6.2f   %+6.2f     %+6.2f   |   %+6.2f     %+6.2f" % (q + 1, len(t), hs - t["a1"].mean(), hs - t["a1"].mean() + 0.7,
              hs - t["a10"].mean() + 0.7, hs - b["a1"].mean() + 0.7, hs - b["a10"].mean() + 0.7))
