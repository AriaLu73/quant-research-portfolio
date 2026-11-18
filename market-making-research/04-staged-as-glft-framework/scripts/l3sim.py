#!/usr/bin/env python3
"""research7 逐笔委托(L3)撮合仿真器。

用途      把假想的我方限价单放进 KuCoin 公开逐笔委托流(/contractMarket/level3v2)里重放,按真实的价格优先、时间优先
          判定它排在谁后面、什么时候成交、成交多少。只做回测研究,不连接交易所,不下任何真实订单。
所属阶段  阶段 0(研究基础设施);此后每个阶段的回测都通过本文件撮合。不属于任何一个研究模块。
对应公式  不对应报价公式中的任何一项;它是 <回测与统计规范> 第 1 条要求的五项模拟的实现:
          队列位置(SimOrder.mark / ahead)、前方撤单(_on_leave)、延迟(Latency)、部分成交(allocate)、手续费(fees.py)。
变量与 <符号表> 的对应
          side      0 = 买入报价(对应 P_b),1 = 卖出报价(对应 P_a)
          tick      价格 / TICK 取整后的整数(P = tick * TICK)
          size      合约张数(V = size * MULT,单位 BTC)
          mid       (bb + ba) / 2 * TICK = S_t
时间      全部用交易所时间戳 data.ts(纳秒,实际精度 1 毫秒)。采集机是家用电脑不是机房,本机接收时间不能用
          (来源:项目记录 memory kucoin-l3-recording)。
依赖的假设(每条都在 docs/research7/阶段0_记录.md 的"仿真假设"表里登记)
  H1 同一价位按进簿先后成交(价格优先、时间优先)。交易所官方撮合文件未核对 → UNKNOWN;10-02 实盘单的重放用来检验它。
  H2 我方订单不改变别人的行为;唯一的影响是先拿走吃单方的量(吃单方总量不变)。
  H3 行情到我方、决策、下单到进簿合计的延迟由 Latency 给出(用户 2026-10-03 裁决的回测口径)。
  H4 成交价与挂单方在簿里的价格不一致的成交(成对打印)不走盘口优先级,不分给我方(见 _on_match)。
"""
import gzip
import heapq
import os
import zlib

import orjson

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 原始数据位置(项目记录:data/README.md 与 memory usdc-line-audit;自采,采集已于 2026-10-02 叫停)
L3_DIR = {"XBTUSDTM": os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt"),
          "XBTUSDCM": os.path.join(ROOT, "data", "research5", "usdc_pairs")}
TRD_DIR = os.path.join(ROOT, "data", "research5", "usdc_pairs")

# 合约规格。来源:docs/research6/step1_交易环境参数表(KuCoin 公开合约接口,取得日期 2026-10-02);
# 核对:data/research5/kucoin_contracts_20261002.json(KuCoin 公开接口 /api/v1/contracts/active 的存档,2026-10-02)。
TICK = 0.1            # 美元 / 最小价格变动(XBTUSDTM 与 XBTUSDCM 相同)
MULT = {"XBTUSDTM": 0.001, "XBTUSDCM": 0.0001}   # BTC / 张
MS = 1_000_000        # 纳秒 / 毫秒(单位换算:毫秒 → 纳秒 乘以 MS)
NS = 1_000_000_000    # 纳秒 / 秒

# 冷启动预热:文件开头看不到此前已在簿里的订单,盘口要等这些旧单被替换掉才可信。
# 120 秒沿用项目既有回放的设定(scripts/research5/maker_families.py WARM_NS),属于 ASSUMPTION:
# 理由是最优价附近的挂单寿命中位数为几十毫秒到几秒(memory maker-families-mf1),120 秒足够盘口附近换完一遍;
# 深处的旧单换不完,它们成交时按"比我方早"处理(见 _on_match),不会让我方多成交。
WARM_NS = 120 * NS
# 序号跳变超过 2 视为丢消息。来源:2026-10-06 数据完整性核对(docs/research5/experiments.md):
# 成交与其后的 done 之间固定缺 1 个不对外推送的内部序号,所以相邻序号差 2 是正常的,大于 2 才是断流。
SN_GAP_OK = 2


