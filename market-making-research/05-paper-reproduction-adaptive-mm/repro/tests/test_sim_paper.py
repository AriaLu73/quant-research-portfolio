r"""Step 8–9 单测:(1) 现金 / 库存更新 Eq. (11)–(12)(卖出收 a·Q⁺、买入付 b·Q⁻,库存反向);(2) 成交规则 min(max(V_MO−V_L,0),V_LO) 与 V_L 的阶梯;
(3) 价差内报价 V_L = 0;(4) 沿深度清算的平均价与成本符号;(5) Level i 定义;(6) 冻结区间不记成交、库存延续。"""
import os
import sys

import numpy as np

REPRO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPRO, "a"))
sys.path.insert(0, os.path.join(REPRO, "data"))
import ladder_store as LS      # noqa: E402
import sim_paper as SP         # noqa: E402


def test_vl_and_fill():
    lad = np.zeros((2, LS.K, 2), np.int32)
    lad[1, :3] = [(102, 5), (103, 7), (105, 10)]
    lad[0, :2] = [(99, 4), (97, 9)]
    assert SP._vl(lad[1], 1, 101, LS.K) == (0, False)        # 价差内
    assert SP._vl(lad[1], 1, 103, LS.K) == (5, False)
    assert SP._vl(lad[1], 1, 104, LS.K) == (12, False)
    assert SP._vl(lad[0], 0, 98, LS.K) == (4, False)
    # 深于全部可见档(只有 3 档 < K,不算 beyond;满 20 档时才算)
    full = np.zeros((LS.K, 2), np.int32); full[:, 0] = np.arange(102, 122); full[:, 1] = 1
    assert SP._vl(full, 1, 130, LS.K) == (20, True)
    fills = np.minimum(np.maximum(np.array([8, 3]) - 5, 0), 6)
    assert fills.tolist() == [3, 0]


def test_cash_inventory_update_and_level():
    # 手工:ask 103 成交 4 张、bid 98 成交 2 张 → W = 103·4 − 98·2 = 216(tick×张),I = 2 − 4 = −2
    W, I = 0.0, 0.0
    at, bt, qp, qm = 103, 98, 4, 2
    W += at * qp - bt * qm; I += qm - qp
    assert W == 216 and I == -2
    p = SP.FixedLevelPolicy(2)
    assert p.quote(0, 0, 0, 201, 0.0)[:2] == (99, 102)         # mid 100.5:bid = ⌈100.5⌉−2 = 99, ask = ⌊100.5⌋+2 = 102
    assert SP.FixedLevelPolicy(1).quote(0, 0, 0, 200, 0.0)[:2] == (99, 101)


def test_liquidation():
    deep = np.zeros((2, LS.KD, 2), np.int32)
    deep[0, :3] = [(99, 5), (98, 10), (96, 100)]
    deep[1, :2] = [(101, 5), (103, 100)]
    Sbar, cost, short = SP.liquidation_price(deep, 12, 100.0)   # 卖 12 张:5@99 + 7@98 → 平均 98.4167
    assert abs(Sbar - (5 * 99 + 7 * 98) / 12) < 1e-9 and short == 0 and cost > 0
    Sbar2, cost2, short2 = SP.liquidation_price(deep, -8, 100.0)  # 买回 8:5@101 + 3@103 → 101.75;成本 = (100 − 101.75)·(−8) > 0
    assert abs(Sbar2 - 101.75) < 1e-9 and cost2 > 0
    assert SP.liquidation_price(deep, 0, 100.0) == (100.0, 0.0, 0)


def test_hold_segments():
    r = dict(I=np.array([0, 0, 3, 3, 3, 0, -1, 0, 0, 2]))
    s = SP.summarize_series(r, 1000)
    assert s["n_hold_segments"] == 3 and s["hold_max_s"] == 3 and s["hold_gt_300s"] == 0


if __name__ == "__main__":
    for f in (test_vl_and_fill, test_cash_inventory_update_and_level, test_liquidation, test_hold_segments):
        f()
        print("ok", f.__name__)
