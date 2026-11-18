#!/usr/bin/env python3
"""research7 阶段 6(研究八)的离线检验:快速撤单触发规则能否在被扫穿之前撤掉最不利的成交。不含策略回放。

用途      在阶段 4 的假想报价(固定价格、存活 10 秒)上加一条"触发即撤"的规则,看留下的成交每笔净值、每张报价的期望净值、
          成交保留比例与撤单准确率怎样变化。
所属阶段  阶段 6,研究八第 4 条(预登记 00_范围_阈值_预登记.md 第 15 节,常数均来自那里)。
对应公式  执行层的"撤单"操作(报价何时落地);不改变报价公式里的任何一项。
时间口径  每 100 毫秒(网格间隔)检查一次;在第 j 个网格行上看到触发 → 撤单在第 j + 1 行生效(100 毫秒,保守:实测撤单 p90 15.6 ms)。
          成交发生在第 it 行(成交前的状态行)之内:只要存在 j ≤ it − 1 且 j > 放置行 的触发,这笔成交就被撤掉了。
变量      eps = ε;e10 = ε·(m_10s − P)(bp);每笔净值 = e10 + 返佣 我方费率。
用法      .venv/Scripts/python.exe scripts/research7/exec_study.py build <YYYYMMDD>
          .venv/Scripts/python.exe scripts/research7/exec_study.py report
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calib as C

ROOT = C.ROOT
FEAT = os.path.join(ROOT, "data", "research7", "feat")
MKT = os.path.join(ROOT, "data", "research7", "market_l2")
OUT = os.path.join(ROOT, "data", "research7", "exec")
TICK, STEP_NS, GRID_PER_S = 0.1, 100_000_000, 10
DELTAS = (0, 20)                 # 只看两个距离:加入最优价、20 tick 外(预登记)
EVERY_S, LIFE_S, H = 5, 10, 10
GAP_S = 5.0
REBATE = OUR_FEE
OCT = ("20261001", "20261002")
# 触发的原始量(每个网格行、每一侧一个数;阈值在 report 里用训练段分位确定)
TRIG = ("hit", "imb", "bn", "near")
COLS = ("hour", "side", "di", "fill", "e10", "a10", "through", "t_fill") + tuple(f"first_{k}" for k in ("hit0", "hit50", "hit90", "imb", "bn25", "bn50", "near")) + ("swept1s",)


def build(day):
    z = np.load(os.path.join(FEAT, f"feat_{day}.npz"))
    g = z["g"].astype(np.int64)
    g0, n = int(g[0]), len(g)
    bb, ba = z["bb"].astype(np.int64), z["ba"].astype(np.int64)
    qb, qa = z["qb"].astype(float), z["qa"].astype(float)
    mid2 = bb + ba
    ok = (z["age"] < GAP_S) & np.r_[True, np.diff(g) == 1]
    imb = (qb - qa) / np.maximum(qb + qa, 1.0)
    # 第 j 行 = 第 j 个 100 毫秒区间开始时的状态;tb / ts_ 的第 j 行是"刚结束的那个区间"里的吃单量(feat_grid 在进入新区间时写行)
    hit = (z["ts_"].astype(float), z["tb"].astype(float))        # 打到买盘(吃单卖出)/ 打到卖盘(吃单买入)
    bn = np.zeros(n)
    fb = os.path.join(FEAT, f"bn_{day}.npz")
    if os.path.exists(fb):
        zb = np.load(fb)
        j = g - int(zb["g0"]) - 1                                # 币安滞后一个网格点
        v = (j >= 1) & (j < len(zb["px"]))
        px = zb["px"].astype(float)
        bn[v] = (np.log(px[j[v]]) - np.log(px[j[v] - 1])) * 1e4   # 币安过去 100 毫秒的收益(bp)
    sw = np.load(os.path.join(MKT, f"XBTUSDTM_{day}.npz"))["sw"]
    per_side = [(sw[sw[:, 1] == s][:, 0], sw[sw[:, 1] == s][:, 4]) for s in (0, 1)]
    # 训练段分位在 report 里才有;这里先把"是否触发"所需的原始量按固定的几个绝对阈值预先算好,阈值在文件头 THR 里
    thr = np.load(os.path.join(OUT, "thr.npy"))                  # [hit 中位, hit 90%, imb 20%](训练段;build 之前由 thr 模式生成)
    rows = []
    life = LIFE_S * GRID_PER_S
    for i0 in range(0, n - (life + (H + 2) * GRID_PER_S), EVERY_S * GRID_PER_S):
        if not ok[i0]:
            continue
        t0 = int(g[i0]) * STEP_NS
        for s in (0, 1):
            ts_s, last_s = per_side[s]
            lo, hi = np.searchsorted(ts_s, (t0, t0 + LIFE_S * 10**9), side="right")
            eps = 1 if s == 0 else -1
            best0 = bb[i0] if s == 0 else ba[i0]
            sl = slice(i0 + 1, i0 + life + 1)                    # 存活期间的检查行(放置之后)
            h = hit[s][sl]
            im = (imb[sl] if s == 0 else -imb[sl])
            b_adv = -eps * bn[sl]                                # 币安朝不利方向的变动(bp):买单怕跌
            best_now = bb[sl] if s == 0 else ba[sl]
            for di, d in enumerate(DELTAS):
                p = best0 - d if s == 0 else best0 + d
                # 第一笔到达或穿过我方价位的吃单
                jf = -1
                for j in range(lo, hi):
                    if (last_s[j] <= p) if s == 0 else (last_s[j] >= p):
                        jf = j
                        break
                fill, e10, a10, thru, it = 0, np.nan, np.nan, 0, i0 + life
                if jf >= 0:
                    tfill = int(ts_s[jf])
                    it = int(min(max(tfill // STEP_NS - g0, 0), n - 1))
                    fill, thru = 1, int((last_s[jf] < p) if s == 0 else (last_s[jf] > p))
                    ih = it + H * GRID_PER_S + 1
                    if ih < n and ok[ih] and ok[it]:
                        m0, mh = mid2[it] / 2.0, mid2[ih] / 2.0
                        e10, a10 = eps * (mh - p) / m0 * 1e4, -eps * (mh - m0) / m0 * 1e4
                # 各触发第一次为真的检查行(相对放置行的偏移,从 1 起;没有则为大数)
                dist = (best_now - p) if s == 0 else (p - best_now)       # 同侧最优价到我方价位的距离(tick)
                conds = (h > 0, h >= thr[0], h >= thr[1], im <= thr[2], b_adv >= 0.25, b_adv >= 0.5,
                         (dist <= d / 2) if d > 0 else np.zeros(life, bool))
                firsts = [int(np.argmax(c)) + 1 if c.any() else 10**6 for c in conds]
                # 撤单准确率用:任一行触发后 1 秒内该价位是否被到达(用第一笔到达的时间近似)
                rows.append(((g0 + i0) // (3600 * GRID_PER_S), s, di, fill, e10, a10, thru, it - i0, *firsts, 0))
    A = np.asarray(rows, np.float64)
    np.save(os.path.join(OUT, f"x_{day}.npy"), A.astype(np.float32))
    print(f"exec {day}: {len(A):,} 张假想报价  EXEC_BUILD_DONE", flush=True)


def make_thr():
    """训练段分位(只用训练段):打到一侧的 100 毫秒吃单量的非零中位数与 90% 分位;朝向一侧的不平衡的 20% 分位。"""
    hits, imbs = [], []
    for d in C.TRAIN_DAYS:
        z = np.load(os.path.join(FEAT, f"feat_{d}.npz"))
        x = np.r_[z["tb"], z["ts_"]].astype(float)
        hits.append(x[x > 0])
        qb, qa = z["qb"].astype(float), z["qa"].astype(float)
        imbs.append(((qb - qa) / np.maximum(qb + qa, 1.0))[::50])
    h, im = np.concatenate(hits), np.concatenate(imbs)
    thr = np.array([np.median(h), np.quantile(h, 0.9), np.quantile(np.r_[im, -im], 0.2)])
    os.makedirs(OUT, exist_ok=True)
    np.save(os.path.join(OUT, "thr.npy"), thr)
    print("阈值(训练段):吃单量非零中位 %.0f 张,90%% 分位 %.0f 张;不平衡 20%% 分位 %.3f" % tuple(thr), flush=True)


def load(days):
    A = np.vstack([np.load(os.path.join(OUT, f"x_{d}.npy")).astype(np.float64) for d in days])
    return {c: A[:, i] for i, c in enumerate(COLS)}


def report():
    L = []
    P = lambda s="": (L.append(s), print(s, flush=True))
    TR, VA, OC = load(C.TRAIN_DAYS), load(C.VALID_DAYS), load(OCT)
    P("阶段 6 离线:快速撤单触发(假想报价,存活 10 秒;触发后 100 毫秒撤单生效;队首口径)")
    names = {"hit0": "T1 同侧被吃 > 0", "hit50": "T1 同侧被吃 ≥ 中位", "hit90": "T1 同侧被吃 ≥ 90% 分位", "imb": "T2 不平衡转逆", "bn25": "T3 币安逆向 ≥ 0.25 bp",
             "bn50": "T3 币安逆向 ≥ 0.5 bp", "near": "T4 价格逼近一半"}

    def evalrule(D, di, firsts):
        """firsts: 该规则第一次触发的偏移(数组)。返回 报价数、不撤时成交数与每笔净值、留下的成交数与每笔净值、每张报价期望净值(不撤 / 撤)、
        被撤掉的成交的每笔净值、撤单准确率的代理(触发的报价里,之后确实被到达的比例)、逐小时配对差的 t。"""
        m = D["di"] == di
        fill = (D["fill"] == 1) & m & np.isfinite(D["e10"])
        net = D["e10"] + REBATE
        cancelled = firsts <= D["t_fill"] - 1                          # 触发行 ≤ 成交行 − 1 → 成交前撤单已生效
        kept = fill & ~cancelled
        avoided = fill & cancelled
        nq = m.sum()
        trig_any = m & (firsts < 10**6)
        acc = (D["fill"][trig_any] == 1).mean() if trig_any.sum() else float("nan")
        # 逐小时:留下的成交的每笔净值 − 全部成交的每笔净值
        hs = np.unique(D["hour"][m])
        d = []
        for h in hs:
            k = D["hour"] == h
            if (kept & k).sum() >= 5 and (fill & k).sum() >= 5:
                d.append(net[kept & k].mean() - net[fill & k].mean())
        mu, t, _ = C.nw_t(d)
        return dict(nq=int(nq), n_all=int(fill.sum()), net_all=float(net[fill].mean()), n_kept=int(kept.sum()), net_kept=float(net[kept].mean()) if kept.sum() else float("nan"),
                    ev_all=float(net[fill].sum() / nq), ev_kept=float(net[kept].sum() / nq), net_avoided=float(net[avoided].mean()) if avoided.sum() else float("nan"),
                    acc=float(acc), trig_share=float(trig_any.sum() / nq), t=t)

    for di, d in enumerate(DELTAS):
        P(f"\n== 距离 {d} tick")
        P("   规则                       | 训练:成交保留  每笔净值 留下 / 全部 / 被撤掉的   每张报价期望净值 撤 / 不撤(×1e-2 bp)  触发比例  触发后确被到达")
        res = {}
        for k, lab in names.items():
            if k == "near" and d == 0:
                continue
            r = evalrule(TR, di, TR[f"first_{k}"])
            res[k] = r
            P(f"   {lab:<24} | {r['n_kept'] / r['n_all']:>6.1%}   {r['net_kept']:+.2f} / {r['net_all']:+.2f} / {r['net_avoided']:+.2f}        {r['ev_kept'] * 100:+7.2f} / {r['ev_all'] * 100:+7.2f}        {r['trig_share']:.1%}    {r['acc']:.1%}")
        order = sorted(res, key=lambda k: -res[k]["ev_kept"])
        best = order[0]
        combo = np.minimum(TR[f"first_{order[0]}"], TR[f"first_{order[1]}"])
        rc = evalrule(TR, di, combo)
        P(f"   组合({names[order[0]]} 或 {names[order[1]]})| {rc['n_kept'] / rc['n_all']:>6.1%}   {rc['net_kept']:+.2f} / {rc['net_all']:+.2f} / {rc['net_avoided']:+.2f}        {rc['ev_kept'] * 100:+7.2f} / {rc['ev_all'] * 100:+7.2f}")
        use_combo = rc["ev_kept"] > res[best]["ev_kept"]
        sel = f"组合({order[0]} 或 {order[1]})" if use_combo else best
        P(f"   训练段选定(每张报价期望净值最高):{sel if use_combo else names[best]}")
        for seg, D in (("验证", VA), ("10 月", OC)):
            f = np.minimum(D[f"first_{order[0]}"], D[f"first_{order[1]}"]) if use_combo else D[f"first_{best}"]
            r = evalrule(D, di, f)
            P(f"   {seg}(只读一次):成交保留 {r['n_kept'] / r['n_all']:.1%};每笔净值 留下 {r['net_kept']:+.2f} / 全部 {r['net_all']:+.2f} / 被撤掉的 {r['net_avoided']:+.2f} bp;"
              f"留下 − 全部 的逐小时配对 t {r['t']:+.1f};每张报价期望净值 撤 {r['ev_kept'] * 100:+.2f} / 不撤 {r['ev_all'] * 100:+.2f}(×1e-2 bp);触发后确被到达 {r['acc']:.1%}")
    open(os.path.join(OUT, "exec_study_report.txt"), "w", encoding="utf8").write("\n".join(L))
    print("EXEC_REPORT_DONE", flush=True)


if __name__ == "__main__":
    {"build": lambda: build(sys.argv[2]), "thr": make_thr, "report": report}[sys.argv[1]]()
