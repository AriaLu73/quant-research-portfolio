#!/usr/bin/env python3
"""项目回测引擎的撮合(engine/backtest/matching.py)对 2026-10-02 实盘订单的对账。只读;不改引擎、不连交易所。

背景      research7 阶段 0 对过实盘的是 scripts/research7/l3sim.py(live_recon.py);AS 框架回放走的是项目引擎
          engine.backtest.runner → broker_sim → matching,是另一套撮合代码,此前没有和实盘订单对过。
做法      1. 盘口和成交:用 l3sim.L3Sim 读同期自采的逐笔委托(我方真实订单从公开流里拿掉),把它维护的每个价位的挂单量
             逐条镜像成项目引擎的盘口增量(Depth),把每笔吃单成交镜像成逐笔成交(Tick;成对打印不发,同 l3sim 的假设 H4)。
          2. 订单:实盘日志里的每张单,在引擎发单时刻交给项目引擎的 BrokerSim(只挂不吃),撤单在引擎发撤单时刻交给它;
             下单 / 撤单延迟固定 1.5 毫秒,排队 queue_cancel_bias = 1.0(用户裁决的口径)。
          3. 记下项目引擎判成交的每一笔,并标明是哪条规则判的:
               sweep   = MatchingEngine.sweep_crossed(对侧公共盘口越过我方挂单价)
               trade   = MatchingEngine.on_trade(逐笔成交打到或穿过我方价位)
             再和实盘的成交逐单对比。
          4. 同样的输入再跑一遍"关掉 sweep_crossed"(只在本脚本里把这个方法换成空操作,不动引擎文件),看差别来自哪条规则。
可评估    发单时盘口已预热好、且挂单期间没有遇到断流的订单才计入(同 live_recon.py)。
用法      .venv/Scripts/python.exe scripts/research7/engine_live_recon.py <XBTUSDCM|XBTUSDTM>
输出      data/research7/live_recon/engine_<合约>.txt
"""
import gzip
import os
import sys
import zlib
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import l3sim as L
import l3_prep as P
import live_recon as LR

from core.enums import Exchange, OrderType, ProductType, Side, TimeInForce
from core.models import Depth, DepthLevel, Order, Tick
from engine.backtest.broker_sim import BrokerSim
from engine.backtest.clock import SimClock

ORDER_LAT_NS = 1_500_000
ENG_SYM = {"XBTUSDCM": "BTC-USDC", "XBTUSDTM": "BTC-USDT"}
CFG = {"rebuild": {"mode": "L3", "queue_cancel_bias": "1.0"},
       "broker_sim": {"matching_mode": "tick", "order_latency": {"model": "fixed", "value_ns": ORDER_LAT_NS},
                      "slippage_model": "thin_depth_penetration", "commission": {"maker": "OUR_FEE", "taker": "0.0002"},
                      "funding_rate": {"settle_interval_hours": 8, "source": "replay"}}}


class DirtyTouch(L.Touch):
    """和 l3sim 的 Touch 一样,只是多记一份"哪些价位变过",用来生成盘口增量。"""
    dirty = set()

    def add(self, side, tick, qty):
        super().add(side, tick, qty)
        DirtyTouch.dirty.add((side, tick))

    def sub(self, side, tick, qty):
        super().sub(side, tick, qty)
        DirtyTouch.dirty.add((side, tick))

    def clear_through(self, side, tick):
        o = 1 - side
        while True:
            b = self.best(o)
            if b is None or (b > tick if o == 1 else b < tick):
                return
            self.size[o][b] = 0
            DirtyTouch.dirty.add((o, b))


L.Touch = DirtyTouch


