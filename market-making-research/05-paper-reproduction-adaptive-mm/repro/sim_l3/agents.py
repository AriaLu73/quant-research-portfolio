"""Step 14 —— 把 Part A 的 P1 目录策略与 Step 13 的 P2 策略接到引擎 l3sim 的 agent 鸭子接口(orders / on_event / on_fill / on_break)。

与论文忠实回测的区别:成交由引擎按 L3 进簿序号精确排队(ahead0 = 进簿时同价前方量,ahead = 存活期间前方量),固定延迟 Latency(fixed_ms=L),post-only。
决策节奏  每个 Δt 边界(交易所时间)决策一次:算 (L⁺, L⁻)[及 e] → 目标 bid/ask tick;与当前挂单不同则撤旧挂新(改价 = 放弃队列位置,记录放弃的 ahead 与新单 ahead0);相同则保留(队列位置不变)。
状态     mid、g 状态、点差桶由引擎盘口与引擎回调里的成交流即时维护:1^± 指标按"本区间内是否有该方向吃单打到盘口"(引擎 recorder.on_sweep)。
市价单   P2Agent 的 e ≠ 0:按附录第 3 条 P2 字面口径,在 t_k + L 时刻以引擎当时重建的对手最优价成交 + taker 费(用 sim.place 以对手价下单无法保证成交,改为
         在延迟后直接按 touch 结算并计入账本;不假设他人对我方市价单作反应)。
记录     每张单:born、rest_at、side、tick、size、ahead0、ahead 轨迹末值、结局(filled / canceled / lost)、成交时 ahead、进簿到成交时间、是否改价撤单与放弃的 ahead。
"""
import numpy as np


