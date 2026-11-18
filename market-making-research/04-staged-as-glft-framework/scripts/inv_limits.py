#!/usr/bin/env python3
"""research7 研究四第 4 条(库存上限)的离线部分:极端价格变动的分位,与"持仓 × 极端变动"的美元损失表。

用途      库存上限要由"压力情景下的最大损失"来定(提示词研究四第 4 条)。这里只量价格变动的分布,不含任何策略回放。
所属阶段  阶段 5,研究四。
对应公式  q_max(库存约束)。
数据      22 天 100 毫秒价格网格(data/research7/vol,vol_grid.py);空档(报价 5 秒以上未变)两端的变动不计。
用法      .venv/Scripts/python.exe scripts/research7/inv_limits.py
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GRID = os.path.join(ROOT, "data", "research7", "vol")
WINDOWS_S = (60, 300, 1800)               # 持有窗口(秒):1 / 5 / 30 分钟 —— 项目记录 pre-live-gates 要求报告最差 1 / 5 / 30 分钟
QS = (0.99, 0.999, 1.0)
ORDER_BTC = 0.2                           # 每张单 0.2 BTC(项目记录)
rows = {w: [] for w in WINDOWS_S}
for f in sorted(os.listdir(GRID)):
    if not f.startswith("grid_"):
        continue
    z = np.load(os.path.join(GRID, f))
    mid, ok = z["mid"].astype(float), z["age"] < 5.0
    for w in WINDOWS_S:
        k = w * 10                                              # 网格点数(100 毫秒一格)
        i = np.arange(0, len(mid) - k, 100)                     # 每 10 秒取一个起点
        good = ok[i] & ok[i + k]
        rows[w].append(np.abs(mid[i + k] - mid[i])[good])       # 美元 / BTC
print("中间价绝对变动的分位(美元 / BTC;22 天,每 10 秒一个起点)与持仓的美元损失")
print("窗口      99%      99.9%     最大   | 1 张(0.2 BTC):99% / 99.9% / 最大 | 2 张(当前上限):99.9% / 最大")
for w in WINDOWS_S:
    x = np.concatenate(rows[w])
    q = np.quantile(x, QS)
    print(f"{w:>5d}s {q[0]:>8.1f} {q[1]:>9.1f} {q[2]:>9.1f}  | ${q[0] * ORDER_BTC:>6.0f} / ${q[1] * ORDER_BTC:>6.0f} / ${q[2] * ORDER_BTC:>6.0f}       | ${q[1] * 2 * ORDER_BTC:>6.0f} / ${q[2] * 2 * ORDER_BTC:>6.0f}")