class Mirror(L.L3Sim):
    """L3Sim + 把吃单成交记下来(价格、张数、吃单方向),供转成项目引擎的 Tick。"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.prints = []
        self.resets = 0

    def _reset(self):
        super()._reset()
        self.resets += 1

    def _on_match(self, d, seq, ts):
        mid, size = d["makerOrderId"], int(d["size"])
        o = self.book.get(mid)
        tt = self.trade_ticks.get(d.get("tradeId"))
        if mid in self.own:
            tick = self.own_tick[mid]
        elif o is not None:
            tick = o[1]
            if tt is not None and tt != tick:
                tick = None                                 # 成对打印:不走盘口,不发
        else:
            tick = tt
        if tick is not None:
            self.prints.append((tick, size, d["side"]))     # side = 吃单方向
        super()._on_match(d, seq, ts)


def run(sym, sweep_on):
    mult = Decimal(str(L.MULT[sym]))
    tick_d = Decimal(str(L.TICK))
    esym = ENG_SYM[sym]
    od = LR.read_journal(sym)
    own = {o["ex_id"]: (o["side"], o["tick"]) for o in od.values() if o["ex_id"]}
    sim = Mirror(sym, L.Latency(fixed_ms=0.0), [], own_ids=own, trade_ticks=P.load_trade_ticks(LR.DAY, LR.HOURS, sym))
    clock = SimClock()
    got = []                                               # (引擎订单号, 张数, 时刻, 规则)
    tags = []                                              # 撮合结果出来时先记下是哪条规则判的,成交回调里再取
    open_ids = set()                                       # 还在引擎里(未成交完、未撤、未拒)的订单

    def on_fill(f):
        s_ = "arrive"
        for n, (oid, q, t) in enumerate(tags):
            if oid == f.order_id and q == f.quantity:
                s_ = t
                del tags[n]
                break
        got.append((f.order_id, int(f.quantity / mult), f.ts_ns, s_))

    def on_report(r):
        if r.status.name in ("FILLED", "CANCELLED", "REJECTED"):
            open_ids.discard(r.order_id)
    broker = BrokerSim(CFG, clock, on_fill=on_fill, on_report=on_report)
    eng = broker._engine(esym)
    real_sweep, real_trade = eng.sweep_crossed, eng.on_trade

    def sweep():
        r = real_sweep() if sweep_on else []
        tags.extend((x.order_id, x.fill_qty, "sweep") for x in r if x.fill_qty > 0)
        return r

    def trade(**k):
        r = real_trade(**k)
        tags.extend((x.order_id, x.fill_qty, "trade") for x in r if x.fill_qty > 0)
        return r
    eng.sweep_crossed, eng.on_trade = sweep, trade

    base = dict(exchange=Exchange.KUCOIN, product_type=ProductType.SWAP_USDT, symbol=esym)
    sends = sorted((o["t_send"], k) for k, o in od.items())
    cancels = sorted((o["t_cancel"], k) for k, o in od.items() if o["t_cancel"])
    i = j = 0
    placed, skipped, live_reset = {}, set(), {}
    snap_sent = False
    seen_resets = 0
    n_depth = n_tick = 0

    def lv(side_levels):
        return [DepthLevel(Decimal(t) * tick_d, Decimal(max(q, 0)) * mult) for t, q in side_levels]

    def feed(line):
        nonlocal i, j, snap_sent, seen_resets, n_depth, n_tick
        a = line.find(b'"ts":')
        if a < 0:
            sim.feed(line)
            return
        b = a + 5
        e = b
        while line[e:e + 1].isdigit():
            e += 1
        if e == b:
            sim.feed(line)
            return
        ts = int(line[b:e])
        # 先把到这一刻为止该发的单、该撤的单交给项目引擎(时刻取引擎发单 / 发撤单时刻,引擎再加 1.5 毫秒)
        while True:
            ts_o = sends[i][0] if i < len(sends) else None
            ts_c = cancels[j][0] if j < len(cancels) else None
            nxt = min(x for x in (ts_o, ts_c, ts + 1) if x is not None)
            if nxt > ts:
                break
            if ts_o is not None and ts_o == nxt:
                k = sends[i][1]
                i += 1
                o = od[k]
                if not (sim.ready and snap_sent) or o["rejected"] and False:
                    skipped.add(k)
                    continue
                clock.advance(max(ts_o, clock.now_ns() if clock._started else ts_o))
                order = Order(order_id=k, strategy_id="live", side=Side.BUY if o["side"] == 0 else Side.SELL, order_type=OrderType.LIMIT,
                              quantity=Decimal(o["size"]) * mult, price=Decimal(o["tick"]) * tick_d, time_in_force=TimeInForce.POST_ONLY, **base)
                broker.place_order(order)
                open_ids.add(k)
                placed[k] = seen_resets
            else:
                k = cancels[j][1]
                j += 1
                if k in placed:
                    clock.advance(max(ts_c, clock.now_ns()))
                    broker.cancel_order(k)
        DirtyTouch.dirty.clear()
        sim.prints.clear()
        sim.feed(line)
        if sim.resets != seen_resets:                      # 断流:盘口重建;此前还挂着的单不评估
            seen_resets = sim.resets
            snap_sent = False
            for k in open_ids:
                live_reset[k] = True
        if not sim.ready:
            return
        if ts < (clock.now_ns() if clock._started else 0):
            ts = clock.now_ns()
        kw = dict(ts_ms=ts // 1_000_000, ts_ns=ts, **base)
        for tick, size, side in sim.prints:
            n_tick += 1
            broker.on_market(Tick(price=Decimal(tick) * tick_d, size=Decimal(size) * mult,
                                  side=Side.BUY if side == "buy" else Side.SELL, **kw))
        if not snap_sent:
            bids = sorted(((t, q) for t, q in sim.touch.size[0].items() if q > 0), reverse=True)
            asks = sorted((t, q) for t, q in sim.touch.size[1].items() if q > 0)
            broker.on_market(Depth(bids=lv(bids), asks=lv(asks), is_snapshot=True, **kw))
            snap_sent = True
            n_depth += 1
        elif DirtyTouch.dirty:
            bids = [(t, sim.touch.size[0].get(t, 0)) for s, t in DirtyTouch.dirty if s == 0]
            asks = [(t, sim.touch.size[1].get(t, 0)) for s, t in DirtyTouch.dirty if s == 1]
            broker.on_market(Depth(bids=lv(bids), asks=lv(asks), **kw))
            n_depth += 1

    # 与 L3Sim.run 相同的读法(含上一小时末尾 300 秒的预热),只是每行经过上面的 feed
    first = True
    for hh in LR.HOURS:
        f = os.path.join(L.L3_DIR[sym], LR.DAY, f"{hh}_{sym}_l3.jsonl.gz")
        if first:
            sim._prewarm(LR.DAY, hh, 300)
        first = False
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    feed(line)
        except (EOFError, OSError, zlib.error):
            sim.breaks += 1
            sim._reset()
    # 结束时还挂着的单:它们的实盘成交若发生在数据结束之后也不可比,但数据覆盖了整个实盘时段,不另处理
    return od, placed, skipped, live_reset, got, dict(depth=n_depth, tick=n_tick, breaks=sim.breaks, paired=sim.paired_n)


def summarize(sym, od, placed, skipped, live_reset, got, tag):
    # 实盘里被交易所以"系统繁忙"等原因拒掉、从未进过公开流的单(rejected 且没有交易所订单号)不可比:现实里这张单不存在
    never = {k for k in placed if od[k]["rejected"] and not od[k]["ex_id"]}
    ok = [k for k in placed if k not in live_reset and k not in never]
    real = {k: sum(q for _, q, _, mk in od[k]["fills"]) for k in ok if od[k]["fills"]}
    simf = {}
    by_src = {}
    for k, q, ts, s in got:
        if k in live_reset or k not in placed or k in never:
            continue
        simf[k] = simf.get(k, 0) + q
        by_src.setdefault(s, [0, 0, set()])
        by_src[s][0] += 1
        by_src[s][1] += q
        by_src[s][2].add(k)
    both = set(real) & set(simf)
    out = ["%s  %s" % (sym, tag),
           "  实盘订单 %d 张;可评估 %d 张(发单时盘口未就绪 %d 张,挂单期间遇到断流 %d 张,实盘被交易所拒掉、从未进簿 %d 张)" % (len(od), len(ok), len(skipped), len(live_reset), len(never)),
           "  实盘成交订单 %d 张 / %d 张合约;项目引擎判成交订单 %d 张 / %d 张合约;两边都成交 %d 张"
           % (len(real), sum(real.values()), len(simf), sum(simf.values()), len(both)),
           "  只有实盘成交 %d 张;只有引擎判成交 %d 张" % (len(set(real) - set(simf)), len(set(simf) - set(real)))]
    for s, (n, q, ks) in sorted(by_src.items()):
        out.append("  规则 %-6s 判了 %d 笔 / %d 张合约,涉及 %d 张订单,其中实盘也成交的 %d 张" % (s, n, q, len(ks), len(ks & set(real))))
    for k in sorted(set(real) | set(simf), key=lambda x: od[x]["t_send"]):
        o = od[k]
        out.append("    %s %s 价 %.1f 量 %d  实盘成交 %d  引擎判 %d  规则 %s"
                   % (k[-8:], "买" if o["side"] == 0 else "卖", o["tick"] * L.TICK, o["size"], real.get(k, 0), simf.get(k, 0),
                      ",".join(sorted({s for kk, _, _, s in got if kk == k})) or "—"))
    return out


if __name__ == "__main__":
    sym = sys.argv[1]
    lines = []
    for sweep_on, tag in ((True, "项目引擎原样(含 sweep_crossed)"), (False, "关掉 sweep_crossed(仅本脚本内)")):
        od, placed, skipped, live_reset, got, st = run(sym, sweep_on)
        lines += summarize(sym, od, placed, skipped, live_reset, got, tag)
        lines.append("  喂给引擎:盘口增量 %d 条、逐笔成交 %d 笔;断流 %d 次;成对打印(未发)%d 笔" % (st["depth"], st["tick"], st["breaks"], st["paired"]))
        lines.append("")
    out = os.path.join(P.OUT, "live_recon", "engine_%s.txt" % sym)
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
