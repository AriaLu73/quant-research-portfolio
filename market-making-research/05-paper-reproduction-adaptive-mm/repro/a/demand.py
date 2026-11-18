"""Step 2 —— P1 Eq. (4)–(5)、§3.1.2:每个区间的随机需求参数 (c^±, p^±)。

模型   Q^±_{t_{k+1}} = 1^±_{t_{k+1}} · c^± · (p^± − L^±_{t_k}),L^± = 报价距中价的距离。
坐标(EC-10)  距离 L 以 tick 计:ask 侧 L = P − S,bid 侧 L = S − P,S = mid2/2。回归 Q_ℓ = a + b·L_ℓ,b < 0 才有效;
            c = −b(张 / tick),p = a / c(tick)。换算回价格坐标:P1 的 "slope" 对 P 的绝对值 = c,"intercept/slope" = p ± S。
虚拟单成交(§3.1.2,脚注 5 队首假设,Part A 原样执行)  单笔 MO:min(max(V_MO − V_L, 0), V_LO);Q_ℓ = Σ_MO(区间内所有同向 MO)。
论文留空的四项,全部做成参数:
  (a) weight_fn   回归权重。"reach_freq"(默认,EC-09):w_ℓ = 训练窗内 Q_ℓ > 0 的区间占比(按侧、按 L 估计,随 L 递减,由数据定);
                  "inv_dist":1/L;"uniform"。
  (b) V_LO        张数,来自 Step 0 标定(reports/step00/vlo.md),×{0.5,1,2} 敏感性。
  (c) vl_mode     "at_t0"(默认,EC-11:论文行文 "at time t_ℓ … the volume of existing ask LOs … is V_L" 取下单时刻一次);
                  "per_mo":每笔 MO 到达前的盘口(ladder_store 的 sw_lad)。
  (d) cap_mode    "per_mo"(默认,字面:每笔 MO 各自以 V_LO 封顶,整区间可超过 V_LO);"interval":整区间再以 V_LO 封顶(敏感性)。
价位网格(EC-08)  grid_mode="levels"(默认):该侧由优到劣的前 K(=20)个占用价位本身(论文用 20 档 TotalView 盘口,"all price level P_ℓ" 即这些档位;
                 虚拟单放在占用价位上,脚注 5 的队列优先权才有意义);
                 grid_mode="ticks"(敏感性):从中价外第一个 tick 到第 K 个占用价位逐 tick,上限 MAX_LEVELS tick。
                 两种模式下 V_L 都只用 20 档内的可见量,不外推。
只在该侧 1^± = 1 的区间估计(任务书 Step 2 末条;Eq. 8 的条件口径)。
"""
import os
import sys
from dataclasses import dataclass, field

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
import ladder_store as LS      # noqa: E402

MAX_LEVELS = 400
NS_MS = 1_000_000


@dataclass
class DemandParams:
    dt_ms: int
    c: np.ndarray            # [N, 2]  列 0 = + (ask 侧 / 买 MO), 列 1 = − (bid 侧 / 卖 MO)
    p: np.ndarray            # [N, 2]  tick
    valid: np.ndarray        # [N, 2]  bool:该侧 1^±=1 且回归有效(b < 0、≥ 2 个价位、有 MO 触及)
    reason: np.ndarray       # [N, 2]  int8:0 ok 1 no_mo 2 gap 3 no_ladder 4 slope_nonneg 5 too_few_levels 6 all_zero 7 p_out_of_range
    n_levels: np.ndarray     # [N, 2]
    q_sum: np.ndarray        # [N, 2]  Σ_ℓ Q_ℓ(诊断)
    cfg: dict = field(default_factory=dict)


def _ladder_cum(lad, side):
    """lad[K,2] (tick, qty) 由优到劣 → (ticks[], cum_before[]):cum_before[i] = 严格优于 ticks[i] 的累计张数。"""
    m = lad[:, 1] > 0
    t, q = lad[m, 0].astype(np.int64), lad[m, 1].astype(np.int64)
    cum = np.concatenate([[0], np.cumsum(q)[:-1]]) if len(q) else np.zeros(0, np.int64)
    return t, cum


