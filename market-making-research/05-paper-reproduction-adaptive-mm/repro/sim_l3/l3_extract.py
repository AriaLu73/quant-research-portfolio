"""Step 1 提取(10 月 L3):用引擎 L3Sim 重建盘口,按 ladder_store 格式记录 50 ms 网格边界的盘口、每张吃单到达前的盘口与扫单量。

挂钩(不改引擎)
  _advance(now)   引擎在应用一条消息之前以该消息的 ts 调用它(l3sim.py feed):此时盘口 = 所有 ts < now 的消息之后的状态,
                  正是 "边界 t_k 时刻" 的盘口 → 在这里补记所有 ≤ now 的边界。
  _on_match       新吃单(takerOrderId 变化)的第一笔成交进入前,记下被打一侧的最优 K 档(吃单到达前的盘口)。
  on_sweep        引擎 _flush 收齐一张吃单后的回调(recorder 接口):总张数、笔数、首末 tick。
吃单口径  引擎扫单 = 同一 takerOrderId 的全部成交,成对打印(公开成交价 ≠ 挂单价)按引擎假设 H4 剔除(skip_paired=True),
          未见过 open 且公开成交流里没有价的成交也不计。成对打印数 / 张数写进 meta(登记表 EC-06)。
用法  python l3_extract.py <sym> <YYYYMMDD> <HH>   → data/step01/<sym>/<day>_<hh>.npz
"""
import bisect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
import engine_bridge as B          # noqa: E402
import ladder_store as LS          # noqa: E402

L, E = B.L, B.E
OUT = os.path.join(B.REPRO, "data", "step01")


class ExtractSim(L.L3Sim):
    """L3Sim + 有序价位键表(求最优 K 档)+ ladder 记录器。撮合逻辑全部仍由引擎执行。"""

    def __init__(self, sym, trade_ticks, t_from, t_to):
        super().__init__(sym, L.Latency(fixed_ms=0.0), agents=[], recorder=self, trade_ticks=trade_ticks)
        self.keys = ([], [])
        self.w = LS.LadderWriter("l3", sym)
        self._pre = None            # 当前吃单到达前的 ladder
        self._pre_taker = None
        self._n_open = 0
        # 只记录交易所时间落在本小时 [t_from, t_to) 的边界与吃单(EC-16):引擎先用上一小时末尾 300 s 预热,预热 120 s 后 ready 即为真,
        # 不加门会把上一小时最后约 180 s 再记一遍;文件按采集机本地时间切分,首尾也可能混入邻小时的消息。
        self.t_from, self.t_to = t_from, t_to
        self.n_sweep_outside = 0

    def _in_window(self, ts):
        return self.t_from <= ts < self.t_to

    # ---- 盘口最优 n 档(占用价位,由优到劣)
    def levels(self, side, n):
        s, ks = self.touch.size[side], self.keys[side]
        out = []
        if side == 0:
            j = len(ks) - 1
            while j >= 0 and len(out) < n:
                q = s.get(ks[j], 0)
                if q > 0:
                    out.append((ks[j], q))
                j -= 1
        else:
            j = 0
            while j < len(ks) and len(out) < n:
                q = s.get(ks[j], 0)
                if q > 0:
                    out.append((ks[j], q))
                j += 1
        return out

    def _track(self, side, tick):
        ks = self.keys[side]
        i = bisect.bisect_left(ks, tick)
        if i == len(ks) or ks[i] != tick:
            ks.insert(i, tick)
        self._n_open += 1
        if self._n_open >= 200_000:
            self._n_open = 0
            for sd in (0, 1):
                sz = self.touch.size[sd]
                self.keys[sd][:] = sorted(k for k in self.keys[sd] if sz.get(k, 0) > 0)

    # ---- 引擎挂钩
    def _advance(self, now):
        if self.ready:
            if self.w.next_bnd is None:
                # 第一个边界 = max(整点, ≥ now 的下一个网格点):预热完成在整点前 → 从整点起记;预热完成在整点后(段首无上一小时)→ 从就绪后起记,不回填
                g = LS.GRID_MS * 1_000_000
                start = max(self.t_from, -(-now // g) * g)
                gd = LS.DEEP_MS * 1_000_000
                self.w.next_bnd, self.w.next_deep = start, -(-start // gd) * gd
            if self.w.next_bnd < self.t_to:
                self.w.on_time(min(now, self.t_to - 1), self.levels)      # 不记 ≥ t_to 的边界(属于下一小时)
        super()._advance(now)

    def _on_open(self, d, seq):
        self._track(0 if d["side"] == "buy" else 1, L.to_tick(d["price"]))
        super()._on_open(d, seq)

    def _on_match(self, d, seq, ts):
        if self._sweep_taker is None and self.ready:
            tk = d["takerOrderId"]
            if tk != self._pre_taker:
                hit = 1 if d["side"] == "buy" else 0       # 吃单买 → 打卖单一侧
                self._pre, self._pre_taker = self.levels(hit, LS.K), tk
        super()._on_match(d, seq, ts)

    def _reset(self):
        super()._reset()
        self.keys = ([], [])
        self.w.next_bnd = None      # 断流后盘口重建,边界从预热结束后重新记

    # ---- recorder 接口
    def on_bbo(self, ts, bb, ba, bsz, asz):
        pass

    def on_sweep(self, ts, maker_side, sweep):
        if not self.ready:
            return
        if not self._in_window(ts):
            self.n_sweep_outside += 1
            return
        vol = sum(s for _, s, _ in sweep)
        taker_side = 1 - maker_side                       # maker_side 0 = 买单被打 → 吃单卖
        pre = self._pre if self._pre_taker == self._sweep_taker else []
        self.w.on_sweep(ts, taker_side, vol, len(sweep), sweep[0][0], sweep[-1][0], pre or [])


if __name__ == "__main__":
    sym, day, hh = sys.argv[1:4]
    B.patch_engine(sym)
    t_from = E.P.hour_start_ns(day, hh)
    t_to = t_from + 3_600 * 1_000_000_000
    sim = ExtractSim(sym, E.P.load_trade_ticks(day, [hh], sym), t_from, t_to)
    E.run_hours(sim, day, [hh], prewarm_s=300)
    r = sim.w.save(os.path.join(OUT, sym, f"{day}_{hh}.npz"), day=day, hh=hh, breaks=sim.breaks, t_from=t_from, t_to=t_to,
                   sweeps_outside_window=sim.n_sweep_outside,
                   paired_n=sim.paired_n, paired_qty=sim.paired_qty, tick=B.CONTRACTS[sym]["tick"], mult=B.CONTRACTS[sym]["mult"])
    print(f"{sym} {day} {hh}: bnd={r['n_bnd']:,} sweeps={r['n_sw']:,} outside={sim.n_sweep_outside} deep={r['n_deep']} breaks={sim.breaks} paired={sim.paired_n} EXTRACT_DONE", flush=True)
