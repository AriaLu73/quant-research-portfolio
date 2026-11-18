#!/usr/bin/env python3
"""research7 价位汇总盘口(L2)+ 逐笔成交 上的撮合仿真器:没有订单号时的排队位置推断。

用途      2026-08-26 … 09-24 只有 L2 与成交(没有逐笔委托)。用户 2026-10-08 裁决:没有逐笔委托就用 L2 模拟。
          本文件用与 l3sim.L3Sim 相同的策略接口(place / cancel / best / level_size;on_event / on_fill / on_break),
          同一个策略类可以不改一行地在两种仿真器上运行;推断的误差用有逐笔委托的 10-01、10-02 标定(l2_vs_l3.py)。
所属阶段  阶段 0 的补充(研究基础设施);研究二第 4 条"只有快照数据时,必须研究队列位置的推断方法及其误差"的实现载体。
对应公式  不对应报价公式中的某一项。
输入      l2_prep.py 生成的事件数组(ts, kind, side, tick, size)。
变量与 <符号表> 的对应  side 0 = 买入报价(P_b)一侧,1 = 卖出报价(P_a)一侧;tick = 价格 / TICK;size 单位张。
排队位置的推断(每张我方订单维护 ahead = 估计排在我方前面的张数)
  进簿    ahead = 进簿瞬间该价位的 L2 总量(全部排在我方前面;这一步是精确的)。
  成交    吃单打到我方价位 v 张:先消耗 ahead,超出的部分成交给我方(不超过我方剩余);
          吃单成交价比我方价位更差(穿过我方):我方先于那一档成交。
  撤单    该价位 L2 数量减少、且不是成交造成的部分 = 别人撤单 c 张。它们在我方前面还是后面,L2 看不出来 → 规则参数 cancel_rule:
            "prop"   按比例:前方减少 c × ahead / (该价位总量)          —— 撤单在队列中均匀分布
            "back"   后方优先:先减后方,后方不够才减前方                 —— 对我方最不利(排队前进最慢)
            "front"  前方优先:先减前方                                   —— 对我方最有利
          三条规则的依据与取舍见 docs/research7/阶段0b_L2仿真标定.md(用逐笔委托的真实排队比较后选定,不是凭经验)。
  加单    该价位 L2 数量增加:新单排在我方后面,ahead 不变。
依赖的假设  H1(价格优先时间优先)、H2(我方不影响他人,只先拿走吃单量)、H3(延迟模型)同 l3sim;
          H4'(成对打印)没有订单号时改用价格判别:吃单买入的成交价低于当时卖一、或吃单卖出的成交价高于当时买一,
               说明这笔成交不是按盘口成交的,不分给我方;
          H6  成交与它造成的 L2 数量减少带同一个交易所时间戳(毫秒),据此把"成交减少"与"撤单减少"分开;对不上的部分当作撤单。
"""
import heapq

import numpy as np

import l3sim as L

K_TRADE, K_LEVEL, K_RESET, K_GAP = 0, 1, 2, 3
# 成交与其 L2 减少的配对窗口:两者时间戳相同(同一毫秒);留 5 毫秒余量。
# ASSUMPTION(数据核对见标定文档:配对不上的成交量占比)。
PAIR_NS = 5 * L.MS


class L2Load:
    """延迟模型用的负载:ts 之前 100 毫秒内本合约的 L2 + 成交事件条数(只用过去的数据)。
    100 毫秒与 l3_prep.Load 相同(docs/research6/step1 第 2 节的口径,ASSUMPTION)。"""
    WIN_NS = 100 * L.MS

    def __init__(self, ts):
        self.ts = ts

    def count(self, t):
        return int(np.searchsorted(self.ts, t, side="right") - np.searchsorted(self.ts, t - self.WIN_NS, side="right"))


