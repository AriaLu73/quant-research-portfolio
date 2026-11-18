"""Step 1 —— P1 §2.1 Eq. (1)–(2) 的事件定义:以 Δt 为参数,从 ladder_store 提取物生成按区间组织的 EventFrame。

区间   t_k = k·Δt(UTC 纪元对齐;Δt 必须是 GRID_MS = 50 ms 的整数倍)。区间 [t_k, t_{k+1}) 的指标记在下标 k+1(与论文 1^±_{t_{k+1}} 一致)。
1^±    区间内是否至少有一笔对应方向的 MO(到达指标,不是笔数;P1 Eq. 1)。+ = 买 MO(打卖单), − = 卖 MO(打买单)。
vol±   区间内该方向 MO 总张数(辅助统计,策略不用)。
mid2   t_k 时刻的 买一+卖一(整数 tick 的两倍),S_{t_k} = mid2/2 × TICK;任一侧空 = -1。
gap    t_k 时刻的盘口不可用(无边界记录 / 任一侧空 / 位于录制缺口内):附录第 7 条"缺口期间冻结报价、不记成交、库存延续,缺口后重新预热 ϖ 个区间"。
burn-in  论文假设 t_0 之前有足够长历史使 e_{t_0} 可定义(§2.1):每段连续覆盖的最前 ϖ 个区间只作历史、不作决策(EC-07)。
"""
import os
import sys
from dataclasses import dataclass

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
import ladder_store as LS      # noqa: E402

NS_MS = 1_000_000


@dataclass
class EventFrame:
    dt_ms: int
    t0: np.ndarray          # 区间起点 t_k (ns),长度 N
    ind_plus: np.ndarray    # 1^+_{t_{k+1}}:区间 [t_k, t_{k+1}) 内有买 MO
    ind_minus: np.ndarray
    vol_plus: np.ndarray
    vol_minus: np.ndarray
    n_plus: np.ndarray      # 该方向 MO 笔数
    n_minus: np.ndarray
    mid2: np.ndarray        # t_k 时刻 bb+ba(-1 = 不可用)
    gap: np.ndarray         # t_k 时刻盘口不可用
    bnd_index: np.ndarray   # 对应 ladder 边界记录的下标(-1 = 无记录),供 Step 2 取 t_k 盘口

    def __len__(self):
        return len(self.t0)


def _concat(files, key):
    arrs = [f[key] for f in files if len(f[key])]
    return np.concatenate(arrs) if arrs else np.zeros(0, np.int64)


def build(ladders, dt_ms, t_start=None, t_end=None):
    """ladders: 已按时间排好的 ladder_store.load() 字典列表(同一合约,连续若干小时)。返回 EventFrame。
    [t_start, t_end) 可裁剪(例如 UTC 日边界);默认取覆盖范围。"""
    assert dt_ms % LS.GRID_MS == 0, "Δt 必须是 50 ms 网格的整数倍"
    dt = dt_ms * NS_MS
    bts = _concat(ladders, "bnd_ts")
    bmid = _concat(ladders, "bnd_mid2")
    sts = _concat(ladders, "sw_ts")
    sside = _concat(ladders, "sw_side").astype(np.int64)
    svol = _concat(ladders, "sw_vol")
    if len(bts) == 0:
        raise ValueError("没有边界记录")
    lo = bts[0] if t_start is None else max(t_start, (bts[0] // dt) * dt)
    hi = bts[-1] if t_end is None else min(t_end, bts[-1])
    lo = (lo // dt) * dt
    t0 = np.arange(lo, hi, dt, dtype=np.int64)
    N = len(t0)
    # 边界记录对齐:t_k 是否恰有边界记录(边界在 50 ms 网格上,t_k 也在)
    idx = np.searchsorted(bts, t0)
    has = (idx < len(bts)) & (bts[np.minimum(idx, len(bts) - 1)] == t0)
    bnd_index = np.where(has, idx, -1)
    mid2 = np.where(has, bmid[np.minimum(idx, len(bts) - 1)], -1)
    gap = ~has | (mid2 < 0)
    # MO 归入区间:k = (ts - lo) // dt,记在 k+1 位置 → 用 k 作为 "区间 [t_k, t_{k+1})" 的下标即可(论文下标 t_{k+1} 只是记号)
    k = (sts - lo) // dt
    ok = (k >= 0) & (k < N) & (sts >= max(lo, bts[0])) & (sts < hi)   # 只计 [首个边界记录, hi) 内的 MO:之前的区间是 gap;末区间不越过裁剪终点 → 各 Δt 下笔数守恒
    k, sd, v = k[ok], sside[ok], svol[ok]
    ind_plus = np.zeros(N, bool)
    ind_minus = np.zeros(N, bool)
    vol_plus = np.zeros(N, np.int64)
    vol_minus = np.zeros(N, np.int64)
    n_plus = np.zeros(N, np.int64)
    n_minus = np.zeros(N, np.int64)
    np.add.at(vol_plus, k[sd == 0], v[sd == 0])
    np.add.at(vol_minus, k[sd == 1], v[sd == 1])
    np.add.at(n_plus, k[sd == 0], 1)
    np.add.at(n_minus, k[sd == 1], 1)
    ind_plus[:] = n_plus > 0
    ind_minus[:] = n_minus > 0
    return EventFrame(dt_ms, t0, ind_plus, ind_minus, vol_plus, vol_minus, n_plus, n_minus, mid2, gap, bnd_index)


def validate(fr: EventFrame):
    """到达频率、联合到达频率、成交量分布(Step 1 验证项)。只统计非缺口区间。"""
    m = ~fr.gap
    p, q = fr.ind_plus[m], fr.ind_minus[m]
    out = dict(dt_ms=fr.dt_ms, n_intervals=int(len(fr)), n_gap=int(fr.gap.sum()),
               pi_plus=float(p.mean()) if m.any() else None, pi_minus=float(q.mean()) if m.any() else None,
               pi_11=float((p & q).mean()) if m.any() else None,
               pi_11_if_indep=float(p.mean() * q.mean()) if m.any() else None,
               P00=float((~p & ~q).mean()), P10=float((p & ~q).mean()), P01=float((~p & q).mean()), P11=float((p & q).mean()),
               share_no_mo=float((~p & ~q).mean()),
               vol_plus_pct={k: float(np.percentile(fr.vol_plus[m & fr.ind_plus], k)) for k in (50, 90, 99)} if (m & fr.ind_plus).any() else None,
               vol_minus_pct={k: float(np.percentile(fr.vol_minus[m & fr.ind_minus], k)) for k in (50, 90, 99)} if (m & fr.ind_minus).any() else None,
               n_mo_per_interval_max=int(max(fr.n_plus.max(), fr.n_minus.max())))
    return out
