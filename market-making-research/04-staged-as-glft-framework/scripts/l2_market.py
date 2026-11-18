#!/usr/bin/env python3
"""research7 从 L2 事件数组重建每天的买一卖一变化序列与吃单明细(8–9 月没有逐笔委托的日子用)。

用途      给校准(σ、λ(δ)、A、κ)与 markout 归因提供与 data/research7/market(逐笔委托版)同格式的输入。
所属阶段  阶段 0 的补充;不属于研究模块,不对应报价公式中的某一项。
输出      data/research7/market_l2/<SYM>_<YYYYMMDD>.npz:bbo [n,5](时间纳秒、买一 tick、卖一 tick、买一张数、卖一张数),
          sw [m,6](时间、挂单方一侧、总张数、最先成交 tick、最后成交 tick、成交行数);列的含义同 l3_prep.Recorder。
          不按盘口成交的打印(l2sim 假设 H4')已剔除。
用法      .venv/Scripts/python.exe scripts/research7/l2_market.py <YYYYMMDD> [SYM]
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l2sim as S
import l3_prep as P
import l3sim as L


def build(day, sym="XBTUSDTM"):
    ev = np.load(os.path.join(P.OUT, "l2", f"{sym}_{day}.npz"))
    rec = P.Recorder()
    sim = S.L2Sim(sym, L.Latency(), [], recorder=rec)      # 不带策略,只重建盘口
    sim.run(ev)
    out = os.path.join(P.OUT, "market_l2")
    os.makedirs(out, exist_ok=True)
    np.savez_compressed(os.path.join(out, f"{sym}_{day}.npz"), bbo=np.asarray(rec.bbo, np.int64).reshape(-1, 5),
                        sw=np.asarray(rec.sw, np.int64).reshape(-1, 6), breaks=sim.breaks)
    print(f"market_l2 {sym} {day}: 买一卖一变化 {len(rec.bbo):,}  吃单 {len(rec.sw):,}  重置 {sim.breaks}  非盘口打印 {sim.paired_n} 笔  L2MKT_DONE", flush=True)


if __name__ == "__main__":
    build(*sys.argv[1:])
