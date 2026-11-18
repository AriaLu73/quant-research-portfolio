"""Part B 回放(Step 13):P2 字面设定 —— 连续不重叠的 300 s 段,每段 X_0 = Y_0 = 0,段末按 L 用市价单清算,段间不延续库存。
每步(t_k):
  1. 状态:y(张)、点差桶 s(t_k 盘口的 卖一−买一 经 edges 分桶)、g(P1 的 g3);缺口 / 无状态 → 冻结(不挂、不吃,库存延续)。
  2. 策略给 (e, L⁺, L⁻):先市价单 e(张):买 e>0 以 t_k 卖一成交、卖以买一成交,加 taker 费 f·|e|(tick/张,EC-30)(附录第 3 条 P2 字面口径,延迟 L 在 Step 15 加);
     再挂单:ask = mid + L⁺、bid = mid − L⁻(to_quotes 取整与有效性规则),成交按 P1 规则(与 Part A 的 sim_paper 相同:V_L 取 t_k 盘口、逐笔封顶 V_LO)。
  3. 段末:Y 以 t_T 盘口的买一 / 卖一清算并付 taker 费(P2 字面);另按 20 档沿深度算第二口径(附录第 3 条)。
记录  每段:X_T(tick×张 → USDT)、成交笔数 / 成交额、市价单笔数 / 成交额 / 费用、max|Y|、段内持仓段时长、段末清算量与两口径成本。
基准  WoMO(ē=0 的目录)、αc(双侧贴盘口,V_LO)、αr(每侧随机 贴盘口 / 改善 1 tick),P1 原版用 Part A 的结果作对照(任务书 Table 9)。
"""
import datetime as dt
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "a"))
sys.path.insert(0, os.path.join(REPRO, "data"))
import arrivals as AR          # noqa: E402
import bellman as BM           # noqa: E402
import events as EV            # noqa: E402
import ladder_store as LS      # noqa: E402
import sim_paper as SP         # noqa: E402

NS = 1_000_000_000


class P2Policy:
    """QVI 目录查表(鞅版;Δ̂ 漂移版用 q.decide,慢,只在 use_drift=True 时用)。"""

    def __init__(self, name, q, edges, use_drift=False):
        self.name, self.q, self.edges, self.use_drift = name, q, np.asarray(edges), use_drift

    def spread_state(self, spread_ticks):
        return int(np.searchsorted(self.edges, spread_ticks, side="left"))

    def act(self, k_in, y, s, g, delta_hat):
        q = self.q
        if self.use_drift and delta_hat:
            Lp, Lm, e = q.decide(k_in, y, s, g, delta_hat)
            return e, Lp, Lm
        j = int(np.clip(np.round((y + q.y[-1]) / q.dy), 0, q.Y - 1))
        e = int(q.pol["e"][k_in, j, s, g]) * q.dy
        if e:
            j = int(np.clip(np.round((y + e + q.y[-1]) / q.dy), 0, q.Y - 1))
        return e, float(q.L[q.pol["Lp"][k_in, j, s, g]]), float(q.L[q.pol["Lm"][k_in, j, s, g]])


class TouchPolicy:
    """αc:双侧贴盘口;αr:每侧随机贴盘口或改善 1 tick(点差 > 1 tick 时)。"""

    def __init__(self, name, random=False, seed=0):
        self.name, self.random, self.rng = name, random, np.random.default_rng(seed)

    def act_ticks(self, bb, ba):
        if not self.random:
            return 0, bb, ba
        bt = bb + (1 if (ba - bb > 1 and self.rng.random() < 0.5) else 0)
        at = ba - (1 if (ba - bb > 1 and self.rng.random() < 0.5) else 0)
        return 0, bt, at


