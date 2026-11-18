#!/usr/bin/env python3
"""全天(00–24 时 UTC)10 毫秒网格上的买一 / 卖一价,用于把回测盈亏拆成"价差部分 / alpha 部分"(成交后 10 秒的中间价)。
口径与 RDAgent_Factor/评估脚本/build_grid.py 相同(同样的盘口重建、对侧残留价位清理、"网格点之前"的状态),只是不限 12–18 时、只存最优价。
输入 data/research7/l2/<合约>_<day>.npz;输出 data/research7/mid24/<合约>_<day>.npz(bp、ap:跳;ok;t0;tick)。
用法 Python314/python.exe scripts/research7/mid24.py ETHUSDTM 20260830 [更多日期...]
"""
import heapq
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L2 = os.path.join(ROOT, "data", "research7", "l2")
OUT = os.path.join(ROOT, "data", "research7", "mid24")
TICK = {"XBTUSDTM": 0.1, "ETHUSDTM": 0.01, "SOLUSDTM": 0.001}
STEP_NS = 10_000_000


def best(sz, heap, side):
    while heap:
        b = -heap[0] if side == 0 else heap[0]
        if sz.get(b, 0) > 0:
            return b
        heapq.heappop(heap)
        sz.pop(b, None)
    return None


def build(sym, day):
    ev = np.load(os.path.join(L2, "%s_%s.npz" % (sym, day)))
    ts_a, kind_a, side_a, tick_a, size_a = (ev[k] for k in ("ts", "kind", "side", "tick", "size"))
    day0 = (int(ts_a[len(ts_a) // 2]) // (86400 * 10**9)) * 86400 * 10**9
    t0, t1 = day0, day0 + 86400 * 10**9
    n = (t1 - t0) // STEP_NS
    bp, ap, ok = np.zeros(n, np.int32), np.zeros(n, np.int32), np.zeros(n, bool)
    sz, heap = ({}, {}), ([], [])
    ready, dirty, last, g = False, True, None, 0
    i1 = int(np.searchsorted(ts_a, t1, side="right"))
    CH = 2_000_000
    for c0 in range(0, i1, CH):
        T, K, S, P, Q = (a[c0:min(c0 + CH, i1)].tolist() for a in (ts_a, kind_a, side_a, tick_a, size_a))
        for ts, k, s, p, q in zip(T, K, S, P, Q):
            if ts > t0 and g < n:
                gi = min((ts - t0 - 1) // STEP_NS + 1, n)
                if gi > g:
                    if dirty:
                        if ready:
                            b, a = best(sz[0], heap[0], 0), best(sz[1], heap[1], 1)
                            last = (b, a) if (b is not None and a is not None and b < a) else None
                        else:
                            last = None
                        dirty = False
                    if last is not None:
                        bp[g:gi], ap[g:gi], ok[g:gi] = last[0], last[1], True
                    g = gi
            if k == 1:
                d = sz[s]
                if q > 0:
                    if p not in d:
                        heapq.heappush(heap[s], -p if s == 0 else p)
                    d[p] = q
                    o, h = sz[1 - s], heap[1 - s]
                    while h:
                        bo = -h[0] if (1 - s) == 0 else h[0]
                        if o.get(bo, 0) <= 0:
                            heapq.heappop(h)
                            o.pop(bo, None)
                            continue
                        if (bo >= p) if (1 - s) == 0 else (bo <= p):
                            o[bo] = 0
                            continue
                        break
                elif p in d:
                    d[p] = 0
                dirty = True
            elif k == 2:
                sz, heap = ({}, {}), ([], [])
                ready, dirty = True, True
            elif k == 3:
                ready, dirty = False, True
    if g < n and last is not None and not dirty:
        bp[g:], ap[g:], ok[g:] = last[0], last[1], True
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(os.path.join(OUT, "%s_%s.npz" % (sym, day)), bp=bp, ap=ap, ok=ok, t0=t0, tick=TICK[sym])
    print("mid24 %s %s: 网格点 %d,有效 %.2f%%" % (sym, day, n, 100 * ok.mean()), flush=True)


if __name__ == "__main__":
    for d in sys.argv[2:]:
        build(sys.argv[1], d)
