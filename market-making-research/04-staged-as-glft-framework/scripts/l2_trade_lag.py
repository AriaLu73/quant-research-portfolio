#!/usr/bin/env python3
"""research7 成交打印的时间戳相对 L2 盘口变化的时间戳差多少(H6 的核对)。

用途      l2sim 假设"成交与它造成的 L2 数量减少带同一个时间戳"。2026-10-08 调试发现不成立:同一次扫单,
          L2 上价位被吃掉的消息比成交打印早约 2 毫秒 —— 不校正的话,策略会在成交打印之前先看到盘口变化并撤单(等于看到了未来)。
          本脚本量这个时间差的分布:对每笔成交,找同一侧、同一价位、时间最近的一次 L2 数量减少,记 成交时间 − L2 时间。
所属阶段  阶段 0 的补充;不对应报价公式中的某一项。
用法      .venv/Scripts/python.exe scripts/research7/l2_trade_lag.py <YYYYMMDD> [...]
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WIN_NS = 50_000_000        # 只在 ±50 毫秒内找配对(ASSUMPTION:远大于预期的时间差,又不至于配到无关的变化)


def lag(day, sym="XBTUSDTM"):
    ev = np.load(os.path.join(ROOT, "data", "research7", "l2", f"{sym}_{day}.npz"))
    ts, kind, side, tick, size = (ev[k] for k in ("ts", "kind", "side", "tick", "size"))
    lv = kind == 1
    key = side[lv].astype(np.int64) * 10_000_000 + tick[lv]            # (侧, 价位) 合成一个键
    order = np.lexsort((ts[lv], key))
    k_s, t_s, q_s = key[order], ts[lv][order], size[lv][order]
    dec = np.r_[False, (k_s[1:] == k_s[:-1]) & (q_s[1:] < q_s[:-1])]   # 同一价位上数量减少的那些消息
    k_d, t_d = k_s[dec], t_s[dec]
    tr = kind == 0
    kt, tt = side[tr].astype(np.int64) * 10_000_000 + tick[tr], ts[tr]
    out = []
    comp = k_d * (1 << 62 // 10**8) if False else None                  # 占位:下面逐键二分
    # 逐笔成交:在该键的减少序列里找时间最近的一次
    start = np.searchsorted(k_d, kt, side="left")
    end = np.searchsorted(k_d, kt, side="right")
    for a, b, t in zip(start.tolist(), end.tolist(), tt.tolist()):
        if b > a:
            j = a + int(np.searchsorted(t_d[a:b], t))
            best = None
            for jj in (j - 1, j):
                if a <= jj < b and (best is None or abs(t_d[jj] - t) < abs(best)):
                    best = int(t - t_d[jj])
            if best is not None and abs(best) <= WIN_NS:
                out.append(best)
    x = np.asarray(out, float) / 1e6                                    # 纳秒 → 毫秒
    q = np.percentile(x, (1, 5, 25, 50, 75, 95, 99))
    print(f"{day}: 成交 {int(tr.sum()):,} 笔,配上对 {len(x):,}({len(x) / max(tr.sum(), 1):.0%});成交时间 − L2 时间(毫秒)分位 1/5/25/50/75/95/99% = "
          + " / ".join(f"{v:+.0f}" for v in q) + f";恰为 0 的占 {np.mean(x == 0):.0%},在 [+1, +3] 的占 {np.mean((x >= 1) & (x <= 3)):.0%}", flush=True)


if __name__ == "__main__":
    for d in sys.argv[1:]:
        lag(d)
