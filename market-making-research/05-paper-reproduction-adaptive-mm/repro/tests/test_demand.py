r"""Step 2 单测:(1) 已知线性需求 Q = c(p−L) 的合成曲线,加权回归精确反推 (c, p);(2) 单笔 MO 成交公式 min(max(V_MO−V_L,0),V_LO) 与 V_L 的阶梯;
(3) at_t0 / per_mo、per_mo / interval 封顶的差异方向;(4) 只在 1^±=1 的区间估计。"""
import os
import sys

import numpy as np

REPRO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPRO, "a"))
sys.path.insert(0, os.path.join(REPRO, "data"))
import demand as DM            # noqa: E402
import ladder_store as LS      # noqa: E402
from events import EventFrame  # noqa: E402


def test_fit_recovers_linear():
    L = np.arange(1, 11, dtype=float)
    c, p = 3.0, 8.0
    Q = c * (p - L)
    for w in (np.ones(10), 1 / L):
        a, b = DM._fit(L, Q, w)
        assert abs(-b - c) < 1e-9 and abs(a / (-b) - p) < 1e-9


def test_fill_formula_and_vl():
    # ask 侧 ladder:102×5, 103×7, 105×10;中价 2×=201(bb=100? 这里只看 ask 侧)
    lad = np.zeros((2, LS.K, 2), np.int32)
    lad[1, :3] = [(102, 5), (103, 7), (105, 10)]
    est = DM.DemandEstimator(V_LO=6, grid_mode="ticks", vl_mode="at_t0")
    Lg, Q = est.curve(lad, 201, [8], [None], side=1)
    # 中价 100.5 → 逐 tick 网格 101..105(101 在价差之内,V_L = 0)→ L = 0.5…4.5;V_L = 0, 0, 5, 12, 12;成交 = min(max(8−V_L,0),6) = 6, 6, 3, 0, 0
    assert Lg.tolist() == [0.5, 1.5, 2.5, 3.5, 4.5] and Q.tolist() == [6, 6, 3, 0, 0]
    est_lv = DM.DemandEstimator(V_LO=6, grid_mode="levels", vl_mode="at_t0")
    Lg2, Q2 = est_lv.curve(lad, 201, [8], [None], side=1)
    assert Lg2.tolist() == [1.5, 2.5, 4.5] and Q2.tolist() == [6, 3, 0]
    # 两笔 MO 各自封顶后求和可超过 V_LO(字面);interval 封顶则不超过
    Lg3, Q3 = est_lv.curve(lad, 201, [8, 8], [None, None], side=1)
    assert Q3.tolist() == [12, 6, 0]
    est_cap = DM.DemandEstimator(V_LO=6, grid_mode="levels", vl_mode="at_t0", cap_mode="interval")
    assert est_cap.curve(lad, 201, [8, 8], [None, None], side=1)[1].tolist() == [6, 6, 0]
    # bid 侧对称
    lad[0, :2] = [(99, 4), (97, 9)]
    Lb, Qb = est_lv.curve(lad, 201, [5], [None], side=0)
    assert Lb.tolist() == [1.5, 3.5] and Qb.tolist() == [5, 1]


def test_estimate_only_on_mo_intervals():
    # 两个区间:区间 0 有买 MO,区间 1 没有;期望 valid+ = [True, False],reason 1 = no_mo
    lad = np.zeros((1, 2, LS.K, 2), np.int32)
    lad[0, 1, :3] = [(102, 5), (103, 7), (105, 10)]
    lad[0, 0, :2] = [(99, 4), (97, 9)]
    d = dict(bnd_lad=lad, sw_ts=np.array([10]), sw_side=np.array([0], np.int8), sw_vol=np.array([8]), sw_lad=np.zeros((1, LS.K, 2), np.int32), meta={})
    fr = EventFrame(1000, np.array([0, 10**9]), np.array([True, False]), np.array([False, False]), np.array([8, 0]), np.array([0, 0]),
                    np.array([1, 0]), np.array([0, 0]), np.array([201, 201]), np.array([False, False]), np.array([0, 0]))
    dp = DM.DemandEstimator(V_LO=6, grid_mode="levels", weight_fn="uniform").estimate(fr, [d])
    assert dp.valid[:, 0].tolist() == [True, False] and dp.reason[1, 0] == 1 and dp.reason[0, 1] == 1
    # Q = [6, 3, 0] 对 L = [1.5, 2.5, 4.5] 的均权拟合:斜率为负,c>0,p 在 2.5 与 4.5 之间附近
    assert dp.c[0, 0] > 0 and 2 < dp.p[0, 0] < 6


if __name__ == "__main__":
    for f in (test_fit_recovers_linear, test_fill_formula_and_vl, test_estimate_only_on_mo_intervals):
        f()
        print("ok", f.__name__)