class L2Sim:
    """L2 事件循环。策略接口与 l3sim.L3Sim 相同。"""

    def __init__(self, sym, latency, agents=(), recorder=None, cancel_rule="prop", cross_fill=False):
        assert cancel_rule in ("prop", "back", "front")
        self.sym, self.lat, self.agents, self.rec, self.rule = sym, latency, list(agents), recorder, cancel_rule
        self.cross_fill = cross_fill
        self.touch = L.Touch()
        self.pending = []                 # 未进簿的我方订单(堆,按 rest_at)
        self._n = 0
        self._ts = 0
        self.ready = False                # 盘口是否可信(重置之后为真,空档期间为假)
        self.breaks = 0
        self.paired_n = self.paired_qty = 0
        self.unpaired_qty = self.trade_qty = 0   # 成交里没能与 L2 减少配上对的张数 / 全部成交张数(H6 的核对)
        self._pend_trade = {}             # (side, tick) -> [待与 L2 减少配对的成交张数, 最近一笔的时间]
        self._bbo = None
        self._hold = -1                   # 最近一次重置的时间戳

    # ------------------------------------------------------------------ 策略调用(与 L3Sim 相同)
    def place(self, agent, side, tick, size, now, tag=None):
        lat = getattr(agent, "lat", None) or self.lat
        o = L.SimOrder(side, tick, size, now, now + lat.delay(now, "open"), tag)
        o.lat = lat
        agent.orders.append(o)
        self._n += 1
        heapq.heappush(self.pending, (o.rest_at, self._n, o, agent))
        return o

    def cancel(self, order, now):
        if order.cancel_at is None and order.state in ("pending", "live"):
            order.cancel_at = now + (order.lat or self.lat).delay(now, "cancel")

    def best(self, side):
        return self.touch.best(side)

    def level_size(self, side, tick):
        return max(self.touch.size[side].get(tick, 0), 0)

    # ------------------------------------------------------------------ 我方订单随时间推进
    def _advance(self, now):
        while self.pending and self.pending[0][0] <= now:
            _, _, o, agent = heapq.heappop(self.pending)
            if o.cancel_at is not None and o.cancel_at <= o.rest_at:
                o.state = "cancelled"
                continue
            other = self.touch.best(1 - o.side)
            if other is not None and ((o.tick >= other) if o.side == 0 else (o.tick <= other)):
                o.state = "rejected"                                   # 只挂不吃:会成交则拒单(同 l3sim)
                continue
            own_best = self.touch.best(o.side)
            o.ahead0 = o.ahead = float(self.level_size(o.side, o.tick))   # 进簿瞬间该价位的全部数量都在我方前面
            o.level0 = None if own_best is None else ((own_best - o.tick) if o.side == 0 else (o.tick - own_best))
            o.mark = 0
            o.state = "live"
        for agent in self.agents:
            for o in agent.orders:
                if o.state == "live" and o.cancel_at is not None and o.cancel_at <= now:
                    o.state = "cancelled"
            if len(agent.orders) > 64:
                agent.orders = [o for o in agent.orders if o.state in ("pending", "live")]

    def _fill(self, agent, o, f, ts, sweep_qty):
        o.left -= f
        o.fills.append((ts, f))
        if o.left == 0:
            o.state = "filled"
        agent.on_fill(self, o, f, ts, sweep_qty)

    def _sweep(self, ts, side, rows):
        """一张吃单(同一毫秒、同一方向的连续成交行)打到 side 一侧。rows: [(tick, 张数)],由好到差。"""
        tot = sum(q for _, q in rows)
        for agent in self.agents:
            mine = [o for o in agent.orders if o.side == side and o.state == "live" and o.left > 0
                    and o.rest_at <= ts and (o.cancel_at is None or ts < o.cancel_at)]
            if not mine:
                continue
            buy = side == 0
            mine.sort(key=lambda o: (-o.tick if buy else o.tick, o.rest_at))
            remaining, k = tot, 0
            for tick, q in rows:
                # 价格比这一档更好的我方订单:先于这一档成交
                while k < len(mine) and remaining > 0 and ((mine[k].tick > tick) if buy else (mine[k].tick < tick)):
                    f = min(mine[k].left, remaining)
                    remaining -= f
                    self._fill(agent, mine[k], f, ts, tot)
                    k += 1
                if remaining <= 0:
                    break
                avail = min(q, remaining)                             # 这一档真实成交的量
                j = k
                while j < len(mine) and mine[j].tick == tick and avail > 0:
                    o = mine[j]
                    a = min(o.ahead, avail)                           # 先消耗排在我方前面的量
                    o.ahead -= a
                    avail -= a
                    remaining -= a
                    f = int(min(o.left, avail))                       # 超出的部分轮到我方(部分成交)
                    if f > 0:
                        avail -= f
                        remaining -= f
                        self._fill(agent, o, f, ts, tot)
                    j += 1
                remaining -= min(avail, remaining)                    # 排在我方后面的真实挂单拿走其余
        if self.rec is not None and self.ready:
            self.rec.on_sweep(ts, side, [(t, q, 0) for t, q in rows])

    def _level(self, ts, side, tick, new):
        """某价位的新总量。区分成交减少与撤单减少,并按 cancel_rule 更新我方订单的前方数量。"""
        old = self.level_size(side, tick)
        if new > 0:
            self.touch.clear_through(side, tick)                      # 新消息为准:对侧与它交叉的残留价位清掉(购买数据有漏删除)
        if new < old:
            d = old - new
            p = self._pend_trade.get((side, tick))
            if p is not None:
                m = min(d, p[0]) if ts - p[1] <= PAIR_NS else 0       # 这部分减少是成交造成的(已在 _sweep 里处理过)
                p[0] -= m
                if p[0] <= 0 or ts - p[1] > PAIR_NS:
                    self.unpaired_qty += max(p[0], 0)
                    del self._pend_trade[(side, tick)]
                d -= m
            if d > 0:                                                 # 撤单 d 张
                for agent in self.agents:
                    for o in agent.orders:
                        if o.state == "live" and o.side == side and o.tick == tick and o.ahead > 0:
                            behind = max(old - o.ahead, 0.0)
                            rule = getattr(agent, "cancel_rule", None) or self.rule   # 策略可自带规则(标定时并列比较)
                            if rule == "prop":
                                o.ahead -= d * o.ahead / old if old > 0 else 0.0
                            elif rule == "back":
                                o.ahead -= max(d - behind, 0.0)
                            else:
                                o.ahead -= min(d, o.ahead)
                            o.ahead = max(o.ahead, 0.0)
        elif new > old and self.agents and self.cross_fill:   # 默认关闭,理由同 l3sim._on_open(2026-10-08)
            # 对侧新增的量若等于或穿过我方挂单价:真实撮合里它会先与我方成交(我方挂在买一卖一之间时才会发生)
            for agent in self.agents:
                hit = [o for o in agent.orders if o.side != side and o.state == "live" and o.left > 0
                       and (o.cancel_at is None or ts < o.cancel_at) and ((o.tick >= tick) if o.side == 0 else (o.tick <= tick))]
                if hit:
                    hit.sort(key=lambda o: (-o.tick if o.side == 0 else o.tick, o.rest_at))
                    rem = new - old
                    for o in hit:
                        f = min(o.left, rem)
                        if f <= 0:
                            break
                        rem -= f
                        self._fill(agent, o, f, ts, new - old)
        self.touch.add(side, tick, new - old)
        # 我方订单的前方数量不可能超过该价位现有总量
        if new < old:
            for agent in self.agents:
                for o in agent.orders:
                    if o.state == "live" and o.side == side and o.tick == tick and o.ahead > new:
                        o.ahead = float(new)

    def _void(self, ts):
        """重置或空档:我方订单作废(真实系统里应撤单重来)。"""
        self.pending = []
        for agent in self.agents:
            for o in agent.orders:
                if o.state in ("pending", "live"):
                    o.state = "lost"
            agent.orders = []
            agent.on_break(self, ts)

    # ------------------------------------------------------------------ 主循环
    def run(self, ev, t_from=None, t_to=None):
        """ev: l2_prep 的五个数组(dict 或 npz)。t_from / t_to(纳秒):只在这段时间内调用策略与记录器
        (之前的事件照常用来建盘口)。"""
        ts_a, kind_a, side_a, tick_a, size_a = (ev[k] for k in ("ts", "kind", "side", "tick", "size"))
        n = len(ts_a)
        CH = 2_000_000                                                # 分块转成 Python 列表,控制内存
        i0 = 0
        sw_rows, sw_ts, sw_side = [], 0, 0
        while i0 < n:
            i1 = min(i0 + CH, n)
            if t_to is not None and ts_a[i0] > t_to:
                break
            T, K, S, P, Q = (a[i0:i1].tolist() for a in (ts_a, kind_a, side_a, tick_a, size_a))
            for ts, k, s, p, q in zip(T, K, S, P, Q):
                self._ts = ts
                # 重置那一毫秒里盘口还在逐行装入,不调用策略
                active = self.ready and ts > self._hold and (t_from is None or ts >= t_from) and (t_to is None or ts <= t_to)
                if sw_rows and (k != K_TRADE or ts != sw_ts or s != sw_side):
                    self._advance(sw_ts)
                    self._sweep(sw_ts, sw_side, sw_rows)              # 上一张吃单的成交收齐
                    sw_rows = []
                if k == K_TRADE:
                    if not self.ready:
                        continue
                    self.trade_qty += q
                    b = self.touch.best(s)
                    # H4':不是按盘口成交的打印(成交价在同侧最优价的"里面"),不分给我方
                    if b is not None and ((p > b) if s == 0 else (p < b)):
                        self.paired_n += 1
                        self.paired_qty += q
                        continue
                    if not sw_rows:
                        sw_ts, sw_side = ts, s
                    sw_rows.append((p, q))
                    e = self._pend_trade.get((s, p))
                    if e is None:
                        self._pend_trade[(s, p)] = [q, ts]
                    else:
                        e[0] += q
                        e[1] = ts
                    continue
                self._advance(ts)
                if k == K_LEVEL:
                    self._level(ts, s, p, q)
                elif k == K_RESET:
                    self.breaks += 1
                    self._void(ts)
                    self.touch = L.Touch()
                    self._pend_trade.clear()
                    self.ready = True                                 # 紧随其后的是整本盘口
                    self._hold = ts
                elif k == K_GAP:
                    self._void(ts)
                    self.ready = False
                if active:
                    if self.rec is not None:
                        bb, ba = self.touch.best(0), self.touch.best(1)
                        if bb is not None and ba is not None and bb < ba:
                            cur = (bb, ba, self.touch.size[0][bb], self.touch.size[1][ba])
                            if cur != self._bbo:
                                self._bbo = cur
                                self.rec.on_bbo(ts, *cur)
                    for agent in self.agents:
                        agent.on_event(self, ts)
            i0 = i1
        if sw_rows:
            self._advance(sw_ts)
            self._sweep(sw_ts, sw_side, sw_rows)
