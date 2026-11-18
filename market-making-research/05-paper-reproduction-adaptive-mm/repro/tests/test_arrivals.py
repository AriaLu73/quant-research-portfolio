r"""Step 4 单测:(1) Γ 在全部 (i+, i−, s) 上封闭且与 encode 一致(Assumption 4 / Eq. 42);(2) 状态数 64 / 27 / 81;
(3) states() 的 burn-in 与缺口重置;(4) 估计的 π 与手工计数一致、联合律 Eq.(9) 四项和为 1。"""
import os
import sys

import numpy as np

REPRO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPRO, "a"))
import arrivals as AR          # noqa: E402
from events import EventFrame  # noqa: E402


def make_frame(ip, im, gap=None):
    N = len(ip)
    ip, im = np.asarray(ip, bool), np.asarray(im, bool)
    gap = np.zeros(N, bool) if gap is None else np.asarray(gap, bool)
    z = np.zeros(N, np.int64)
    return EventFrame(1000, np.arange(N) * 10**9, ip, im, z, z, ip.astype(np.int64), im.astype(np.int64), np.full(N, 200), gap, np.arange(N))


def test_gamma_matches_encode():
    rng = np.random.default_rng(0)
    for kind in ("g1", "g2", "g3"):
        g = AR.GState(kind)
        assert g.n_states == {"g1": 64, "g2": 27, "g3": 81}[kind]
        assert set(np.unique(g.Gamma)) <= set(range(g.n_states))
        for _ in range(300):
            hp = rng.integers(0, 2, g.lags + 1)
            hm = rng.integers(0, 2, g.lags + 1)
            s_old = g.encode(hp[1:], hm[1:])            # 旧历史(滞后 1..ϖ)
            s_new = g.encode(hp, hm)                    # 新历史(最新 + 滞后)
            assert g.Gamma[hp[0], hm[0], s_old] == s_new
        # 每个状态都可达:Γ 的像覆盖全部状态
        assert len(set(g.Gamma.flatten().tolist())) == g.n_states


def test_states_burnin_and_gap():
    g = AR.GState("g2")
    ip = [1, 0, 1, 1, 0, 0, 1, 0, 1, 1]
    im = [0, 0, 1, 0, 1, 0, 0, 0, 1, 0]
    gap = [0, 0, 0, 0, 0, 1, 0, 0, 0, 0]
    s = g.states(make_frame(ip, im, gap))
    assert list(s[:3]) == [-1, -1, -1] and s[3] >= 0 and s[4] >= 0     # 前 ϖ=3 个无状态
    assert s[5] == -1 and list(s[6:9]) == [-1, -1, -1] and s[9] >= 0   # 缺口及其后 3 个无状态
    # s[3] 的历史 = 区间 2,1,0 的和 = (2, 0, 1) → 2 + 0*3 + 1*9 = 11
    assert s[3] == 11


def test_estimates_and_joint():
    rng = np.random.default_rng(1)
    N = 20000
    ip = rng.random(N) < 0.3
    im = rng.random(N) < 0.25
    fr = make_frame(ip, im)
    g = AR.GState("g3")
    m = AR.ArrivalModel(g).add(fr).finalize()
    chk = m.check_legal()
    assert chk["pi11_gt_min"] == 0 and chk["P00_negative"] == 0
    J = m.joint()
    assert np.allclose(J.sum(axis=1), 1.0)
    # 独立生成 → 条件概率应接近无条件(每个状态 ±0.1)
    seen = m.count > 50
    assert np.all(np.abs(m.pi_plus[seen] - 0.3) < 0.1)
    # 手工核对一个状态
    s = g.states(fr)
    k = np.where(s == 0)[0]
    assert m.count[0] == len(k) and m.n_plus[0] == ip[k].sum()
    sc = AR.score(fr, m)
    assert 0 < sc["plus"]["logloss"] < 1


if __name__ == "__main__":
    for f in (test_gamma_matches_encode, test_states_burnin_and_gap, test_estimates_and_joint):
        f()
        print("ok", f.__name__)
