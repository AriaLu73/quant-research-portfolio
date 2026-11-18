"""Step 8–9 —— P1 §3.2 的论文忠实回测(脚注 5/6 队首假设,无费率、无延迟)与终端清算(Table 2 vs Table 3)。

每个区间 k(决策时刻 t_k):
  1. 状态 s_k = g(e_{t_k})(Step 4 的 Γ 推进);缺口 / burn-in 区间冻结报价、不记成交、库存延续(附录第 7 条)。
  2. 查 Catalog[k, s_k],按库存 I_k 算 (L⁺, L⁻)(Eq. 22;非鞅版加 Eq. 31/44 的 Δ̂ 项,Δ̂ = (S_k − S_{k−5})/5,Eq. 49,历史不足 5 个中价时取 0:EC-26)。
  3. 价格有效性规则 + 取整(EC-20)→ (bid_tick, ask_tick)。
  4. 成交:区间内真实 MO 流,买 MO 打我方卖单:fill = min(max(V_MO − V_L, 0), V_LO),V_L = t_k 盘口上严格优于我方价位的可见量(EC-11 at_t0),
     逐笔封顶(EC-13);我方价位深于第 20 档时 V_L 取 20 档总量(下界)并计数(EC-27)。卖 MO 对称。
  5. 现金 / 库存(Eq. 11–12):W += a·Q̃⁺ − b·Q̃⁻(以 tick×张 记账,换算 USDT = × TICK × mult),I += Q̃⁻ − Q̃⁺。
终端:J_T = W_T + S_T I_T − λ I_T²(Eq. 10;λ 按 EC-21);PnL_T = W_T + S̄_T I_T,S̄_T 用日末 200 档深快照沿深度清算(Step 9)。
固定档位基准 Level i(EC-25):ask = ⌊mid⌋ + i(中价上方第 i 个 tick),bid = ⌈mid⌉ − i;与最优策略共用同一成交规则。
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
sys.path.insert(0, os.path.join(REPRO, "data"))
import arrivals as AR          # noqa: E402
import bellman as BM           # noqa: E402
import events as EV            # noqa: E402
import ladder_store as LS      # noqa: E402

NS = 1_000_000_000


def day_bounds(day):
    t = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    return t, t + 86400 * NS


def load_day(sym, day):
    files = sorted(glob.glob(os.path.join(REPRO, "data", "step01", sym, f"{day}_*.npz")))
    return [LS.load(p) for p in files]


def _vl(lad_side, side, tick, k_levels, include_own=False):
    """side 侧 ladder (K,2) 上严格优于 tick 的可见张数;返回 (V_L, beyond_flag)。include_own:再加同价位已有张数(Step 14 (c) 口径)。"""
    t = lad_side[:, 0].astype(np.int64)
    q = lad_side[:, 1].astype(np.int64)
    m = q > 0
    t, q = t[m], q[m]
    if len(t) == 0:
        return 0, False
    better = ((t < tick) if side == 1 else (t > tick)) | ((t == tick) if include_own else False)
    beyond = bool(better.all()) and len(t) >= k_levels          # 我方比第 20 档还深:V_L 只知道下界
    return int(q[better].sum()), beyond


class Policy:
    """报价策略接口:quote(k, s, I, mid2, delta_hat) -> (bid_tick, ask_tick, flag)。"""

    def __init__(self, name):
        self.name = name

    def quote(self, k, s, I, mid2, delta_hat):
        raise NotImplementedError


class CatalogPolicy(Policy):
    def __init__(self, name, cat: BM.Catalog, g: AR.GState, use_drift=False):
        super().__init__(name)
        self.cat, self.g, self.use_drift = cat, g, use_drift

    def quote(self, k, s, I, mid2, delta_hat):
        Lp, Lm = BM.optimal_L(self.cat, k, s, I, delta_hat if self.use_drift else 0.0)
        bt, at, flag = BM.to_quotes(mid2, Lp, Lm)
        return bt, at, flag, Lp, Lm


class FixedLevelPolicy(Policy):
    def __init__(self, i):
        super().__init__(f"Level{i}")
        self.i = i

    def quote(self, k, s, I, mid2, delta_hat):
        mid = mid2 / 2.0
        return int(np.ceil(mid)) - self.i, int(np.floor(mid)) + self.i, 0, np.nan, np.nan


def simulate(sym, day, dt_ms, policies, g: AR.GState, V_LO, lam_usdt, tick, mult, cap_mode="per_mo", need_state=True, vl_queue=False):
    """一天内同时回放多个策略(共用事件流与盘口,库存各自独立)。返回每个策略的 DayResult 字典。"""
    lads = load_day(sym, day)
    d0, d1 = day_bounds(day)
    fr = EV.build(lads, dt_ms, d0, d1)
    N = len(fr)
    s_seq = g.states(fr) if need_state else np.zeros(N, np.int64)
    bnd_lad = np.concatenate([d["bnd_lad"] for d in lads])
    sw_ts = np.concatenate([d["sw_ts"] for d in lads])
    sw_side = np.concatenate([d["sw_side"] for d in lads]).astype(int)
    sw_vol = np.concatenate([d["sw_vol"] for d in lads])
    deep_ts = np.concatenate([d["deep_ts"] for d in lads])
    deep_lad = np.concatenate([d["deep_lad"] for d in lads])
    dt_ns = dt_ms * 1_000_000
    lo_idx = np.searchsorted(sw_ts, fr.t0)
    hi_idx = np.searchsorted(sw_ts, fr.t0 + dt_ns)
    P = len(policies)
    W = np.zeros(P)
    I = np.zeros(P)
    rec = {p.name: dict(W=np.zeros(N + 1), I=np.zeros(N + 1), bid=np.full(N, -1, np.int64), ask=np.full(N, -1, np.int64), flag=np.zeros(N, np.int8),
                        qp=np.zeros(N, np.int64), qm=np.zeros(N, np.int64), Lp=np.full(N, np.nan), Lm=np.full(N, np.nan),
                        frozen=np.zeros(N, bool), beyond=np.zeros(N, np.int8)) for p in policies}
    mids = fr.mid2.astype(float) / 2.0
    for k in range(N):
        active = (not fr.gap[k]) and (s_seq[k] >= 0 or not need_state)
        if not active:
            for p in policies:
                rec[p.name]["frozen"][k] = True
                rec[p.name]["W"][k + 1], rec[p.name]["I"][k + 1] = W[policies.index(p)], I[policies.index(p)]
            continue
        mid2 = int(fr.mid2[k])
        # Eq. (49):最近 5 个中价增量的均值;历史不足或含缺口 → 0(EC-26)
        delta_hat = 0.0
        if k >= 5 and not fr.gap[k - 5:k].any():
            delta_hat = (mids[k] - mids[k - 5]) / 5.0
        sl = slice(lo_idx[k], hi_idx[k])
        buys = sw_vol[sl][sw_side[sl] == 0]
        sells = sw_vol[sl][sw_side[sl] == 1]
        lad = bnd_lad[fr.bnd_index[k]]
        for j, p in enumerate(policies):
            bt, at, flag, Lp, Lm = p.quote(k, int(s_seq[k]), I[j], mid2, delta_hat)
            r = rec[p.name]
            r["bid"][k], r["ask"][k], r["flag"][k], r["Lp"][k], r["Lm"][k] = bt, at, flag, Lp, Lm
            qp = qm = 0
            if len(buys):
                VL, beyond = _vl(lad[1], 1, at, LS.K, vl_queue)
                fills = np.minimum(np.maximum(buys - VL, 0), V_LO)
                qp = int(fills.sum()) if cap_mode == "per_mo" else int(min(fills.sum(), V_LO))
                r["beyond"][k] |= 1 if beyond else 0
            if len(sells):
                VL, beyond = _vl(lad[0], 0, bt, LS.K, vl_queue)
                fills = np.minimum(np.maximum(sells - VL, 0), V_LO)
                qm = int(fills.sum()) if cap_mode == "per_mo" else int(min(fills.sum(), V_LO))
                r["beyond"][k] |= 2 if beyond else 0
            W[j] += at * qp - bt * qm
            I[j] += qm - qp
            r["qp"][k], r["qm"][k] = qp, qm
            r["W"][k + 1], r["I"][k + 1] = W[j], I[j]
    # 终端(Step 9)
    S_T = mids[-1] if fr.mid2[-1] > 0 else mids[fr.mid2 > 0][-1]
    j_last = int(np.searchsorted(deep_ts, d1, side="right")) - 1
    deep = deep_lad[j_last]
    out = {}
    unit = tick * mult                                           # tick×张 → USDT
    lam_tick = lam_usdt / unit
    for j, p in enumerate(policies):
        r = rec[p.name]
        IT, WT = I[j], W[j]
        Sbar, cost, short = liquidation_price(deep, IT, S_T)
        J = WT + S_T * IT - lam_tick * IT * IT
        PnL = WT + Sbar * IT
        out[p.name] = dict(sym=sym, day=day, dt_ms=dt_ms, policy=p.name, W_T_usdt=WT * unit, I_T=IT, S_T_tick=S_T,
                           J_T_usdt=J * unit, PnL_T_usdt=PnL * unit, liq_cost_usdt=cost * unit, liq_depth_short=short,
                           n_fills=int((r["qp"] > 0).sum() + (r["qm"] > 0).sum()), vol_contracts=int(r["qp"].sum() + r["qm"].sum()),
                           notional_usdt=float(((r["qp"] * r["ask"].clip(0) + r["qm"] * r["bid"].clip(0)) * unit).sum()),
                           frozen_share=float(r["frozen"].mean()), flag_share=float((r["flag"] > 0).mean()), beyond_share=float((r["beyond"] > 0).mean()),
                           max_abs_I=float(np.abs(r["I"]).max()), std_I=float(r["I"].std()),
                           mean_Lp=float(np.nanmean(r["Lp"])) if np.isfinite(r["Lp"]).any() else None,
                           mean_Lm=float(np.nanmean(r["Lm"])) if np.isfinite(r["Lm"]).any() else None, series=r)
    return out, fr


def liquidation_price(deep, IT, S_T):
    """沿日末深快照清算 I_T:多头卖给 bid 侧、空头从 ask 侧买回。返回 (平均价 tick, 清算成本 tick×张 = (S_T − S̄)·I_T, 深度不足张数)。"""
    if IT == 0:
        return S_T, 0.0, 0
    side = 0 if IT > 0 else 1
    lad = deep[side]
    q = np.abs(IT)
    got, left = 0.0, q
    for t, v in lad:
        if v <= 0 or left <= 0:
            continue
        take = min(left, v)
        got += take * t
        left -= take
    filled = q - left
    if filled == 0:
        return S_T, 0.0, int(left)
    Sbar = got / filled
    if left > 0:                                                 # 深度不足:剩余按最后一档价(保守)并记录
        last = lad[lad[:, 1] > 0][-1, 0]
        Sbar = (got + left * last) / q
    cost = (S_T - Sbar) * IT
    return float(Sbar), float(cost), int(left)


def summarize_series(r, dt_ms):
    """持仓段时长分布(|I| > 0 的连续区间)、成交额等(用户:笔数旁边要有成交额;持仓段 > 300 s 计数)。"""
    I = r["I"]
    nz = I != 0
    segs = []
    start = None
    for k, z in enumerate(nz):
        if z and start is None:
            start = k
        if not z and start is not None:
            segs.append(k - start)
            start = None
    if start is not None:
        segs.append(len(nz) - start)
    segs = np.asarray(segs) * dt_ms / 1000.0
    return dict(n_hold_segments=int(len(segs)), hold_p50_s=float(np.median(segs)) if len(segs) else 0.0,
                hold_max_s=float(segs.max()) if len(segs) else 0.0, hold_gt_300s=int((segs > 300).sum()))