class _Base:
    def __init__(self, name, V_LO, dt_ms, g, edges=None, fee_take_ticks=0.0, lat_ms=1.8, rebate_ticks=0.0):
        self.name, self.V_LO, self.dt_ns, self.g = name, int(V_LO), dt_ms * 1_000_000, g
        self.edges = None if edges is None else np.asarray(edges)
        self.fee, self.lat_ms, self.rebate = fee_take_ticks, lat_ms, rebate_ticks   # Step 15:maker 返佣 tick/张
        self.orders = []
        self.live = [None, None]          # 当前挂单 [bid, ask]
        self.hist_p, self.hist_m = [], []  # 最近区间的 1^±(最新在前)
        self.cur_ind = [False, False]     # 本区间内是否已见买 / 卖吃单
        self.next_bnd = None
        self.k = 0                        # 区间序号(Part A:当日;Part B:段内)
        self.W, self.I = 0.0, 0.0
        self.records, self.fills, self.mos = [], [], []
        self.n_breaks = 0
        self.pending_mo = []              # (exec_at, e)

    # ---- 引擎回调
    def on_break(self, sim, ts):
        self.n_breaks += 1
        for o in self.live:
            if o is not None:
                self._close(o, "lost")
        self.live = [None, None]

    def on_fill(self, sim, o, qty, ts, sweep_qty):
        px = o.tick
        if o.side == 1:
            self.W += px * qty; self.I -= qty
        else:
            self.W -= px * qty; self.I += qty
        self.W += self.rebate * qty
        self.fills.append((ts, o.side, o.tick, qty, o.ahead0 if o.ahead0 is not None else -1, o.ahead if o.ahead is not None else -1,
                           ts - o.rest_at, sweep_qty, o.level0 if o.level0 is not None else -99, o.born))
        if o.left == 0:
            self._close(o, "filled")
            if self.live[o.side] is o:
                self.live[o.side] = None

    def on_sweep(self, ts, maker_side, sweep):
        """由适配器(recorder 链)转发:吃单方向 = 1 − maker_side。"""
        self.cur_ind[1 - maker_side] = True

    # ---- 内部
    def _close(self, o, outcome):
        self.records.append((o.born, o.rest_at, o.side, o.tick, o.size, o.ahead0 if o.ahead0 is not None else -1,
                             o.ahead if o.ahead is not None else -1, {"filled": 1, "canceled": 2, "lost": 3}[outcome], o.size - o.left,
                             o.level0 if o.level0 is not None else -99))

    def _state(self, sim):
        bb, ba = sim.best(0), sim.best(1)
        if bb is None or ba is None:
            return None
        if len(self.hist_p) < self.g.lags:
            return None
        s = self.g.encode(self.hist_p, self.hist_m)
        return bb, ba, s

    def _requote(self, sim, ts, side, tick):
        o = self.live[side]
        if o is not None and o.state in ("pending", "live") and o.left > 0:
            if o.tick == tick:
                return
            # 改价:撤旧(记录放弃的队列位置)
            self.records_requote.append((ts, side, o.tick, tick, o.ahead if o.ahead is not None else -1, o.ahead0 if o.ahead0 is not None else -1))
            sim.cancel(o, ts)
            self._close(o, "canceled")
        self.live[side] = sim.place(self, side, tick, self.V_LO, ts, tag=f"{self.name}:{'bid' if side == 0 else 'ask'}")

    def _boundary(self, sim, ts):
        """到达 Δt 边界:收区间指标、推进状态、做决策。"""
        self.hist_p.insert(0, self.cur_ind[0]); self.hist_m.insert(0, self.cur_ind[1])
        del self.hist_p[self.g.lags + 1:]; del self.hist_m[self.g.lags + 1:]
        self.cur_ind = [False, False]
        self.k += 1

    def on_event(self, sim, ts):
        if self.next_bnd is None:
            self.next_bnd = (ts // self.dt_ns + 1) * self.dt_ns
            self.records_requote = []
            return
        # 延迟后的市价单结算
        while self.pending_mo and self.pending_mo[0][0] <= ts:
            exec_at, e, seg = self.pending_mo.pop(0)
            bb, ba = sim.best(0), sim.best(1)
            if bb is None or ba is None:
                self.pending_mo.insert(0, (exec_at, e, seg)); break
            px = ba if e > 0 else bb
            self.W -= e * px + self.fee * abs(e); self.I += e
            self.mos.append((ts, e, px, seg, (bb + ba) / 2.0, ba - bb))
        while ts >= self.next_bnd:
            self._boundary(sim, ts)
            self.next_bnd += self.dt_ns
        # 决策只在边界后的第一条消息做一次
        if getattr(self, "_decided_k", -1) != self.k:
            self._decided_k = self.k
            st = self._state(sim)
            if st is None:
                return
            self.decide(sim, ts, *st)

    def decide(self, sim, ts, bb, ba, s):
        raise NotImplementedError


class PaperPolicyAgent(_Base):
    """Part A 的 P1 目录策略(鞅版 / 非鞅版):每个 Δt 边界按 (k, g, I) 查 Catalog。k 以当日 UTC 00:00 起算。"""

    def __init__(self, name, cat, g, V_LO, dt_ms, day_start_ns, use_drift=False, **kw):
        super().__init__(name, V_LO, dt_ms, g, **kw)
        self.cat, self.use_drift, self.day0 = cat, use_drift, day_start_ns
        self.mids = []

    def decide(self, sim, ts, bb, ba, s):
        import bellman as BM
        mid2 = bb + ba
        self.mids.append(mid2 / 2.0)
        dh = (self.mids[-1] - self.mids[-6]) / 5.0 if (self.use_drift and len(self.mids) >= 6) else 0.0
        k = int((ts - self.day0) // self.dt_ns)
        k = min(max(k, 0), self.cat.N)
        Lp, Lm = BM.optimal_L(self.cat, k, s, self.I, dh)
        bt, at, flag = BM.to_quotes(mid2, Lp, Lm)
        self._requote(sim, ts, 0, bt); self._requote(sim, ts, 1, at)


class P2Agent(_Base):
    """Step 13 的 P2 策略:300 s 段,段末以市价清算(延迟后按 touch 结算 + 费),段间库存归零。"""

    def __init__(self, name, q, g, V_LO, dt_ms, day_start_ns, seg_s=300, **kw):
        super().__init__(name, V_LO, dt_ms, g, edges=q.edges, **kw)
        self.q, self.day0, self.n_seg = q, day_start_ns, int(round(seg_s * 1000 / dt_ms))
        self.segments = []
        self.seg_start_W = 0.0

    def decide(self, sim, ts, bb, ba, s):
        import bellman as BM
        k_abs = int((ts - self.day0) // self.dt_ns)
        k_in = k_abs % self.n_seg
        seg = k_abs // self.n_seg
        if k_in == 0 and k_abs > 0 and getattr(self, "_last_seg", -1) != seg:
            # 段末清算:上一段结束时的库存以市价平掉(经延迟),记在上一段
            self._last_seg = seg
            if self.I != 0:
                self.pending_mo.append((ts + int(self.lat_ms * 1_000_000), -self.I, seg - 1))
            self.segments.append((ts, self.W - self.seg_start_W, self.I))
            self.seg_start_W = self.W
        sidx = int(np.searchsorted(self.edges, ba - bb, side="left"))
        q = self.q
        j = int(np.clip(np.round((self.I + q.y[-1]) / q.dy), 0, q.Y - 1))
        e = int(q.pol["e"][min(k_in, q.pol["e"].shape[0] - 1), j, sidx, s]) * q.dy
        if e:
            self.pending_mo.append((ts + int(self.lat_ms * 1_000_000), e, seg))
            j = int(np.clip(np.round((self.I + e + q.y[-1]) / q.dy), 0, q.Y - 1))
        kk = min(k_in, q.pol["Lp"].shape[0] - 1)
        Lp, Lm = float(q.L[q.pol["Lp"][kk, j, sidx, s]]), float(q.L[q.pol["Lm"][kk, j, sidx, s]])
        bt, at, flag = BM.to_quotes(bb + ba, Lp, Lm)
        self._requote(sim, ts, 0, bt); self._requote(sim, ts, 1, at)
