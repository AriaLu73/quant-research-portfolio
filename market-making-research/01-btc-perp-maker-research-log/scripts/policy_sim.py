#!/usr/bin/env python3
"""快速策略模拟器(研究闭环用,最终验证仍走 engine/backtest):贴盘口双边做市 + 状态门控 + 库存控制。

与 quote_econ 相同的 QueuePositionEstimator(ESTIMATED,队尾入队、撤单归因 0.5),逐行事件循环:
  - 每侧至多一张贴盘口单;post/pull 由状态门控(含滞回)与库存决定;
  - 盘口价上移(被插队)→ 撤单按新盘口重挂(若门控允许);盘口价被吃穿/撤空 → 我方成为唯一挂单,下一笔同侧主动成交即成交;
  - 成交:队列推进量 ≥ Q + S;费用:maker 返费 rebate_bp;无 taker;
  - 净收益 = 已实现(FIFO)+ 期末按 mid 计价 + 返费;记录每笔成交的 markout 与状态。
用法:python scripts/research/policy_sim.py --days 20251001,20260101,20260401 --policy baseline
      python scripts/research/policy_sim.py --grid  (跑预设参数面板,输出 docs/research/policy_grid.md)
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KU = os.path.join(ROOT, "data", "research", "kucoin")
FOUT = os.path.join(ROOT, "data", "research", "factors")
US = 1000
CANCEL_BIAS = 0.5

DEFAULT = dict(
    clip=0.15, max_clips=3, rebate_bp=OUR_FEE,
    # 门控(对齐:本侧有利为正)。None/0 = 关
    imb_post=None, imb_pull=None,          # imb5 对齐阈值(post 高于 / pull 低于)
    ofi_post=None, ofi_pull=None,          # ofi_1000ms 对齐
    vol_max=None,                          # vol_10000ms 上限(bp)
    tint_max=None,                         # tint_1000ms 上限
    q_min=None, q_max=None,                # 本侧顶档量 BTC 区间(只在区间内新挂)
    reduce_ungated=True,                   # 减仓侧不受门控
    skew=0.0,                              # 每手库存对开仓侧 imb 门槛的加价
    hold_touch=True,                       # 贴盘口不因信号轻微变化撤单(只按 pull 线撤)
    latency_ms=2,                          # 决策→生效延迟(近似:延迟内到来的成交仍按旧状态处理)
    partial=True,                          # 部分成交:前方量耗尽后按成交量逐笔成交(与引擎一致)
    reduce_post=None, reduce_pull=None,    # 减仓侧 imb5 对齐门槛(None = 与开仓侧相同;仅 reduce_ungated=False 时生效)
    hold_max_s=None,                       # 持仓超过该秒数后减仓侧不再门控
    join_max=None,                         # 只在本侧顶档公开量 ≤ 此值(BTC)时新挂(抢新档队首,L07/L10)
    join_lo=None, join_hi=None,            # "确认后加入":本侧顶档量在 [lo,hi] 且 200ms 内增长(qdepl_200 < grow_thr)才新挂
    grow_thr=-0.3,
    behind_min=None,                       # 宽限后我方身后队列 < 此值(BTC)则撤单(档位脆弱)
    grace_ms=500,                          # 宽限期
    x_post=None, x_pull=None,              # 跨所领先(OKX mid − KuCoin mid,去 60s 均值,bp;对齐)门槛
    x_sample_ms=100,                       # OKX 报价采样粒度(保守:100ms)
    vanish_cancel=False,                   # 档位被撤空/吃穿后立即撤单(与引擎策略一致),延迟内到达的成交仍成交
    score_min=None,                        # 薄档存活 logistic 得分门槛(data/research/thin_level_logit_reduced.json)
    score_reduce=True,                     # 减仓侧新挂是否也要求得分
    q_pull=None,                           # 本侧顶档公开量低于此(BTC)即撤单(避免队首被吃穿前的毒性小单)
    q_pull_reduce=True,                    # 减仓侧是否也执行 q_pull
    requote_ms=100,                        # 撤单后重挂最小间隔
)


def load_day(day: str, x_sample_ms: int = 100):
    F = pq.read_table(os.path.join(FOUT, f"{day}.parquet")).to_pandas()
    tr = pq.read_table(os.path.join(KU, f"trades_{day}.parquet")).to_pandas()
    ts = F["ts"].values.astype(np.int64); n = len(ts)
    out = {"ts": ts, "n": n, "mid": F["mid"].values.astype(np.float64),
           "bb": F["bb"].values.astype(np.float64), "ba": F["ba"].values.astype(np.float64),
           "bq1": F["bq1"].values.astype(np.float64), "aq1": F["aq1"].values.astype(np.float64),
           "valid": F["valid"].values, "hour": F["hour"].values.astype(np.int64)}
    for c in ("imb5", "imb1", "ofi_1000ms", "vol_10000ms", "tint_1000ms", "cancel_imb_2000ms", "ret_5000ms", "spread_ticks", "tflow_5000ms", "qdepl_b_200ms", "qdepl_a_200ms"):
        out[c] = F[c].values.astype(np.float64)
    tts = tr["ts"].values.astype(np.int64); tside = tr["side"].values; tqty = tr["qty"].values.astype(np.float64)
    pts = np.r_[ts[0] - 1, ts[:-1]]
    j0 = np.searchsorted(tts, pts, side="right"); j1 = np.searchsorted(tts, ts, side="right")
    for side, sgn in (("b", -1), ("a", 1)):
        cum = np.r_[0.0, np.cumsum(np.where(tside == sgn, tqty, 0.0))]
        tv = cum[j1] - cum[j0]
        px = out["bb"] if side == "b" else out["ba"]
        q = out["bq1"] if side == "b" else out["aq1"]
        same = np.r_[False, px[1:] == px[:-1]]
        dq = np.r_[0.0, np.diff(q)]
        cancel = np.where(same, np.maximum(0.0, -dq - tv), 0.0)
        out[f"tv_{side}"] = tv
        out[f"adv_{side}"] = np.where(same, tv + CANCEL_BIAS * cancel, 0.0)
    # 薄档存活得分(精简 10 特征 logistic;按侧对齐)
    cp = os.path.join(ROOT, "data", "research", "thin_level_logit_reduced.json")
    out["score_b"] = np.full(n, -99.0); out["score_a"] = np.full(n, -99.0)
    if os.path.exists(cp):
        C = json.load(open(cp)); feats = C["features"]; lo = np.array(C["lo"]); hi = np.array(C["hi"]); mu = np.array(C["mu"]); sd = np.array(C["sd"]); w = np.array(C["w"])
        bbp = np.r_[out["bb"][0], out["bb"][:-1]]; bap = np.r_[out["ba"][0], out["ba"][:-1]]
        for side, sgn in (("b", 1.0), ("a", -1.0)):
            cols = []
            for c in feats:
                if c == "q":
                    v = out["bq1"] if side == "b" else out["aq1"]
                elif c == "form_toward":
                    v = ((out["bb"] > bbp) if side == "b" else (out["ba"] < bap)).astype(np.float64)
                elif c == "qdepl_b_200ms":
                    v = F["qdepl_b_200ms"].values if side == "b" else F["qdepl_a_200ms"].values
                elif c in ("ret_1000ms", "ofi_1000ms", "imb5"):
                    v = sgn * F[c].values
                else:
                    v = F[c].values
                cols.append(np.asarray(v, dtype=np.float64))
            X = np.nan_to_num(np.stack(cols, 1)); X = np.clip(X, lo, hi); Xs = (X - mu) / sd
            out[f"score_{side}"] = C["intercept"] + Xs @ w
    okx_p = os.path.join(ROOT, "data", "research", "okx", f"quotes_{day}.parquet")
    out["xlead"] = np.full(n, np.nan)
    if os.path.exists(okx_p):
        q = pq.read_table(okx_p).to_pandas()
        qts = np.maximum.accumulate(q["ts"].values.astype(np.int64)); qmid = ((q["bb"] + q["ba"]) / 2).values
        if x_sample_ms > 0:            # 保守:按采样粒度取每格最后一条
            g = qts // (x_sample_ms * US)
            last = np.r_[g[1:] != g[:-1], True]
            qts = qts[last]; qmid = qmid[last]
            qts = (qts // (x_sample_ms * US) + 1) * (x_sample_ms * US)      # 格末才可见
        k = np.searchsorted(qts, ts, side="right") - 1
        om = np.where(k >= 0, qmid[np.maximum(k, 0)], np.nan)
        x = (om - out["mid"]) / out["mid"] * 1e4
        out["xlead"] = (pd.Series(x) - pd.Series(x).rolling(3000, min_periods=100).mean()).values
    return out


def run_policy(D: dict, P: dict, log_fills: bool = True):
    n = D["n"]; ts = D["ts"]; mid = D["mid"]; bb = D["bb"]; ba = D["ba"]
    bq1 = D["bq1"]; aq1 = D["aq1"]; valid = D["valid"]
    imb5 = D["imb5"]; ofi = D["ofi_1000ms"]; vol = D["vol_10000ms"]; tint = D["tint_1000ms"]
    adv_b = D["adv_b"]; adv_a = D["adv_a"]; tv_b = D["tv_b"]; tv_a = D["tv_a"]
    clip = P["clip"]; max_pos = P["max_clips"] * clip; reb = P["rebate_bp"] / 1e4
    imb_post = P["imb_post"]; imb_pull = P["imb_pull"]; ofi_post = P["ofi_post"]; ofi_pull = P["ofi_pull"]
    vol_max = P["vol_max"]; tint_max = P["tint_max"]; q_min = P["q_min"]; q_max = P["q_max"]
    red_ung = P["reduce_ungated"]; skew = P["skew"]; lat = P["latency_ms"] * US; rq = P["requote_ms"] * US
    partial = P["partial"]; r_post = P["reduce_post"]; r_pull = P["reduce_pull"]; hold_max = P["hold_max_s"]
    q_pull = P["q_pull"]; q_pull_red = P["q_pull_reduce"]
    x_post = P["x_post"]; x_pull = P["x_pull"]; xlead = D["xlead"]
    join_max = P["join_max"]; behind_min = P["behind_min"]; grace = P["grace_ms"] * US
    vanish_cancel = P["vanish_cancel"]
    join_lo = P["join_lo"]; join_hi = P["join_hi"]; grow_thr = P["grow_thr"]; qd_b = D["qdepl_b_200ms"]; qd_a = D["qdepl_a_200ms"]
    score_min = P["score_min"]; score_red = P["score_reduce"]; sc_b = D["score_b"]; sc_a = D["score_a"]
    o_rem = {1: 0.0, -1: 0.0}; pos_since = 0
    # 订单状态:price, ahead(剩余前方量), posted_ts;None = 无
    o_px = {1: None, -1: None}; o_ahead = {1: 0.0, -1: 0.0}; o_t = {1: 0, -1: 0}; last_cancel = {1: -10**18, -1: -10**18}
    o_cxl = {1: None, -1: None}          # 撤单生效时刻(None = 未撤)
    pos = 0.0; lots = []          # FIFO [(signed_qty, price)]
    realized = 0.0; rebate = 0.0; vol_usd = 0.0
    fills = []                    # (ts, side, price, qty, pos_after, row)
    n_post = n_cancel = n_fill = 0
    eq_track = []                 # (ts, equity)
    peak = 0.0; mdd = 0.0
    last_eq_ts = ts[0]
    pos_abs_sum = 0.0; pos_sq_sum = 0.0; pos_n = 0; pos_max = 0.0

    def gate(side, i, reducing=False):
        """side=+1 买(bid) / -1 卖(ask);返回 (allow_post, allow_keep)。"""
        al = side * imb5[i]
        al_ofi = side * ofi[i]
        sk = skew * (pos / clip) * side          # 多头时提高买侧门槛、降低卖侧门槛
        post = keep = True
        ip = imb_post if (not reducing or r_post is None) else r_post
        il = imb_pull if (not reducing or r_pull is None) else r_pull
        if ip is not None and al < ip + sk:
            post = False
        if il is not None and al < il + sk:
            keep = False
        xv = xlead[i]
        if x_post is not None and xv == xv and side * xv < x_post:
            post = False
        if x_pull is not None and xv == xv and side * xv < x_pull:
            keep = False
        if ofi_post is not None and al_ofi < ofi_post:
            post = False
        if ofi_pull is not None and al_ofi < ofi_pull:
            keep = False
        if vol_max is not None and vol[i] > vol_max:
            post = False
        if tint_max is not None and tint[i] > tint_max:
            post = False
        return post, keep

    def do_fill(side, px, qty, i, tag=0):
        nonlocal pos, realized, rebate, vol_usd, n_fill, pos_max, pos_since
        rem = qty
        while rem > 1e-12 and lots and (lots[0][0] > 0) != (side > 0):
            lq, lp = lots[0]; m = min(rem, abs(lq))
            realized += (px - lp) * m if lq > 0 else (lp - px) * m
            rem -= m
            if abs(lq) - m > 1e-12:
                lots[0] = (lq - m if lq > 0 else lq + m, lp)
            else:
                lots.pop(0)
        if rem > 1e-12:
            lots.append((side * rem, px))
        prev_pos = pos
        pos += side * qty
        pos_since = i and ts[i] if (abs(prev_pos) < 1e-9 and abs(pos) > 1e-9) else (0 if abs(pos) < 1e-9 else pos_since)
        rebate += px * qty * reb
        vol_usd += px * qty
        n_fill += 1
        pos_max = max(pos_max, abs(pos))
        if log_fills:
            fills.append((ts[i], side, px, qty, pos, i, tag, (bq1[i] if side > 0 else aq1[i]), ts[i] - o_t[side]))

    for i in range(n):
        if not valid[i]:
            continue
        t = ts[i]
        # ---- 成交判定(先于本行决策:本行事件属于 (t_{i-1}, t_i])
        for side in (1, -1):
            px = o_px[side]
            if px is None:
                continue
            if t - o_t[side] < lat:          # 未生效
                continue
            if o_cxl[side] is not None and t >= o_cxl[side]:   # 撤单已生效
                o_px[side] = None; o_cxl[side] = None
                continue
            cur = bb[i] if side > 0 else ba[i]
            adv = adv_b[i] if side > 0 else adv_a[i]
            tv = tv_b[i] if side > 0 else tv_a[i]
            if cur == px:
                if partial:
                    if o_ahead[side] > 0:
                        o_ahead[side] -= adv
                        over = min(-o_ahead[side], tv) if o_ahead[side] < 0 else 0.0
                    else:
                        over = tv
                    if over > 0:
                        fq = min(o_rem[side], over)
                        do_fill(side, px, fq, i, 1); o_rem[side] -= fq
                        if o_rem[side] <= 1e-9:
                            o_px[side] = None; o_cxl[side] = None
                    if o_ahead[side] < 0:
                        o_ahead[side] = 0.0
                else:
                    o_ahead[side] -= adv
                    if o_ahead[side] <= -clip + 1e-12:
                        do_fill(side, px, clip, i); o_px[side] = None; o_cxl[side] = None
            elif (side > 0 and cur < px) or (side < 0 and cur > px):
                # 档位被吃穿/撤空:我方唯一挂单;本行若有同侧主动成交则成交
                if tv > 0:
                    fq = min(o_rem[side], tv) if partial else clip
                    do_fill(side, px, fq, i, 2); o_rem[side] -= fq
                    if not partial or o_rem[side] <= 1e-9:
                        o_px[side] = None; o_cxl[side] = None
                else:
                    o_ahead[side] = 0.0
                if vanish_cancel and o_px[side] is not None and o_cxl[side] is None:
                    o_cxl[side] = t + lat; n_cancel += 1; last_cancel[side] = t
            else:
                # 盘口上移,我方落后一档:撤单(按新盘口重挂由下方决策)
                if o_cxl[side] is None:
                    o_cxl[side] = t + lat; n_cancel += 1; last_cancel[side] = t
        # ---- 决策(每行;贴盘口不动的规则由 hold_touch 体现)
        for side in (1, -1):
            cur = bb[i] if side > 0 else ba[i]
            q_here = bq1[i] if side > 0 else aq1[i]
            reducing = (pos * side) < -1e-12                 # 本侧成交会减少 |pos|
            room = max_pos - side * pos                       # 本侧还能加多少
            post_ok, keep_ok = gate(side, i, reducing)
            if reducing and (red_ung or (hold_max is not None and pos_since and t - pos_since > hold_max * 1_000_000)):
                post_ok = keep_ok = True
            if q_pull is not None and (q_pull_red or not reducing) and q_here < q_pull:
                # 队列过薄:撤单(有 join_max 时给宽限期让新档成长;无 join_max 时也不新挂)
                if o_px[side] is None or join_max is None or t - o_t[side] >= grace:
                    keep_ok = False
                if join_max is None:
                    post_ok = False
            if join_max is not None and q_here > join_max:
                post_ok = False
            if score_min is not None and (score_red or not reducing):
                if (sc_b[i] if side > 0 else sc_a[i]) < score_min:
                    post_ok = False
            if join_lo is not None and not reducing:
                qd = qd_b[i] if side > 0 else qd_a[i]
                if not (join_lo <= q_here <= join_hi and qd < grow_thr):
                    post_ok = False
            if behind_min is not None and o_px[side] is not None and t - o_t[side] >= grace:
                behind = q_here - max(o_ahead[side], 0.0)
                if behind < behind_min:
                    keep_ok = False
            if room < clip - 1e-12:
                post_ok = False
                if not reducing:
                    keep_ok = False
            px = o_px[side]
            if px is not None:
                if not keep_ok and o_cxl[side] is None:
                    o_cxl[side] = t + lat; n_cancel += 1; last_cancel[side] = t
                continue
            # 新挂
            if not post_ok or t - last_cancel[side] < rq:
                continue
            if not reducing and q_min is not None and q_here < q_min:
                continue
            if not reducing and q_max is not None and q_here > q_max:
                continue
            o_px[side] = cur; o_ahead[side] = q_here; o_t[side] = t; n_post += 1
            o_rem[side] = min(clip, abs(pos)) if reducing and abs(pos) >= 0.001 else clip
        # ---- 权益跟踪(每 5s)
        if t - last_eq_ts >= 5_000_000:
            last_eq_ts = t
            eq = realized + rebate + sum((mid[i] - lp) * lq for lq, lp in lots)
            peak = max(peak, eq); mdd = max(mdd, peak - eq)
            eq_track.append((t, eq))
            pos_abs_sum += abs(pos); pos_sq_sum += pos * pos; pos_n += 1
    i = n - 1
    unreal = sum((mid[i] - lp) * lq for lq, lp in lots)
    hourly = {}
    if eq_track:
        prev_eq = 0.0
        for t_, e_ in eq_track:
            h = int((t_ // 1_000_000) % 86400 // 3600)
            hourly[h] = hourly.get(h, 0.0) + (e_ - prev_eq); prev_eq = e_
    net = realized + rebate + unreal
    res = dict(fills=n_fill, posts=n_post, cancels=n_cancel, vol_usd=vol_usd, realized=realized, rebate=rebate,
               unreal=unreal, net=net, net_bp=(net / vol_usd * 1e4) if vol_usd else 0.0,
               spread_bp=((realized + unreal) / vol_usd * 1e4) if vol_usd else 0.0,
               mdd=mdd, pos_end=pos, pos_max=pos_max,
               pos_mean=(pos_abs_sum / pos_n) if pos_n else 0.0, pos_std=(np.sqrt(pos_sq_sum / pos_n) if pos_n else 0.0),
               fill_rate=(n_fill / n_post) if n_post else 0.0, hourly=hourly)
    if log_fills and fills:
        fa = np.array([(f[0], f[1], f[2], f[3], f[5]) for f in fills[:]], dtype=np.float64)
        rows = fa[:, 4].astype(np.int64)
        for h in (500, 5000, 30000):
            kk = np.minimum(np.searchsorted(ts, fa[:, 0].astype(np.int64) + h * US, side="left"), n - 1)
            res[f"mk_{h}ms"] = float(np.mean(fa[:, 1] * (mid[kk] - fa[:, 2]) / fa[:, 2] * 1e4))
    res["_fills"] = fills
    res["_eq"] = eq_track
    return res


PRESETS = {
    "baseline": {},
    "imb03_partial": dict(imb_post=0.3, imb_pull=-0.3),
    "imb03_full": dict(imb_post=0.3, imb_pull=-0.3, partial=False),
    "imb03_redgate_loose": dict(imb_post=0.3, imb_pull=-0.3, reduce_ungated=False, reduce_post=0.0, reduce_pull=-0.6),
    "imb03_redgate_loose_h60": dict(imb_post=0.3, imb_pull=-0.3, reduce_ungated=False, reduce_post=0.0, reduce_pull=-0.6, hold_max_s=60),
    "imb03_redgate_loose_h20": dict(imb_post=0.3, imb_pull=-0.3, reduce_ungated=False, reduce_post=0.0, reduce_pull=-0.6, hold_max_s=20),
    "imb03_redgate_same_h60": dict(imb_post=0.3, imb_pull=-0.3, reduce_ungated=False, hold_max_s=60),
    "imb03_redgate_same_h300": dict(imb_post=0.3, imb_pull=-0.3, reduce_ungated=False, hold_max_s=300),
    "imb03_redgate_same": dict(imb_post=0.3, imb_pull=-0.3, reduce_ungated=False),
    "imb05_redgate_same_h60": dict(imb_post=0.5, imb_pull=-0.1, reduce_ungated=False, hold_max_s=60),
    "imb03_redgate_same_h60_c1": dict(imb_post=0.3, imb_pull=-0.3, reduce_ungated=False, hold_max_s=60, max_clips=1),
    "imb03_redgate_same_h60_skew": dict(imb_post=0.3, imb_pull=-0.3, reduce_ungated=False, hold_max_s=60, skew=0.3),
    "imb_gate_03": dict(imb_post=0.3, imb_pull=-0.3),
    "imb_gate_05": dict(imb_post=0.5, imb_pull=-0.2),
    "ofi_gate": dict(ofi_post=-0.3, ofi_pull=-1.5),
    "calm": dict(vol_max=0.5, tint_max=4),
    "qwin": dict(q_min=0.4, q_max=3.0),
    "calm_qwin": dict(vol_max=0.5, tint_max=4, q_min=0.4, q_max=3.0),
    "calm_qwin_ofi": dict(vol_max=0.5, tint_max=4, q_min=0.4, q_max=3.0, ofi_post=-0.3, ofi_pull=-1.5),
    "calm_qwin_imb": dict(vol_max=0.5, tint_max=4, q_min=0.4, q_max=3.0, imb_post=0.0, imb_pull=-0.5),
    "all_gates": dict(vol_max=0.5, tint_max=4, q_min=0.4, q_max=3.0, imb_post=0.0, imb_pull=-0.5, ofi_post=-0.3, ofi_pull=-1.5),
    "all_gates_skew": dict(vol_max=0.5, tint_max=4, q_min=0.4, q_max=3.0, imb_post=0.0, imb_pull=-0.5, ofi_post=-0.3, ofi_pull=-1.5, skew=0.3),
    "all_gates_redgated": dict(vol_max=0.5, tint_max=4, q_min=0.4, q_max=3.0, imb_post=0.0, imb_pull=-0.5, ofi_post=-0.3, ofi_pull=-1.5, reduce_ungated=False),
}


def summarize(name, per_day):
    tot_net = sum(r["net"] for r in per_day); tot_vol = sum(r["vol_usd"] for r in per_day)
    tot_f = sum(r["fills"] for r in per_day); reb = sum(r["rebate"] for r in per_day)
    sp = sum(r["realized"] + r["unreal"] for r in per_day)
    mk5 = np.nanmean([r.get("mk_5000ms", np.nan) for r in per_day])
    hs = [v for r in per_day for v in r.get("hourly", {}).values()]
    hpos = f"{sum(v > 0 for v in hs)}/{len(hs)} (min {min(hs):+.0f})" if hs else "-"
    return (f"| {name} | {tot_f:,} | {tot_vol:,.0f} | {sp:+.2f} ({sp / tot_vol * 1e4 if tot_vol else 0:+.3f}) | {reb:+.2f} | {tot_net:+.2f} ({tot_net / tot_vol * 1e4 if tot_vol else 0:+.3f}) | "
            + " / ".join(f"{r['net']:+.1f}" for r in per_day) + f" | {max(r['mdd'] for r in per_day):.1f} | {np.mean([r['pos_mean'] for r in per_day]):.3f} / {max(r['pos_max'] for r in per_day):.2f} | {np.mean([r['fill_rate'] for r in per_day]):.2f} | {mk5:+.3f} | {hpos} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="20251001,20260101,20260401")
    ap.add_argument("--policy", default="baseline")
    ap.add_argument("--params", default="")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--scan", default="", help="JSON: {\"base\": {...}, \"axes\": {param: [values]}} 逐参数一维扫描")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "research", "policy_grid.md"))
    ns = ap.parse_args()
    days = ns.days.split(",")
    t0 = time.time()
    data = {d: load_day(d, DEFAULT["x_sample_ms"]) for d in days}
    print(f"loaded {len(days)} days in {time.time() - t0:.0f}s", flush=True)
    names = list(PRESETS) if ns.grid else [ns.policy]
    scan = json.loads(ns.scan) if ns.scan else None
    if scan:
        PRESETS.clear()
        base = scan.get("base", {})
        PRESETS["scan_base"] = dict(base)
        for k, vals in scan["axes"].items():
            for v in vals:
                PRESETS[f"{k}={v}"] = dict(base, **{k: v})
        names = list(PRESETS); ns.grid = True
    lines = ["# 策略模拟面板(快速模拟器,训练日)", "", f"天:{', '.join(days)};单量 {DEFAULT['clip']} BTC;库存上限 {DEFAULT['max_clips']} 手;返费 {DEFAULT['rebate_bp']}bp;队列估计 ESTIMATED", "",
             "| policy | fills | vol $ | spread pnl $ (bp) | rebate $ | net $ (bp) | net by day | max DD $ | pos mean/max BTC | fill rate | mk5s bp | hours>0 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    results = {}
    for name in names:
        P = dict(DEFAULT); P.update(PRESETS.get(name, {}))
        if ns.params:
            P.update(json.loads(ns.params))
        per_day = []
        for d in days:
            r = run_policy(data[d], P)
            r.pop("_fills"); r.pop("_eq")
            per_day.append(r)
            print(f"  {name} {d}: fills {r['fills']} vol ${r['vol_usd']:,.0f} spread {r['realized'] + r['unreal']:+.2f} rebate {r['rebate']:+.2f} net {r['net']:+.2f} ({r['net_bp']:+.3f}bp) mdd {r['mdd']:.1f} pos_max {r['pos_max']:.2f} mk5 {r.get('mk_5000ms', 0):+.3f}", flush=True)
        results[name] = {"params": P, "per_day": per_day}
        lines.append(summarize(name, per_day))
    if ns.grid:
        open(ns.out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        json.dump(results, open(ns.out.replace(".md", ".json"), "w"), indent=1, default=float)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