def simulate_day(sym, day, dt_ms, policies, g: AR.GState, V_LO, tick, mult, fee_take_ticks, seg_s=300, cap_mode="per_mo", rebate_ticks=0.0, log_fills=False):
    """rebate_ticks(Step 15):每张挂单成交另记 +rebate(tick/张)的返佣收入,计入 X 并单列 rebate 合计。"""
    lads = SP.load_day(sym, day)
    d0, d1 = SP.day_bounds(day)
    fr = EV.build(lads, dt_ms, d0, d1)
    N = len(fr)
    s_seq = g.states(fr)
    bnd_lad = np.concatenate([d["bnd_lad"] for d in lads])
    sw_ts = np.concatenate([d["sw_ts"] for d in lads]); sw_side = np.concatenate([d["sw_side"] for d in lads]).astype(int)
    sw_vol = np.concatenate([d["sw_vol"] for d in lads])
    lo_idx = np.searchsorted(sw_ts, fr.t0); hi_idx = np.searchsorted(sw_ts, fr.t0 + dt_ms * 1_000_000)
    mids = fr.mid2.astype(float) / 2.0
    # 缺口(mid2 = −1)时的回退中价:最近一个有效中价(前向填充;开头用首个有效值)。修正 11-07:原来直接用 mids[k] = −0.5,
    # 段末落在缺口里时 yT·mid ≈ 0,段 PnL 只剩现金腿(10-02 一段空头 136 张被记成 +1,175 USDT)。
    ok_m = fr.mid2 > 0
    if ok_m.any():
        idx = np.where(ok_m, np.arange(len(mids)), -1); idx = np.maximum.accumulate(idx)
        first = int(np.argmax(ok_m)); idx = np.where(idx < 0, first, idx)
        mid_ff = mids[idx]
    else:
        mid_ff = mids
    n_seg = int(round(seg_s * 1000 / dt_ms))
    unit = tick * mult
    P = len(policies)
    X = np.zeros(P); Y = np.zeros(P)
    segs = {p.name: [] for p in policies}
    fill_log = {p.name: [] for p in policies}                  # log_fills:(k, qp, qm, ask_tick, bid_tick, e_mo)
    cur = {p.name: dict(fills=0, notional=0.0, n_mo=0, mo_notional=0.0, mo_fee=0.0, maxY=0.0, hold=[], run=0, frozen=0) for p in policies}
    for k in range(N):
        k_in = k % n_seg
        active = (not fr.gap[k]) and s_seq[k] >= 0 and fr.bnd_index[k] >= 0
        lad = bnd_lad[fr.bnd_index[k]] if fr.bnd_index[k] >= 0 else None
        bb = int(lad[0, 0, 0]) if lad is not None and lad[0, 0, 1] > 0 else None
        ba = int(lad[1, 0, 0]) if lad is not None and lad[1, 0, 1] > 0 else None
        if bb is None or ba is None:
            active = False
        mid2 = int(fr.mid2[k]); spread = (ba - bb) if active else None
        delta_hat = (mids[k] - mids[k - 5]) / 5.0 if k >= 5 and not fr.gap[k - 5:k].any() else 0.0
        sl = slice(lo_idx[k], hi_idx[k]); buys = sw_vol[sl][sw_side[sl] == 0]; sells = sw_vol[sl][sw_side[sl] == 1]
        for j, p in enumerate(policies):
            c = cur[p.name]
            if active:
                if isinstance(p, P2Policy):
                    s = p.spread_state(spread)
                    e, Lp, Lm = p.act(k_in, Y[j], s, int(s_seq[k]), delta_hat)
                    if e:
                        px = ba if e > 0 else bb
                        X[j] -= e * px + fee_take_ticks * abs(e)
                        Y[j] += e
                        c["n_mo"] += 1; c["mo_notional"] += abs(e) * px * unit; c["mo_fee"] += fee_take_ticks * abs(e) * unit
                    bt, at, flag = BM.to_quotes(mid2, Lp, Lm)
                else:
                    e, bt, at = p.act_ticks(bb, ba)
                qp = qm = 0
                if len(buys):
                    VL, _ = SP._vl(lad[1], 1, at, LS.K)
                    f = np.minimum(np.maximum(buys - VL, 0), V_LO); qp = int(f.sum()) if cap_mode == "per_mo" else int(min(f.sum(), V_LO))
                if len(sells):
                    VL, _ = SP._vl(lad[0], 0, bt, LS.K)
                    f = np.minimum(np.maximum(sells - VL, 0), V_LO); qm = int(f.sum()) if cap_mode == "per_mo" else int(min(f.sum(), V_LO))
                X[j] += at * qp - bt * qm + rebate_ticks * (qp + qm)
                if log_fills and (qp or qm or e):
                    fill_log[p.name].append((k, qp, qm, at, bt, e))
                Y[j] += qm - qp
                c["fills"] += int(qp > 0) + int(qm > 0); c["notional"] += (qp * at + qm * bt) * unit; c["rebate"] = c.get("rebate", 0.0) + rebate_ticks * (qp + qm) * unit
            else:
                c["frozen"] += 1
            c["maxY"] = max(c["maxY"], abs(Y[j]))
            if Y[j] != 0:
                c["run"] += 1
            elif c["run"]:
                c["hold"].append(c["run"]); c["run"] = 0
            # 段末清算(该段最后一步之后的边界 t_{k+1})
            if k_in == n_seg - 1 or k == N - 1:
                nb = fr.bnd_index[k + 1] if k + 1 < N else -1
                lad_T = bnd_lad[nb] if nb >= 0 else lad
                yT = Y[j]
                liq_touch = liq_walk = 0.0; short = 0; ok_T = lad_T is not None and lad_T[0, 0, 1] > 0 and lad_T[1, 0, 1] > 0
                if yT != 0 and ok_T:
                    bbT, baT = int(lad_T[0, 0, 0]), int(lad_T[1, 0, 0])
                    px = bbT if yT > 0 else baT
                    liq_touch = yT * px - fee_take_ticks * abs(yT)
                    Sbar, _, short = SP.liquidation_price(np.stack([np.pad(lad_T[0], ((0, LS.KD - LS.K), (0, 0))), np.pad(lad_T[1], ((0, LS.KD - LS.K), (0, 0)))]), yT, (bbT + baT) / 2)
                    liq_walk = yT * Sbar - fee_take_ticks * abs(yT)
                elif yT != 0:
                    liq_touch = liq_walk = yT * mid_ff[k]        # 盘口不可用:按最近有效中价(记 book_ok=False)
                if c["run"]:
                    c["hold"].append(c["run"]); c["run"] = 0
                segs[p.name].append(dict(k_end=k, X_T_usdt=(X[j] + liq_touch) * unit, X_T_walk_usdt=(X[j] + liq_walk) * unit, Y_T=float(yT),
                                         liq_cost_touch_usdt=float((yT * mid_ff[k] - liq_touch) * unit) if yT else 0.0, liq_short=int(short),
                                         fills=c["fills"], notional=c["notional"], n_mo=c["n_mo"], mo_notional=c["mo_notional"], mo_fee=c["mo_fee"],
                                         maxY=c["maxY"], hold_s=[h * dt_ms / 1000.0 for h in c["hold"]], frozen=c["frozen"], book_ok=bool(ok_T), rebate=c.get("rebate", 0.0)))
                X[j] = 0.0; Y[j] = 0.0
                cur[p.name] = dict(fills=0, notional=0.0, n_mo=0, mo_notional=0.0, mo_fee=0.0, maxY=0.0, hold=[], run=0, frozen=0)
    if log_fills:
        return segs, fr, fill_log
    return segs, fr