def to_tick(price):
    """价格(美元,字符串或数)→ 整数 tick。单位换算:美元 → tick,除以 TICK 后四舍五入。"""
    return int(round(float(price) / TICK))


class Latency:
    """从"事件发生的交易所时间"到"我方因此发出的新单进簿 / 撤单生效"的总延迟。

    口径  用户 2026-10-03 裁决(memory latency-figures-authoritative;docs/research6/step1 第 2 节):
          正常时 1.8 毫秒(行情 0.3 + 下单 1.5),交易所拥堵时 50 毫秒。下单与撤单用同一数值。
    拥堵  XBTUSDTM + XBTUSDCM 两个合约的公开逐笔消息在"过去 100 毫秒"内 ≥ 744 条即判拥堵。
          744 = 2026-10-02 19:00–21:03 UTC 负载最忙 20% 的分界(l3_congestion.py 的结果),属于 ASSUMPTION;
          只用当前时刻以前的消息,没有用到未来数据。
    输入  load: 由 l3_load.py 生成的"每毫秒累计消息数"对象;为 None 时全程按 normal_ms。
    """

    def __init__(self, load=None, normal_ms=1.8, busy_ms=50.0, busy_thr=744, fixed_ms=None):
        self.load = load
        self.normal = int(normal_ms * MS)     # 毫秒 → 纳秒
        self.busy = int(busy_ms * MS)         # 毫秒 → 纳秒
        self.thr = busy_thr
        self.fixed = None if fixed_ms is None else int(fixed_ms * MS)   # 敏感性分析用:全程固定延迟

    def delay(self, ts, kind="open"):
        """ts: 触发决策的事件时间(纳秒);kind: "open" 下单 / "cancel" 撤单(本类两者同值)→ 总延迟(纳秒)。"""
        if self.fixed is not None:
            return self.fixed
        if self.load is not None and self.load.count(ts) >= self.thr:
            return self.busy
        return self.normal


class EmpiricalLatency:
    """按交易所负载分档、从实盘实测分布里抽样的延迟(阶段 0 验收 T0-2 之后采用,取代两点模型)。

    数据  data/research7/latency_empirical.npz(scripts/research7/live_latency.py;2026-10-02 18:49–21:22 UTC
          实盘 3,330 次进簿、3,318 次撤单):每次的 [发出时刻的负载, 发出→生效 的毫秒数]。
    用法  delay(ts, kind) = lead_ms + 在"ts 时刻负载所在档"的实测样本里随机抽一个。
          lead_ms 是行情到我方的时间:策略由行情事件触发时取 0.3 ms(memory latency-figures-authoritative:行情 0.3 ms);
          从"引擎已发出"的时刻起算时取 0(实盘对账)。
    依赖的假设  ① 各次延迟相互独立(实盘里慢单成批出现,这里没有模拟,登记为局限);
                ② 这 2.5 小时的分布代表其它时段(只有这一段实盘数据,UNKNOWN);
                ③ 负载只用 ts 之前 100 毫秒的消息数,没有用到未来数据。
    随机数种子固定,结果可复现。
    """

    # 行情到达(交易所时间戳 → 包到我方机器)的实测分位数,毫秒:(累计概率, 毫秒)。
    # 来源:docs/research6/step1 第 2 节 S5(2026-10-02 18:15 UTC 机房抓包,BTC-USDT level2,7 分钟 16.7 万条):
    # p50 1.4、p90 5.6、p99 12.5、最大 26;最小值取网络往返 0.3(用户口径"行情 0.3 ms")。
    # 分位点之间按对数线性插值 —— ASSUMPTION(只有分位数,没有原始样本)。
    MD_QUANTILES = ((0.0, 0.3), (0.5, 1.4), (0.9, 5.6), (0.99, 12.5), (1.0, 26.0))

    def __init__(self, load, table, lead_ms=0.3, seed=0, md_jitter=False):
        import numpy as np
        self.load, self.lead = load, int(lead_ms * MS)                 # 毫秒 → 纳秒
        self.md_jitter = md_jitter                                     # True:行情到达时间按 MD_QUANTILES 抽样,取代固定的 lead_ms
        self._qp = [p for p, _ in self.MD_QUANTILES]
        self._ql = [__import__("math").log(v) for _, v in self.MD_QUANTILES]
        self.edges = [float(e) for e in table["edges"]]
        self.rng = np.random.default_rng(seed)
        self.samples = {}
        for kind in ("open", "cancel"):
            x = table[kind]
            b = np.searchsorted(self.edges, x[:, 0], side="right") - 1  # 每个样本所在的负载档
            self.samples[kind] = [np.sort(x[b == i, 1]) for i in range(len(self.edges))]

    def delay(self, ts, kind="open"):
        """ts: 起算时刻(纳秒);kind: "open" / "cancel" → 延迟(纳秒)。"""
        import bisect
        n = self.load.count(ts) if self.load is not None else 0
        i = max(bisect.bisect_right(self.edges, n) - 1, 0)
        pool = self.samples[kind][i]
        ms = float(pool[self.rng.integers(len(pool))])
        lead = self.lead
        if self.md_jitter:
            # 逆分布函数抽样:u ~ U(0,1),在相邻分位点之间对 log(毫秒) 线性插值
            u = float(self.rng.random())
            j = max(bisect.bisect_right(self._qp, u) - 1, 0)
            j = min(j, len(self._qp) - 2)
            w = (u - self._qp[j]) / (self._qp[j + 1] - self._qp[j])
            lead = int(__import__("math").exp(self._ql[j] * (1 - w) + self._ql[j + 1] * w) * MS)
        return lead + int(ms * MS)


