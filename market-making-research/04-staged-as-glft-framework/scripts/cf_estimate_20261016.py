#!/usr/bin/env python3
"""完整框架三处"加法"的参数(用户 10-16:"你去算哪个加法markout最高";选定 ①②③ 各自单加 + 三个全加,回放 10-14 实盘有成交的小时)。只读,线下。

数据   data/research7/market_l2/<合约>_20261013.npz(10-14 的前一天;回放日 10-14 不参与估计)。全天。
状态   自己合约的买一卖一失衡 obi = (买一量 − 卖一量)/(买一量 + 卖一量),每 100 毫秒取一次;按当天的五分位分五档(边界 OBI_EDGES)。
①  漂移 m(档) = 该档样本之后 TAU 秒的中间价变动(bp)的平均。策略里 = m × 中间价 ÷ 10000(美元),替换原来 beta_obi × obi 那一项。
②  两侧成交强度按档:每档、每侧,λ(δ) = 该档里这一侧被打到离中间价 ≥ δ 的吃单笔数 ÷ 该档总时长;ln λ 对 δ 直线拟合 → k。
    写成倍数 = k(侧, 档) ÷ k(两侧合并、不分档,同一天同一办法),策略里 k_侧 = 部署参数 k × 倍数(和第 4 步 tox 档位倍数同一接法)。
③  逆向跳 J(侧, 档) = 这一侧被吃单打到之后 TAU 秒,中间价朝挂单方不利的方向走了多少(bp;从成交前最后一个中间价算起)的平均。
    策略里两侧半价差各加 J − 返佣(我方费率)。用的是全市场吃单,不是我们自己的成交(只是近似)。
用法  Python314/python.exe scripts/research7/cf_estimate_20261016.py
输出  data/research7/cf_params_20261013.json
"""
import json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAY, TAU, STEP = "20261013", 1.0, 0.1
TICK = {"XBTUSDTM": 0.1, "ETHUSDTM": 0.01}
DELTAS = {"XBTUSDTM": np.arange(0.1, 7.01, 0.1), "ETHUSDTM": 0.01 * np.arange(1, 71)}    # 与 as_offline.py 估 A、k 的网格相同


def fit_k(depth, deltas, T, min_count=30):
    cnt = np.array([(depth >= d).sum() for d in deltas])
    use = cnt >= min_count
    if use.sum() < 5:
        return np.nan, 0
    y = np.log(cnt[use] / T)
    return float(-np.polyfit(deltas[use], y, 1)[0]), int(len(depth))


out = {}
for nat in ("XBTUSDTM", "ETHUSDTM"):
    z = np.load(os.path.join(ROOT, "data", "research7", "market_l2", "%s_%s.npz" % (nat, DAY)))
    bbo, sw = z["bbo"], z["sw"]
    bbo = bbo[bbo[:, 2] > bbo[:, 1]]
    tick = TICK[nat]
    bt = bbo[:, 0].astype(np.int64)
    mid = (bbo[:, 1] + bbo[:, 2]) / 2.0 * tick
    qb, qa = bbo[:, 3].astype(float), bbo[:, 4].astype(float)
    obi = np.where(qb + qa > 0, (qb - qa) / (qb + qa), 0.0)
    # 100 毫秒网格;剔除盘口超过 5 秒没变的时刻(断档)
    g = np.arange(bt[0], bt[-1] - int(TAU * 1e9), int(STEP * 1e9))
    gi = np.searchsorted(bt, g, side="right") - 1
    gj = np.searchsorted(bt, g + int(TAU * 1e9), side="right") - 1
    fresh = (g - bt[gi]) < 5e9
    g, gi, gj = g[fresh], gi[fresh], gj[fresh]
    x = obi[gi]
    edges = np.quantile(x, [0.2, 0.4, 0.6, 0.8])
    b = np.searchsorted(edges, x, side="right")
    dm = (mid[gj] - mid[gi]) / mid[gi] * 1e4
    m_bp = [float(dm[b == i].mean()) for i in range(5)]
    Tb = [float((b == i).sum() * STEP) for i in range(5)]
    # 吃单:时刻、被打的一侧(1 = 卖盘被打 = 买方吃单)、打到的最远价
    tt = sw[:, 0].astype(np.int64)
    keep = (tt > g[0]) & (tt < g[-1])
    tt, side, px = tt[keep], sw[keep, 1].astype(int), sw[keep, 4] * tick
    ti = np.searchsorted(bt, tt, side="left") - 1                  # 成交之前最后一个盘口
    ok = ti >= 0
    tt, side, px, ti = tt[ok], side[ok], px[ok], ti[ok]
    tb = np.searchsorted(edges, obi[ti], side="right")
    sgn = np.where(side == 1, 1.0, -1.0)                           # 买方吃单 +1
    depth = sgn * (px - mid[ti])
    tj = np.searchsorted(bt, tt + int(TAU * 1e9), side="right") - 1
    adverse_bp = sgn * (mid[tj] - mid[ti]) / mid[ti] * 1e4          # 挂单方(被打的一侧)之后不利的方向为正
    deltas = DELTAS[nat]
    T_all = float(len(g) * STEP)
    k_pool, _ = fit_k(depth[depth > 0], deltas, 2 * T_all)
    kmult = {"ask": [], "bid": []}
    J = {"ask": [], "bid": []}
    nfit = {"ask": [], "bid": []}
    for sname, s_side in (("ask", 1), ("bid", 0)):
        for i in range(5):
            sel = (side == s_side) & (tb == i)
            d = depth[sel]
            kk, nn = fit_k(d[d > 0], deltas, Tb[i])
            kmult[sname].append(float(kk / k_pool) if np.isfinite(kk) else 1.0)
            nfit[sname].append(nn)
            J[sname].append(float(adverse_bp[sel].mean()) if sel.sum() >= 30 else 0.0)
    out[nat] = dict(day=DAY, tau_s=TAU, obi_edges=[float(e) for e in edges], m_bp=m_bp, k_pool=k_pool,
                    k_mult_ask=kmult["ask"], k_mult_bid=kmult["bid"], J_ask_bp=J["ask"], J_bid_bp=J["bid"],
                    n_trades_ask=nfit["ask"], n_trades_bid=nfit["bid"], hours_per_bucket=[t / 3600 for t in Tb])
    print(nat, json.dumps(out[nat], ensure_ascii=False, indent=1), flush=True)
json.dump(out, open(os.path.join(ROOT, "data", "research7", "cf_params_%s.json" % DAY), "w"), ensure_ascii=False, indent=1)
