"""Step 13.3 —— P2 §2.1 / §2.3:点差的 Markov 链(tick 时钟 + 转移矩阵)。
点差 S_t = 卖一 − 买一(整数 tick),取 ladder_store 50 ms 网格边界;状态 i ∈ {1..m}:点差 = i tick,≥ m 的并入第 m 态(EC-33:m 取使每态占比 ≥ MIN_SHARE 的最大值)。
估计(P2 Eq. 2.6–2.7)  跳变时刻 θ_n = 点差状态变化的时刻;ρ_ij = #{θ_n: 从 i 跳到 j} / #{从 i 出发的跳},ρ_ii = 0;
                       λ(t) 按 UTC 小时分段常数 = 该小时跳变数 / 该小时有效时长。
离散化  Δt 内的转移概率 P_h(Δt) = expm(λ_h (ρ − I) Δt)(连续时间链的精确离散化)。
"""
import glob
import json
import os
import sys

import numpy as np
from scipy.linalg import expm

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPRO, "data"))
import ladder_store as LS      # noqa: E402

MIN_SHARE = 0.01
NS = 1_000_000_000


def spread_series(sym, day):
    ts, sp = [], []
    for p in sorted(glob.glob(os.path.join(REPRO, "data", "step01", sym, f"{day}_*.npz"))):
        z = LS.load(p, keys=("bnd_ts", "bnd_lad"))
        lad = z["bnd_lad"]
        ok = (lad[:, 0, 0, 1] > 0) & (lad[:, 1, 0, 1] > 0)
        ts.append(z["bnd_ts"][ok])
        sp.append(lad[ok, 1, 0, 0].astype(np.int64) - lad[ok, 0, 0, 0].astype(np.int64))
    return (np.concatenate(ts), np.concatenate(sp)) if ts else (np.zeros(0, np.int64), np.zeros(0, np.int64))


class SpreadChain:
    def __init__(self, m, rho, lam_hourly, share, meta):
        self.m, self.rho, self.lam_hourly, self.share, self.meta = m, rho, lam_hourly, share, meta

    def state(self, spread_ticks):
        """点差(tick)→ 桶序号 0..m-1。"""
        return int(np.searchsorted(np.asarray(self.edges), spread_ticks, side="left"))

    def states(self, spread_ticks_array):
        return np.searchsorted(np.asarray(self.edges), np.asarray(spread_ticks_array), side="left")

    def transition(self, hour, dt_ms):
        lam = self.lam_hourly[hour]
        R = lam * (self.rho - np.eye(self.m))
        return expm(R * dt_ms / 1000.0)

    def to_json(self):
        return dict(m=self.m, rho=self.rho.tolist(), lam_hourly=self.lam_hourly.tolist(), share=self.share.tolist(), meta=self.meta)

    @staticmethod
    def from_json(d):
        ch = SpreadChain(d["m"], np.asarray(d["rho"]), np.asarray(d["lam_hourly"]), np.asarray(d["share"]), d["meta"])
        ch.edges, ch.rep = np.asarray(d["meta"]["edges"]), np.asarray(d["meta"]["rep_ticks"])
        return ch


def fit(sym, days, min_share=MIN_SHARE):
    """days:训练窗日期列表。返回 SpreadChain。"""
    all_sp, jumps = [], []          # jumps: (hour, from_state_raw, to_state_raw)
    hour_time = np.zeros(24)
    for d in days:
        ts, sp = spread_series(sym, d)
        if len(sp) == 0:
            continue
        all_sp.append(sp)
        hrs = ((ts // NS) % 86400) // 3600
        np.add.at(hour_time, hrs, LS.GRID_MS / 1000.0)
        ch = np.where(np.diff(sp) != 0)[0]
        jumps.append(np.stack([hrs[ch + 1], sp[ch], sp[ch + 1]], axis=1))
    sp = np.concatenate(all_sp)
    J = np.concatenate(jumps) if jumps else np.zeros((0, 3), np.int64)
    # EC-33:KuCoin 点差不是 1–6 tick 的离散档(XBTUSDCM 10 月中位 19 tick、p90 64;9 月中位 199),状态改为训练窗上的 m 个分位桶,
    # 桶边界 = 分位数(去重),代表值 = 桶内中位数(tick);状态变化 = 桶变化。m 默认 6(P2 Table 4c)。
    m_target = 6
    edges = np.unique(np.percentile(sp, np.linspace(0, 100, m_target + 1)[1:-1]).astype(np.int64))
    edges = edges[edges > 0]
    bins = np.concatenate([[0], edges, [np.iinfo(np.int64).max]])         # 桶 i = (bins[i], bins[i+1]]
    m = len(bins) - 1
    def clip(x):
        return np.searchsorted(bins[1:-1], x, side="left")                   # 0..m-1
    rep = np.array([float(np.median(sp[clip(sp) == i])) if np.any(clip(sp) == i) else float(bins[i] + 1) for i in range(m)])
    f, t = clip(J[:, 1]), clip(J[:, 2])
    keep = f != t                                   # 并入最后一态后的"同态跳"不算跳
    C = np.zeros((m, m))
    np.add.at(C, (f[keep], t[keep]), 1)
    rho = np.where(C.sum(1, keepdims=True) > 0, C / np.maximum(C.sum(1, keepdims=True), 1), 0.0)
    for i in range(m):
        if C[i].sum() == 0:                         # 从未观察到离开:按邻态均分(登记)
            rho[i] = 0.0
            nb = [j for j in (i - 1, i + 1) if 0 <= j < m]
            rho[i, nb] = 1.0 / len(nb)
    hour_jumps = np.bincount(J[keep, 0], minlength=24)[:24]
    lam = np.where(hour_time > 0, hour_jumps / np.maximum(hour_time, 1e-9), np.nan)
    lam = np.where(np.isnan(lam), np.nanmean(lam), lam)
    share = np.bincount(clip(sp), minlength=m) / len(sp)
    meta = dict(sym=sym, days=list(days), n_obs=int(len(sp)), n_jumps=int(keep.sum()), spread_pct={str(q): float(np.percentile(sp, q)) for q in (10, 50, 90, 99)},
                hour_time_s=hour_time.tolist(), edges=edges.tolist(), rep_ticks=rep.tolist())
    ch = SpreadChain(m, rho, lam, share, meta)
    ch.edges, ch.rep = edges, rep
    return ch


if __name__ == "__main__":
    sym = sys.argv[1]
    days = sys.argv[2].split(",")
    ch = fit(sym, days)
    print(json.dumps(ch.to_json(), indent=1)[:1500])