class SimOrder:
    """我方的一张假想限价单。

    side / tick / size   方向、价位、下单张数
    left                 尚未成交的张数(部分成交后递减)
    born                 触发下单的事件时间(纳秒)
    rest_at              进簿时间 = born + 延迟;在此之前不能成交
    cancel_at            撤单生效时间;None = 没有撤。撤单在途期间仍可成交
    mark                 进簿瞬间盘口已处理到的最大公开序号:序号 ≤ mark 的同价位挂单排在我方前面(队列位置)
    ahead0 / ahead       进簿瞬间 / 当前 排在我方前面的同价位张数(只统计看得见的挂单;用于按队列位置分组)
    level0               进簿瞬间离同侧最优价几个 tick(0 = 加入最优价,负数 = 改善了最优价),用于按档位分组
    tag                  策略自己的标签(例如 "bid" / "ask" / 实盘订单号)
    """
    __slots__ = ("side", "tick", "size", "left", "born", "rest_at", "cancel_at", "mark", "ahead0", "ahead", "level0",
                 "tag", "state", "fills", "lat")

    def __init__(self, side, tick, size, born, rest_at, tag=None):
        self.side, self.tick, self.size, self.left = side, tick, size, size
        self.born, self.rest_at, self.cancel_at = born, rest_at, None
        self.mark, self.ahead0, self.ahead, self.level0 = None, None, None, None
        self.tag, self.state, self.fills, self.lat = tag, "pending", [], None


