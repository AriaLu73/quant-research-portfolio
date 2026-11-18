#!/usr/bin/env python3
"""research7 阶段 2 的数据准备:把每天的买一卖一变化序列采样成 100 毫秒等间隔的价格网格。

用途      研究五(波动率)的所有估计——不同采样间隔下的已实现波动、日内规律、预测模型——都从这张网格出发;
          这一步只做采样,不含任何估计方法的选择。
所属阶段  阶段 2(研究五的"数据与特征"一步)。
对应公式  为估计 σ_t(替换报价公式中的常数 σ)准备输入。
变量与 <符号表> 的对应  mid = S_t(美元);micro = 按挂单量加权的中间价(美元),研究五第 1 条"基于 microprice 的估计"的候选输入
输入      data/research7/market_l2/XBTUSDTM_<day>.npz(L2 重建;10 月两天也有 L2 版,保证 22 天口径一致)
输出      data/research7/vol/grid_<day>.npz:
            t0    当天第一个网格点的时间(纳秒,对齐到 100 毫秒)
            mid   float32[n]  每个网格点时刻"之前最后一次盘口变化"的中间价(只用过去的数据)
            micro float32[n]  同一时刻的加权中间价 = (买一价 × 卖一量 + 卖一价 × 买一量) / (买一量 + 卖一量)
            sprd  int16[n]    价差(tick)
            age   float32[n]  这个报价已经多久没有变化(秒);超过 GAP_S 视为数据空档
用法      .venv/Scripts/python.exe scripts/research7/vol_grid.py <YYYYMMDD>
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "data", "research7", "market_l2")
OUT = os.path.join(ROOT, "data", "research7", "vol")
SYM = "XBTUSDTM"
TICK = 0.1                    # 美元 / tick(合约接口存档 2026-10-02)
STEP_NS = 100_000_000         # 网格间隔 100 毫秒:提示词 <markout与P&L归因> 列出的最短时间窗;更细的间隔交易所时间戳(1 毫秒)支持,
                              # 但阶段 2 用不到。ASSUMPTION(只决定可研究的最小采样间隔)


def build(day):
    b = np.load(os.path.join(SRC, f"{SYM}_{day}.npz"))["bbo"]
    t = b[:, 0]
    t0 = (t[0] // STEP_NS + 1) * STEP_NS
    g = np.arange(t0, t[-1], STEP_NS)
    i = np.searchsorted(t, g, side="right") - 1          # 每个网格点之前(含)最后一次盘口变化
    bb, ba, qb, qa = (b[i, k].astype(np.float64) for k in (1, 2, 3, 4))
    mid = (bb + ba) / 2.0 * TICK
    micro = (bb * qa + ba * qb) / np.maximum(qb + qa, 1.0) * TICK
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(os.path.join(OUT, f"grid_{day}.npz"), t0=t0, mid=mid.astype(np.float32), micro=micro.astype(np.float32),
                        sprd=(ba - bb).astype(np.int16), age=((g - t[i]) / 1e9).astype(np.float32))
    print(f"grid {day}: {len(g):,} 点  价差为 1 tick 的时间占比 {np.mean(ba - bb == 1):.1%}  价差中位 {np.median(ba - bb):.0f} tick  报价 5 秒以上未变的占比 {np.mean((g - t[i]) > 5e9):.2%}  VOLGRID_DONE", flush=True)


if __name__ == "__main__":
    build(sys.argv[1])