def _vl_on_grid(grid, ticks, cum, side, include_own=False):
    """网格上每个价位 P 的 V_L = 严格优于 P 的可见张数(ask 侧 tick < P;bid 侧 tick > P)。
    include_own=True(Step 14 第 (c) 口径,"价格严格优于 + 同价位 L3 前方量"):再加上 P 价位本身已有的张数(新单排在它们后面)。"""
    if len(ticks) == 0:
        return np.zeros(len(grid), np.int64)
    sd = "right" if include_own else "left"
    if side == 1:                                # ask:ticks 升序
        idx = np.searchsorted(ticks, grid, side=sd)          # 个数 of ticks < P(或 ≤ P)
    else:                                        # bid:ticks 降序 → 用负数
        idx = np.searchsorted(-ticks, -grid, side=sd)        # 个数 of ticks > P(或 ≥ P)
    total = np.concatenate([cum, [cum[-1] + 0]]) if len(cum) else np.zeros(1, np.int64)
    # cum[i] = 严格优于 ticks[i] 的量;优于 P 的量 = 前 idx 个档位之和 = cum[idx] (idx < len) 或 全部
    allq = int(cum[-1]) if len(cum) else 0
    full = np.zeros(len(ticks) + 1, np.int64)
    if len(ticks):
        full[:len(ticks)] = cum
        full[len(ticks)] = cum[-1] + 0
    return full[idx] if len(ticks) else np.zeros(len(grid), np.int64)


def _level_grid(mid2, ticks, side):
    """从中价外第一个 tick 到第 K 个占用价位,逐 tick。"""
    if len(ticks) == 0:
        return None
    if side == 1:
        first = mid2 // 2 + 1
        last = int(ticks[-1])
        if last < first:
            return None
        g = np.arange(first, min(last, first + MAX_LEVELS - 1) + 1, dtype=np.int64)
    else:
        first = (mid2 + 1) // 2 - 1
        last = int(ticks[-1])
        if last > first:
            return None
        g = np.arange(first, max(last, first - MAX_LEVELS + 1) - 1, -1, dtype=np.int64)
    return g


def _fit(Lg, Q, w):
    """加权最小二乘 Q = a + b L。返回 (a, b) 或 None。"""
    W = w.sum()
    if W <= 0 or len(Lg) < 2:
        return None
    Lm, Qm = (w * Lg).sum() / W, (w * Q).sum() / W
    sxx = (w * (Lg - Lm) ** 2).sum()
    if sxx <= 0:
        return None
    b = (w * (Lg - Lm) * (Q - Qm)).sum() / sxx
    return Qm - b * Lm, b