def allocate(sweep, mine, now):
    """把一张吃单(一次扫单)的真实成交分给我方挂单。实现的规则:价格优先、时间优先(假设 H1、H2)。

    sweep  [(挂单方 tick, 张数, 挂单方进簿序号)],按行情里的先后(就是真实的成交优先顺序);挂单方都在同一侧。
           进簿序号 = -1 表示没见过它的 open(比我方任何订单都早)。
    mine   我方在这一侧的订单(任意状态,函数内部筛选:已进簿、未撤销生效、还有剩余)。
    now    扫单时间(纳秒)。
    返回   [(订单, 成交张数)]。
    逻辑   吃单方的总量固定 = 真实成交量之和。按真实成交顺序往下走;走到某一笔真实成交之前,
           凡是价格比它好、或价格相同而它进簿比我方晚的我方订单,先成交(排在它前面)。
           我方拿走的量从吃单方总量里扣掉,所以排在后面的真实挂单会少成交(不重复计量)。
    """
    live = [o for o in mine if o.state == "live" and o.left > 0 and o.rest_at <= now and (o.cancel_at is None or now < o.cancel_at)]
    if not live or not sweep:
        return []
    buy = live[0].side == 0
    # 我方订单之间的优先级:价格好的在前,价格相同先进簿的在前
    live.sort(key=lambda o: (-o.tick if buy else o.tick, o.rest_at))
    remaining = sum(s for _, s, _ in sweep)        # 吃单方总量(张)
    out, k = [], 0
    for tick, size, mseq in sweep:
        while k < len(live) and remaining > 0:
            o = live[k]
            better = (o.tick > tick) if buy else (o.tick < tick)
            if better or (o.tick == tick and mseq > o.mark):   # 这笔真实挂单排在我方后面
                f = min(o.left, remaining)                      # 部分成交:吃单量不够就只成交一部分
                out.append((o, f))
                remaining -= f
                k += 1
            else:
                break
        if remaining <= 0:
            break
        remaining -= min(size, remaining)                       # 真实挂单拿走它的量
    return out


class Touch:
    """用每个价位的挂单张数维护买一 / 卖一(整数 tick)。堆 + 惰性删除。

    size[side][tick] = 该价位看得见的挂单总张数;best(side) 返回张数 > 0 的最优 tick,没有则 None。
    """

    def __init__(self):
        self.size = ({}, {})
        self.heap = ([], [])

    def add(self, side, tick, qty):
        s = self.size[side]
        if tick not in s:
            s[tick] = 0
            heapq.heappush(self.heap[side], -tick if side == 0 else tick)
        s[tick] += qty

    def sub(self, side, tick, qty):
        s = self.size[side]
        if tick in s:
            s[tick] -= qty

    def best(self, side):
        h, s = self.heap[side], self.size[side]
        while h:
            tick = -h[0] if side == 0 else h[0]
            if s.get(tick, 0) > 0:
                return tick
            heapq.heappop(h)          # 这个价位已经空了,丢掉
            s.pop(tick, None)
        return None

    def clear_through(self, side, tick):
        """side 侧在 tick 有新挂单进簿:对侧不可能还有等于或穿过它的挂单(否则早已成交)。
        若盘口里还留着这样的对侧价位,说明是丢消息留下的残单,清掉。"""
        o = 1 - side
        while True:
            b = self.best(o)
            if b is None or (b > tick if o == 1 else b < tick):
                return
            self.size[o][b] = 0


