"""V_LO 标定的采集:每条 L3 新挂单(open)进簿时所在的档位序号(同侧由优到劣第几个占用价位)与张数。

定义(任务书文件头:"L3 新挂单中落在盘口前 5 档的张数中位数";"档" = 占用价位,登记表 EC-04):
  rank = 1 + 同侧价格严格优于该单且张数 > 0 的占用价位数;改善最优价的新单 rank = 1。只需判断 rank ≤ 5,计数到 6 即停。
实现  子类化引擎 L3Sim,只在 _on_open 前读盘口(self.touch.size),不改撮合。盘口占用价位用本类维护的有序 key 表(惰性清零键,定期重建)。
输出  repro/_tmp/vlo/<sym>_<day>_<hh>.npz:rows[n,5] = ts, side, tick, size, rank(1..5;6 = 更深;0 = 该侧为空)
用法  python vlo_collect.py <sym> <YYYYMMDD> <HH>
"""
import bisect
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine_bridge as B   # noqa: E402

L, E = B.L, B.E
OUT = os.path.join(B.REPRO, "_tmp", "vlo")


class VloSim(L.L3Sim):
    def __init__(self, sym, t_from=0, t_to=1 << 62):
        super().__init__(sym, L.Latency(fixed_ms=0.0), agents=[], recorder=None, trade_ticks={})
        self.t_from, self.t_to = t_from, t_to
        self.keys = ([], [])        # 每侧出现过的价位(升序);张数可能已为 0,计数时按 touch.size 过滤
        self.rows = []
        self._n_since_rebuild = 0

    def _rank(self, side, tick):
        s = self.touch.size[side]
        ks = self.keys[side]
        i = bisect.bisect_left(ks, tick)
        n = 0
        if side == 0:                      # bid:更优 = 更高的 tick
            j = i + (1 if i < len(ks) and ks[i] == tick else 0)
            while j < len(ks) and n < 6:
                if s.get(ks[j], 0) > 0:
                    n += 1
                j += 1
        else:                              # ask:更优 = 更低的 tick
            j = i - 1
            while j >= 0 and n < 6:
                if s.get(ks[j], 0) > 0:
                    n += 1
                j -= 1
        return n + 1

    def _on_open(self, d, seq):
        side = 0 if d["side"] == "buy" else 1
        tick = L.to_tick(d["price"])
        ks = self.keys[side]
        i = bisect.bisect_left(ks, tick)
        if i == len(ks) or ks[i] != tick:
            ks.insert(i, tick)
        if self.ready and self.t_from <= self._ts < self.t_to:      # 只记本小时(EC-16:预热段是上一小时末尾,不能重复计)
            best = self.touch.best(side)
            r = 0 if best is None else self._rank(side, tick)
            self.rows.append((self._ts, side, tick, int(d["size"]), min(r, 6)))
        self._n_since_rebuild += 1
        if self._n_since_rebuild >= 200_000:  # 清掉已空的价位键
            self._n_since_rebuild = 0
            for sd in (0, 1):
                sz = self.touch.size[sd]
                self.keys[sd][:] = sorted(k for k in self.keys[sd] if sz.get(k, 0) > 0)
        super()._on_open(d, seq)


if __name__ == "__main__":
    sym, day, hh = sys.argv[1:4]
    B.patch_engine(sym)
    t_from = E.P.hour_start_ns(day, hh)
    sim = VloSim(sym, t_from, t_from + 3_600 * 1_000_000_000)
    E.run_hours(sim, day, [hh], prewarm_s=300)
    os.makedirs(OUT, exist_ok=True)
    rows = np.asarray(sim.rows, np.int64).reshape(-1, 5)
    np.savez_compressed(os.path.join(OUT, f"{sym}_{day}_{hh}.npz"), rows=rows, breaks=sim.breaks)
    r = rows[:, 4]
    print(f"{sym} {day} {hh}: opens={len(rows):,} rank<=5 {int((r >= 1).sum() and ((r >= 1) & (r <= 5)).sum()):,} "
          f"median_size_top5={np.median(rows[(r >= 1) & (r <= 5), 3]) if ((r >= 1) & (r <= 5)).any() else float('nan')} breaks={sim.breaks} VLO_DONE", flush=True)