class DemandEstimator:
    def __init__(self, V_LO, weight_fn="reach_freq", vl_mode="at_t0", cap_mode="per_mo", reach=None, grid_mode="levels", reach_min=0.01):
        self.V_LO, self.weight_fn, self.vl_mode, self.cap_mode, self.grid_mode = int(V_LO), weight_fn, vl_mode, cap_mode, grid_mode
        # EC-22:levels 模式下只用 reach 频率 ≥ reach_min 的前若干档(第一遍 reach 未知时用全部 K 档);
        # 否则离中价百分之几的远档(L ~ 1e5 tick)以 L² 的杠杆压过近档,斜率抵消到 ~0、p 爆到 1e30。
        self.reach_min = reach_min
        self.n_use = (None, None)
        if reach is not None and grid_mode == "levels":
            self.n_use = tuple(max(2, int(np.argmax(np.asarray(reach[s])[1:LS.K + 1] < reach_min)) if np.any(np.asarray(reach[s])[1:LS.K + 1] < reach_min) else LS.K) for s in (0, 1))
        self.reach = reach          # reach_freq 权重表:dict side → np.ndarray(按 L 的 tick 距离索引,长度 MAX_LEVELS+1)
        self.reach_acc = [np.zeros(MAX_LEVELS + 2), np.zeros(MAX_LEVELS + 2)]   # 分子 (Q>0 计数)
        self.reach_cnt = [np.zeros(MAX_LEVELS + 2), np.zeros(MAX_LEVELS + 2)]   # 分母 (出现在网格上的次数)

    # ---- 单个区间、单侧的需求曲线
    def curve(self, lad_t0, mid2, sweeps_vol, sweeps_lad, side):
        """返回 (L_grid[], Q[]) 或 None。sweeps_vol:区间内该方向 MO 张数;sweeps_lad:对应的到达前 ladder(per_mo 用)。"""
        ticks0, cum0 = _ladder_cum(lad_t0[side], side)
        if self.grid_mode == "levels":
            grid = ticks0.copy()                                     # 占用价位本身(由优到劣),rank = 1..len
            if self.n_use[side] is not None:
                grid = grid[:self.n_use[side]]
            if len(grid) == 0 or (side == 1 and grid[0] * 2 <= mid2) or (side == 0 and grid[0] * 2 >= mid2):
                return None                                          # 盘口与中价不一致(交叉/空)
        else:
            grid = _level_grid(mid2, ticks0, side)
            if grid is None:
                return None
        Q = np.zeros(len(grid), np.int64)
        own = self.vl_mode == "queue"                           # Step 14.4(c)/14.5:V_L 含同价位前方量
        if self.vl_mode in ("at_t0", "queue"):
            VL = _vl_on_grid(grid, ticks0, cum0, side, include_own=own)
            for v in sweeps_vol:
                Q += np.minimum(np.maximum(int(v) - VL, 0), self.V_LO)
        else:
            for v, lad in zip(sweeps_vol, sweeps_lad):
                t, c = _ladder_cum(lad, side)
                VL = _vl_on_grid(grid, t, c, side) if len(t) else np.zeros(len(grid), np.int64)
                Q += np.minimum(np.maximum(int(v) - VL, 0), self.V_LO)
        if self.cap_mode == "interval":
            Q = np.minimum(Q, self.V_LO)
        Lg = (grid * 2 - mid2) / 2.0 if side == 1 else (mid2 - grid * 2) / 2.0     # 距中价 tick 数(可为 .5)
        return Lg, Q

    def _weights(self, Lg, Q, side):
        if self.weight_fn == "uniform":
            return np.ones(len(Lg))
        if self.weight_fn == "inv_dist":
            return 1.0 / np.maximum(Lg, 0.5)
        # reach_freq:levels 模式按档位序号 1..K 查表,ticks 模式按 L 的整数 tick 查表;表未给时先用 1/L 占位并累计计数(第一遍),第二遍用表
        if self.grid_mode == "levels":
            idx = np.arange(1, len(Lg) + 1)
        else:
            idx = np.minimum(np.ceil(Lg).astype(int), MAX_LEVELS + 1)
        if self.reach is None:
            self.reach_acc[side][idx] += (Q > 0)
            self.reach_cnt[side][idx] += 1
            return 1.0 / np.maximum(Lg, 0.5)
        w = self.reach[side][idx]
        return np.where(w > 0, w, 1e-6)

    def reach_table(self):
        return [np.where(self.reach_cnt[s] > 0, self.reach_acc[s] / np.maximum(self.reach_cnt[s], 1), 0.0) for s in (0, 1)]

    # ---- 整个 frame
    def estimate(self, frame, ladders):
        bnd_lad = np.concatenate([d["bnd_lad"] for d in ladders if len(d["bnd_lad"])])
        sw_ts = np.concatenate([d["sw_ts"] for d in ladders if len(d["sw_ts"])]) if any(len(d["sw_ts"]) for d in ladders) else np.zeros(0, np.int64)
        sw_side = np.concatenate([d["sw_side"] for d in ladders if len(d["sw_side"])]).astype(int) if len(sw_ts) else np.zeros(0, int)
        sw_vol = np.concatenate([d["sw_vol"] for d in ladders if len(d["sw_vol"])]) if len(sw_ts) else np.zeros(0, np.int64)
        sw_lad = np.concatenate([d["sw_lad"] for d in ladders if len(d["sw_lad"])]) if len(sw_ts) else np.zeros((0, LS.K, 2), np.int32)
        N, dt = len(frame), frame.dt_ms * NS_MS
        c = np.full((N, 2), np.nan)
        p = np.full((N, 2), np.nan)
        valid = np.zeros((N, 2), bool)
        reason = np.zeros((N, 2), np.int8)
        nlev = np.zeros((N, 2), np.int32)
        qsum = np.zeros((N, 2), np.int64)
        lo_idx = np.searchsorted(sw_ts, frame.t0)
        hi_idx = np.searchsorted(sw_ts, frame.t0 + dt)
        for k in range(N):
            for col, side, ind in ((0, 1, frame.ind_plus[k]), (1, 0, frame.ind_minus[k])):   # + → ask 侧(side 1)
                if not ind:
                    reason[k, col] = 1
                    continue
                if frame.gap[k] or frame.bnd_index[k] < 0:
                    reason[k, col] = 2
                    continue
                sl = slice(lo_idx[k], hi_idx[k])
                m = sw_side[sl] == (0 if side == 1 else 1)        # 买 MO(0)打 ask 侧
                vols, lads = sw_vol[sl][m], sw_lad[sl][m]
                res = self.curve(bnd_lad[frame.bnd_index[k]], int(frame.mid2[k]), vols, lads, side)
                if res is None:
                    reason[k, col] = 3
                    continue
                Lg, Q = res
                nlev[k, col], qsum[k, col] = len(Lg), int(Q.sum())
                if len(Lg) < 2:
                    reason[k, col] = 5
                    continue
                if Q.sum() == 0:
                    reason[k, col] = 6
                    continue
                w = self._weights(Lg, Q, side)
                ab = _fit(Lg, Q.astype(float), w)
                if ab is None or ab[1] >= 0:
                    reason[k, col] = 4
                    continue
                a, b = ab
                pk = a / (-b)
                if not np.isfinite(pk) or pk > Lg[-1] * 1.0 + 1e-9 or pk <= 0:
                    reason[k, col] = 7                                 # p 不在所用档位范围内(需求曲线没有在观测到的档位内归零),EC-22
                    c[k, col], p[k, col] = -b, pk
                    continue
                c[k, col], p[k, col], valid[k, col] = -b, pk, True
        return DemandParams(frame.dt_ms, c, p, valid, reason, nlev, qsum,
                            dict(V_LO=self.V_LO, weight_fn=self.weight_fn, vl_mode=self.vl_mode, cap_mode=self.cap_mode,
                                 grid_mode=self.grid_mode, reach_given=self.reach is not None, reach_min=self.reach_min, n_use=list(self.n_use)))


def summarize(dp: DemandParams):
    out = {}
    names = {0: "ok", 1: "no_mo", 2: "gap", 3: "no_ladder", 4: "slope_nonneg", 5: "too_few_levels", 6: "all_zero", 7: "p_out_of_range"}
    for col, lab in ((0, "plus"), (1, "minus")):
        v = dp.valid[:, col]
        r = dp.reason[:, col]
        out[lab] = dict(n_valid=int(v.sum()), reasons={names[i]: int((r == i).sum()) for i in range(8)},
                        c_mean=float(np.nanmean(dp.c[v, col])) if v.any() else None, c_std=float(np.nanstd(dp.c[v, col])) if v.any() else None,
                        p_mean=float(np.nanmean(dp.p[v, col])) if v.any() else None, p_std=float(np.nanstd(dp.p[v, col])) if v.any() else None,
                        corr_cp=float(np.corrcoef(dp.c[v, col], dp.p[v, col])[0, 1]) if v.sum() > 2 else None,
                        n_levels_p50=float(np.median(dp.n_levels[v, col])) if v.any() else None)
    return out