class L3Sim:
    """逐笔委托事件循环。一次遍历可以同时带多个互不影响的策略(agents),每个策略有自己的订单。

    策略接口(鸭子类型):
        agent.orders            list[SimOrder],由本类维护
        agent.on_event(sim, ts) 每条行情处理完之后调用(仅在预热结束后);在里面调 sim.place / sim.cancel
        agent.on_fill(sim, order, qty, ts, sweep_qty)   我方成交回调
        agent.on_break(sim, ts) 断流:我方订单全部作废(真实系统里应当撤单重来)
    记录器接口:recorder.on_bbo(ts, bb, ba, bsz, asz)、recorder.on_sweep(ts, maker_side, sweep) —— 可为 None。
    """

    def __init__(self, sym, latency, agents=(), recorder=None, own_ids=None, trade_ticks=None, skip_paired=True, cross_fill=False):
        self.sym, self.lat, self.agents, self.rec = sym, latency, list(agents), recorder
        self.book = {}                      # 订单号 → [side, tick, 剩余张数, 进簿序号]
        self.touch = Touch()
        self.own = own_ids or {}            # 实盘对账用:我方真实订单号 → 标签;这些订单不进盘口(见 _on_open)
        self.trade_ticks = trade_ticks or {}  # tradeId → 成交 tick(公开成交流),给没见过 open 的挂单方定价
        self.last_seq = -1                  # 已处理到的最大公开序号
        self.t_first = None                 # 本段数据的起点(预热从这里算)
        self.breaks = 0
        self.cross_fill = cross_fill        # True:新进簿的对侧订单穿过我方价位时算与我方成交(已弃用,见 _on_open)
        self.skip_paired = skip_paired      # True:成对打印不参与撮合(假设 H4)
        # 2026-10-11 审计后新增(默认关闭,不改变既有结果):挂单进簿不到 fresh_ns 就被打到的成交,视为"先挂后吃"的配对成交,
        # 不分给我方。依据:10-01 六个股票 / 大宗合约上,62–80% 的成交额打到的是进簿不到 5 毫秒的挂单(中位数 1–2 毫秒)——
        # 这种流是同一方先放一张挂单再立刻吃掉,它会挂在我方报价之内,不会来打我方的挂单;不剔除的话仿真会把它整个算给我们。
        self.fresh_ns = None
        self.fresh_n = self.fresh_qty = 0
        self.paired_n = self.paired_qty = 0 # 成对打印的笔数 / 张数(统计用)
        self.pending = []                   # 还没进簿的我方订单(堆,按 rest_at)
        self._n = 0                         # 堆里打破平局用的计数器
        self._sweep, self._sweep_taker, self._sweep_side, self._sweep_ts = [], None, None, 0
        self._bbo = (None, None, 0, 0)
        self.ready = False
        self._last_sn, self._ts = None, 0
        self.own_side = {k: v[0] for k, v in self.own.items()}
        self.own_tick = {k: v[1] for k, v in self.own.items()}

    # ------------------------------------------------------------------ 策略调用
    def place(self, agent, side, tick, size, now, tag=None):
        """策略在事件时间 now 决定下单。订单在 now + 延迟 时进簿(假设 H3),返回 SimOrder。"""
        lat = getattr(agent, "lat", None) or self.lat      # 策略可以自带延迟模型(例如不同的随机数种子)
        o = SimOrder(side, tick, size, now, now + lat.delay(now, "open"), tag)
        o.lat = lat
        agent.orders.append(o)
        self._n += 1
        heapq.heappush(self.pending, (o.rest_at, self._n, o, agent))
        return o

    def rest_now(self, agent, side, tick, size, tag=None):
        """实盘对账专用:让一张仿真订单在"当前这条行情"的位置立即进簿(进簿时刻取自交易所的真实记录,不走延迟模型)。"""
        o = SimOrder(side, tick, size, self._ts, self._ts, tag)
        own_best = self.touch.best(side)
        o.mark = self.last_seq
        o.ahead0 = o.ahead = self.level_size(side, tick)
        o.level0 = None if own_best is None else ((own_best - tick) if side == 0 else (tick - own_best))
        o.state = "live"
        agent.orders.append(o)
        return o

    def cancel(self, order, now):
        """策略在事件时间 now 决定撤单。now + 延迟 之前这张单仍可能成交(撤单在途)。"""
        if order.cancel_at is None and order.state in ("pending", "live"):
            order.cancel_at = now + (order.lat or self.lat).delay(now, "cancel")

    def best(self, side):
        return self.touch.best(side)

    def level_size(self, side, tick):
        return max(self.touch.size[side].get(tick, 0), 0)

    # ------------------------------------------------------------------ 内部:我方订单随时间推进
    def _advance(self, now):
        """把到 now 为止应当生效的事情做掉:新单进簿、撤单生效。"""
        while self.pending and self.pending[0][0] <= now:
            _, _, o, agent = heapq.heappop(self.pending)
            if o.cancel_at is not None and o.cancel_at <= o.rest_at:
                o.state = "cancelled"                     # 进簿之前撤单已生效
                continue
            other = self.touch.best(1 - o.side)
            # 只挂不吃(post-only):进簿时若会与对侧成交,交易所拒单。
            # 来源:实盘日志里 post_only 单的行为(项目记录 uh-live);官方文件未核对 → 登记为 UNKNOWN。
            if other is not None and ((o.tick >= other) if o.side == 0 else (o.tick <= other)):
                o.state = "rejected"
                continue
            own_best = self.touch.best(o.side)
            o.mark = self.last_seq                         # 此刻已在簿里的同价位订单都排在我方前面
            o.ahead0 = o.ahead = self.level_size(o.side, o.tick)
            o.level0 = None if own_best is None else ((own_best - o.tick) if o.side == 0 else (o.tick - own_best))
            o.state = "live"
        for agent in self.agents:
            for o in agent.orders:
                if o.state == "live" and o.cancel_at is not None and o.cancel_at <= now:
                    o.state = "cancelled"
            if len(agent.orders) > 64:                     # 清掉已结束的订单,控制内存
                agent.orders = [o for o in agent.orders if o.state in ("pending", "live")]

    def _flush(self):
        """一张吃单的成交收齐了:分给各策略的我方挂单。"""
        if self._sweep:
            tot = sum(s for _, s, _ in self._sweep)
            for agent in self.agents:
                mine = [o for o in agent.orders if o.side == self._sweep_side]
                for o, f in allocate(self._sweep, mine, self._sweep_ts):
                    o.left -= f
                    o.fills.append((self._sweep_ts, f))
                    if o.left == 0:
                        o.state = "filled"
                    agent.on_fill(self, o, f, self._sweep_ts, tot)
            if self.rec is not None and self.ready:
                self.rec.on_sweep(self._sweep_ts, self._sweep_side, self._sweep)
        self._sweep, self._sweep_taker = [], None

    def _on_leave(self, side, tick, qty, seq):
        """真实挂单离开(被撤或成交)qty 张:排在它后面的我方订单,前方数量相应减少(前方撤单 / 前方成交)。"""
        for agent in self.agents:
            for o in agent.orders:
                if o.state == "live" and o.side == side and o.tick == tick and seq <= o.mark:
                    o.ahead = max(o.ahead - qty, 0)

    def _reset(self):
        """断流或文件开头:盘口与我方订单全部作废,重新预热。"""
        self._flush()
        self.book.clear()
        self.touch = Touch()
        self.pending = []
        for agent in self.agents:
            for o in agent.orders:
                if o.state in ("pending", "live"):
                    o.state = "lost"
            agent.orders = []
            agent.on_break(self, self.t_first or 0)
        self.t_first, self.ready = None, False

    # ------------------------------------------------------------------ 内部:行情事件
    def _on_open(self, d, seq):
        oid = d["orderId"]
        side = 0 if d["side"] == "buy" else 1
        tick, size = to_tick(d["price"]), int(d["size"])
        if oid in self.own:
            # 实盘对账:我方真实订单由仿真订单代替,不进盘口;把"真实进簿"这件事告诉需要它的策略
            for agent in self.agents:
                if hasattr(agent, "on_own_open"):
                    agent.on_own_open(self, oid, self._ts)
            return
        # 这张新挂单若等于或穿过我方对侧挂单的价格,在真实撮合里它会先与我方成交(我方先在簿里)。
        # 只有我方挂在真实买一卖一之间时才会发生。它成交后剩下的量照原样进簿(不扣我方拿走的部分:假设 H2 的简化,
        # 影响只是盘口上多显示了这部分量)。
        # 2026-10-08 起默认关闭(cross_fill=False):探针标定显示这条规则让"贴盘口"的假想单一天成交 7.1 亿美元,
        # 是全市场成交额(约 3.3 亿)的两倍多 —— 新进簿的单多数是只挂不吃的报价,现实里碰到我方的单会被拒或根本不会挂在那里,
        # 不能当作吃单。关闭后只有真实的吃单成交(match)才会成交给我方:这是保守口径(少算了普通限价单真会与我方成交的那部分)。
        for agent in (self.agents if self.cross_fill else ()):
            hit = [o for o in agent.orders if o.side != side and o.state == "live" and o.left > 0
                   and (o.cancel_at is None or self._ts < o.cancel_at)
                   and ((o.tick >= tick) if o.side == 0 else (o.tick <= tick))]
            if hit:
                hit.sort(key=lambda o: (-o.tick if o.side == 0 else o.tick, o.rest_at))   # 我方订单之间:价格优先、时间优先
                remaining = size
                for o in hit:
                    f = min(o.left, remaining)                 # 部分成交
                    if f <= 0:
                        break
                    remaining -= f
                    o.left -= f
                    o.fills.append((self._ts, f))
                    if o.left == 0:
                        o.state = "filled"
                    agent.on_fill(self, o, f, self._ts, size)
        self.touch.clear_through(side, tick)
        self.book[oid] = [side, tick, size, seq, self._ts]
        self.touch.add(side, tick, size)

    def _on_match(self, d, seq, ts):
        mid, size = d["makerOrderId"], int(d["size"])
        o = self.book.get(mid)
        if mid in self.own:
            # 实盘对账:打到我方真实订单的吃单量留在扫单里,挂单方序号设为"无穷晚",仿真订单若在簿里就会拿到它
            side, tick, mseq = self.own_side[mid], self.own_tick[mid], 1 << 62
        elif o is not None:
            side, tick, mseq = o[0], o[1], o[3]
            if self.fresh_ns is not None and len(o) > 4 and ts - o[4] < self.fresh_ns:
                self.fresh_n += 1
                self.fresh_qty += size
                self._on_leave(side, tick, size, mseq)
                self.touch.sub(side, tick, size)
                o[2] -= size
                if o[2] <= 0:                              # remainSize 是吃单方剩余量,不能用来判断挂单方是否成交完
                    self.book.pop(mid, None)
                return
            # 成对打印:公开成交流里的成交价与这张挂单在簿里的挂单价不同。
            # 数据事实(2026-10-02 XBTUSDCM 19 时,scripts/research7/live_recon.py 的两张不一致订单):一张挂在 84152.1 的卖单
            # 以 83991.5 成交,而当时簿里有更便宜的卖单(包括我方实盘单)没有成交 → 这类成交不走盘口的价格优先,
            # 不能分给我方挂单(假设 H4;项目记录 memory research3-flow-structure 亦要求回放先剔除成对打印)。
            tt = self.trade_ticks.get(d.get("tradeId"))
            if tt is not None and tt != tick:
                self.paired_n += 1
                self.paired_qty += size
                if self.skip_paired:
                    self._on_leave(side, tick, size, mseq)
                    self.touch.sub(side, tick, size)
                    o[2] -= size
                    if o[2] <= 0:                          # remainSize 是吃单方剩余量,不能用来判断挂单方是否成交完
                        self.book.pop(mid, None)
                    return
                tick = tt
        else:
            # 没见过 open 的挂单方(文件开头或断流之前就在簿里):比我方早。成交价取公开成交流(逐笔委托的 price 是吃单方限价)
            side = 1 if d["side"] == "buy" else 0
            tick = self.trade_ticks.get(d.get("tradeId"))
            mseq = -1
            if tick is None:
                return
        if self._sweep_taker is None:
            self._sweep_taker, self._sweep_side, self._sweep_ts = d["takerOrderId"], side, ts
        if side == self._sweep_side:
            self._sweep.append((tick, size, mseq))
        if o is not None:
            self._on_leave(side, tick, size, mseq)
            self.touch.sub(side, tick, size)
            o[2] -= size                                   # remainSize 是吃单方剩余量,不是挂单方的;挂单方剩余 = 原剩余 − 本笔成交量
            if o[2] <= 0:
                del self.book[mid]

    def _on_done(self, d):
        if d["orderId"] in self.own:
            for agent in self.agents:
                if hasattr(agent, "on_own_done"):
                    agent.on_own_done(self, d["orderId"], d.get("reason"), self._ts)
            return
        o = self.book.pop(d["orderId"], None)
        if o is not None and o[2] > 0:
            self._on_leave(o[0], o[1], o[2], o[3])
            self.touch.sub(o[0], o[1], o[2])

    def _on_update(self, d):
        o = self.book.get(d.get("orderId"))
        if o is not None and d.get("size") is not None:
            new = int(float(d["size"]))
            if new < o[2]:
                self._on_leave(o[0], o[1], o[2] - new, o[3])
            self.touch.sub(o[0], o[1], o[2] - new)
            o[2] = new

    # ------------------------------------------------------------------ 主循环
    def feed(self, line):
        """处理原始文件的一行:b'<本机接收纳秒>\\t<json>'。"""
        i = line.find(b"\t")
        if i <= 0:
            return
        j = line.find(b'"sn":', i, i + 120)
        broke = False
        if j > 0:
            sn = int(line[j + 5:line.index(b",", j)])
            broke = self._last_sn is not None and sn > self._last_sn + SN_GAP_OK
            self._last_sn = sn
        elif b'"_marker"' in line and b'"connect"' in line:
            broke, self._last_sn = self.t_first is not None, None      # 重连:中间丢了多少不知道
        if broke:
            self.breaks += 1
            self._reset()
        if b'"subject":"received"' in line:
            return                                         # 只是"收到",不改变盘口
        m = orjson.loads(line[i + 1:])
        d, s = m.get("data"), m.get("subject")
        if not d or not s:
            return
        ts = int(d["ts"])
        self._ts = ts
        if self.t_first is None:
            self.t_first = ts
        seq = int(d.get("sequence", self.last_seq))
        if s != "match" or d["takerOrderId"] != self._sweep_taker:
            self._flush()                                  # 上一张吃单的成交到此收齐
        self._advance(ts)
        if s == "open":
            self._on_open(d, seq)
        elif s == "match":
            self._on_match(d, seq, ts)
        elif s == "done":
            self._on_done(d)
        elif s == "update":
            self._on_update(d)
        if seq > self.last_seq:
            self.last_seq = seq
        if not self.ready and ts >= self.t_first + WARM_NS:
            self.ready = True
        if self.ready:
            if self.rec is not None:
                bb, ba = self.touch.best(0), self.touch.best(1)
                if bb is not None and ba is not None:
                    cur = (bb, ba, self.touch.size[0][bb], self.touch.size[1][ba])
                    if cur != self._bbo:
                        self._bbo = cur
                        self.rec.on_bbo(ts, *cur)
            for agent in self.agents:
                agent.on_event(self, ts)

    def run(self, day, hours, prewarm_s=300):
        """重放 day(YYYYMMDD)的若干个小时文件(按顺序,盘口状态跨小时延续)。
        prewarm_s: 第一个小时之前,先用上一个小时文件的最后这么多秒把盘口建起来(只建盘口,不调用策略),
                   这样第一个小时一开始就能报价。300 秒 > WARM_NS,ASSUMPTION(只影响可用时长,不影响成交判定)。"""
        first = True
        for hh in hours:
            f = os.path.join(L3_DIR[self.sym], day, f"{hh}_{self.sym}_l3.jsonl.gz")
            if first and prewarm_s:
                self._prewarm(day, hh, prewarm_s)
            first = False
            try:
                with gzip.open(f, "rb") as fh:
                    for line in fh:
                        self.feed(line)
            except (EOFError, OSError, zlib.error):
                self.breaks += 1                           # 文件尾损坏:当作断流
                self._reset()
        self._flush()

    def _prewarm(self, day, hh, seconds):
        """读上一个小时文件的末尾 seconds 秒,只用来建盘口。上一个小时不存在则跳过(退回到 WARM_NS 预热)。"""
        import datetime as dt
        t0 = dt.datetime.strptime(day + hh, "%Y%m%d%H").replace(tzinfo=dt.timezone.utc)
        p = t0 - dt.timedelta(hours=1)
        f = os.path.join(L3_DIR[self.sym], p.strftime("%Y%m%d"), f"{p.strftime('%H')}_{self.sym}_l3.jsonl.gz")
        if not os.path.exists(f):
            return
        # 行首是本机接收时间(纳秒);采集机时钟与交易所时钟相差不到几秒,用它粗筛"最后 seconds 秒"足够
        cut = int(t0.timestamp() * NS) - seconds * NS
        agents, rec, self.agents, self.rec = self.agents, self.rec, [], None
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    if int(line[:19]) >= cut:
                        self.feed(line)
        except (EOFError, OSError, zlib.error, ValueError):
            pass
        self.agents, self.rec = agents, rec