def summarize(segs, dt_ms):
    """按 P2 Table 5 / Section 4:m(X_T)、σ(X_T)、IR;加成交额、市价单、max|Y|、段末清算量、持仓段。"""
    xs = np.array([s["X_T_usdt"] for s in segs]); xw = np.array([s["X_T_walk_usdt"] for s in segs])
    hold = np.concatenate([np.asarray(s["hold_s"]) for s in segs]) if segs else np.zeros(0)
    yT = np.abs([s["Y_T"] for s in segs])
    return dict(n_seg=len(segs), m=float(xs.mean()), sd=float(xs.std(ddof=1)) if len(xs) > 1 else 0.0, IR=float(xs.mean() / xs.std(ddof=1)) if len(xs) > 1 and xs.std() > 0 else 0.0,
                m_walk=float(xw.mean()), fills=float(np.mean([s["fills"] for s in segs])), notional=float(np.sum([s["notional"] for s in segs])),
                n_mo=float(np.mean([s["n_mo"] for s in segs])), mo_notional=float(np.sum([s["mo_notional"] for s in segs])), mo_fee=float(np.sum([s["mo_fee"] for s in segs])),
                maxY_mean=float(np.mean([s["maxY"] for s in segs])), maxY_max=float(np.max([s["maxY"] for s in segs])),
                YT_abs_mean=float(yT.mean()), YT_zero_share=float((yT == 0).mean()), YT_abs_p90=float(np.percentile(yT, 90)),
                hold_n=int(len(hold)), hold_p50_s=float(np.median(hold)) if len(hold) else 0.0, hold_max_s=float(hold.max()) if len(hold) else 0.0,
                hold_gt_300s=int((hold > 300).sum()), frozen_steps=int(np.sum([s["frozen"] for s in segs])),
                pnl_sum=float(xs.sum()), **clean_stats(segs))


def clean_stats(segs):
    """UR-04 敏感性:不含缺口段(段内有冻结区间或段末盘口不可用)的 m / σ / IR。"""
    cl = [s for s in segs if s["frozen"] == 0 and s["book_ok"]]
    xs = np.array([s["X_T_usdt"] for s in cl])
    sd = float(xs.std(ddof=1)) if len(xs) > 1 else 0.0
    return dict(n_seg_clean=len(cl), n_seg_gap=len(segs) - len(cl), m_clean=float(xs.mean()) if len(xs) else 0.0, sd_clean=sd,
                IR_clean=float(xs.mean() / sd) if sd > 0 else 0.0, pnl_sum_clean=float(xs.sum()) if len(xs) else 0.0)
