#!/usr/bin/env python3
"""research7 宽价差合约:实盘策略类 MM_LTK_PROBE_v1 原样接到 L2 排队仿真器上回放(9 月四个全合约日)。

用途      用户 2026-10-09:"这个策略拿 8–9 月的数据也跑一下"。跑的是 strategies/deploy/MM_LTK_PROBE_v1.py 这个文件本身
          (不是研究脚本里的规则副本):仿真器把盘口、币安成交、成交回报、订单终态按实盘回调的形式喂给它,它发出的
          订单与撤单进仿真器排队。
所属阶段  阶段 8 探针的补充检验(事件级回放)。
对应公式  策略文件头的规则 F / P / R / V / K / I;本文件不含任何报价逻辑。
两个方案  vol = 文件默认值(门槛 −0.25 跳 + 0.10 σ60);fix = theta_sigma 0(10-08 回放检验过的固定门槛)。同一延迟种子配对,
          两个方案在同一遍行情里各自独立排队(仿真器假设 H2:我方不影响他人)。
撮合口径  l2sim.L2Sim:没有逐笔委托,排队位置按 L2 推断(撤单按比例,cancel_rule = prop;误差标定见 阶段0b_L2仿真标定.md,
          那次标定用的是 BTC 合约,不是这五个合约)。挂在价差之内的我方订单:吃单到来时先于原来的最优价成交。
          成交价不在当时盘口最优价上的打印(成对打印)不分给我方。
延迟      下单 / 撤单:10-02 实盘实测分布按负载分档抽样 + 行情到达抖动(l3sim.EmpiricalLatency,md_jitter);
          币安成交到达:REF_DELAY_MS。
费用      KuCoin 我方费率档,TradFi 合约挂单返佣 我方费率(项目记录 memory kucoin-mm-offer),记为负的手续费。
输出      data/research7/ltk_live/<合约>_<day>_<方案>.npz:
            fills  每行 (成交时间 ns, 方向 ±1, 成交价 美元, 数量 标的单位, 成交后持仓, 是否离场单 0/1, 成交时这张单已在簿多少秒)
            mids   每行 (秒, 别人的中间价 美元):每秒第一条行情时的值
            pnl    每行 (秒, 现金 + 持仓 × 中间价 − 手续费):同上时刻
          与同名 .json(策略自己的统计 _summary()、下单 / 撤单条数)。
用法      .venv/Scripts/python.exe scripts/research7/ltk_live_replay.py run <合约> <YYYYMMDD>
          .venv/Scripts/python.exe scripts/research7/ltk_live_replay.py all [并行数]
"""
import contextlib
import io
import json
import os
import sys
from decimal import Decimal
from types import SimpleNamespace as NS

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "strategies", "deploy"))
import l2sim as S
import l3sim as L
import ltk_screen as SC

OUT = os.path.join(ROOT, "data", "research7", "ltk_live")
L2 = os.path.join(ROOT, "data", "research7", "l2")
STOCKS = ("CRCLUSDTM", "IONQUSDTM", "AMDUSDTM", "SPCXUSDTM", "SPYUSDTM")       # 探针的五个股票合约:盘口只有 4 天
STOCK_DAYS = ("20260910", "20260918", "20260921", "20260924")
COMMS = ("XAUTUSDTM", "PAXGUSDTM", "BZUSDTM")       # 金属 / 大宗:盘口有 20 天
DROPPED = ("XAGUSDTM", "CLUSDTM", "NATGASUSDTM")    # 用户 2026-10-09 裁决:不适合做市,剔除(第一版在这三个上的结果仍保留在输出目录里)
COMM_DAYS = tuple("202608%02d" % d for d in range(26, 32)) + tuple("202609%02d" % d for d in (1, 2, 3, 4, 5, 6, 7, 10, 11, 14, 17, 18, 23, 24))
SYMS = STOCKS + COMMS
DAYS = tuple(sorted(set(STOCK_DAYS + COMM_DAYS)))
JOBS = [(s, d) for d in STOCK_DAYS for s in STOCKS] + [(s, d) for d in COMM_DAYS for s in COMMS]
SEED = 91
REF_DELAY_MS = 24.0                # 币安逐笔成交流到达延迟:取 10-06 colo 实测的 90 分位(中位数 7 ms;memory pre-live-gates)。偏保守
REBATE = OUR_FEE                    # 返佣,占成交额的比例(TradFi 档;本文件的合约全部属于这一档,ltk_screen.TRADFI)
ORDER_USD = 200.0                  # 探针规模(config/deploy_kucoin_ltk_probe.yaml)
V1 = {"exit_rule": 0, "skew_sigma": 0.0, "quote_ttl_s": 60.0}                    # 第一版(文件名 vol / fix 的已有结果就是这组参数)
VARIANTS = {"vol": dict(V1), "fix": dict(V1, theta_sigma=0.0),
            "t20": dict(V1, quote_ttl_s=20.0),                                          # 第一版只改 TTL
            "s025": {"skew_sigma": 0.25}, "s05": {"skew_sigma": 0.5}, "s10": {"skew_sigma": 1.0}}   # 第二版(预登记第 19 节)
# 定版(用户 2026-10-09:第一版离场 + TTL 20 秒)放大单量:每单 = 持仓上限 = $1,000 / $2,000,亏损线上限按比例放大($4 × 5 / × 10)。
# 目的:量"单量放大后盈亏是否跟着放大"(容量)。$2,000 与 10-01 逐笔委托回放的单量相同。
VARIANTS["u1k"] = dict(V1, quote_ttl_s=20.0, order_usd=1000.0, max_pos_usd=1000.0, loss_stop_usd=20.0)
VARIANTS["u2k"] = dict(V1, quote_ttl_s=20.0, order_usd=2000.0, max_pos_usd=2000.0, loss_stop_usd=40.0)
# 放开下单频率上限(每秒 1 → 5 张、每 10 秒 6 → 30 张、每天 2 万 → 20 万张):量"成交额与盈亏有多少是被我自己设的上限挡掉的"。
# 原上限是为 5 个合约的探针按网关限速(每 10 秒 100 条)定的,不是策略本身的要求;放开后是否可行取决于账户限频档位(未核实)。
_FAST = {"max_orders_per_s": 5, "max_orders_per_10s": 30, "max_orders_per_day": 200000}
VARIANTS["c200"] = dict(V1, quote_ttl_s=20.0, **_FAST)
VARIANTS["c2k"] = dict(V1, quote_ttl_s=20.0, order_usd=2000.0, max_pos_usd=2000.0, loss_stop_usd=40.0, **_FAST)
RUN = ("c200", "c2k")                                                                  # 本次要跑的方案;其余已有结果
WAKE_TICK = 1                      # 币安价变化时插入的"空事件"所在价位:买盘 1 跳处(远离盘口,不影响最优价),只为让策略被唤醒


# 选品回放:环境变量 LTK_CAND 指向一个合约清单文件时,只在四个全合约日上跑这些合约的定版($200、第一版离场、TTL 20 秒)。
if os.environ.get("LTK_CAND"):
    CAND = tuple(open(os.environ["LTK_CAND"]).read().split())
    SYMS = CAND
    JOBS = [(s_, d_) for d_ in STOCK_DAYS for s_ in CAND]
    RUN = ("t20",)


class Ctx:
    """策略上下文的仿真实现:emit_signal → 仿真器下单;cancel → 仿真器撤单。只接受带价格的只挂单。"""

    def __init__(self, agent):
        self.a = agent

    def position(self, symbol):
        return None

    def spec(self, symbol):
        return {"tick_size": repr(self.a.tick), "lot_size": repr(self.a.mult), "min_qty": repr(self.a.mult), "min_notional": "0"}

    def emit_signal(self, *, symbol, side, quantity, price=None, **kw):
        assert price is not None and kw.get("tif") == "post_only"
        a = self.a
        n = int(round(float(quantity) / a.mult))                     # 单位换算:标的数量 → 张
        if n <= 0:
            return ""
        a.n_oid += 1
        oid = "o%d" % a.n_oid
        o = a.sim.place(a, 0 if side == "buy" else 1, int(round(float(price) / a.tick)), n, a.ts, tag=oid)
        a.open[oid] = o
        a.n_place += 1
        return oid

    def cancel(self, oid):
        o = self.a.open.get(oid)
        if o is not None:
            self.a.sim.cancel(o, self.a.ts)
            self.a.n_cancel += 1
        return True


class LiveAgent:
    """仿真器眼里的"策略":把仿真器的回调翻译成实盘策略类的回调。"""

    def __init__(self, name, lat, sym, bn_ts, bn_px, params):
        import MM_LTK_PROBE_v1 as P
        from core.enums import OrderStatus, Side
        self.P, self.OS, self.Side = P, OrderStatus, Side
        self.name, self.lat, self.orders = name, lat, []
        self.sym, self.usym = sym, sym[:-5] + "-USDT"
        self.tick, self.mult = SC.spec(sym)
        self.bn_ts, self.bn_px, self.bi = bn_ts, bn_px, 0
        self.sim, self.ts = None, 0
        self.open, self.n_oid, self.n_place, self.n_cancel = {}, 0, 0, 0
        self.fills, self.mids, self.pnl, self.sec = [], [], [], -1
        self.strat = P.MmLtkProbe(Ctx(self))
        p = {"symbol": self.usym, "order_usd": ORDER_USD, "max_pos_usd": ORDER_USD, "book_has_own": 0, "status_s": 1e12}
        p.update(params)
        self.strat.on_params_update(p)
        self.strat.on_start()

    # ---- 订单终态回报(撤单生效 / 拒单 / 断流作废)
    def _reports(self):
        for oid, o in list(self.open.items()):
            if o.state in ("pending", "live"):
                continue
            del self.open[oid]
            st = self.OS.FILLED if o.state == "filled" else self.OS.REJECTED if o.state == "rejected" else self.OS.CANCELLED
            self.strat.on_order_report(NS(order_id=oid, status=st))

    def on_event(self, sim, ts):
        self.sim, self.ts = sim, ts
        s = self.strat
        self._reports()
        lim = ts - int(REF_DELAY_MS * L.MS)
        bt, bp = self.bn_ts, self.bn_px
        i = self.bi
        while i < len(bt) and bt[i] <= lim:                           # 已经到达我方的币安成交,按时间顺序送给策略
            s.on_ref_tick(NS(symbol=self.usym, ts_ns=int(bt[i]), price=bp[i]))
            i += 1
        self.bi = i
        bb, ba = sim.best(0), sim.best(1)
        if bb is None or ba is None:
            return
        s.on_depth(NS(symbol=self.usym, ts_ns=ts,
                      bids=[NS(price=bb * self.tick, size=sim.level_size(0, bb) * self.mult)],
                      asks=[NS(price=ba * self.tick, size=sim.level_size(1, ba) * self.mult)]))
        self._reports()
        sec = ts // L.NS
        if sec != self.sec and bb < ba and s.blocked != "wide":      # 盘口一侧被抽空时的中间价不是价格,不记入盈亏路径
            self.sec = sec
            mid = (bb + ba) / 2.0 * self.tick
            self.mids.append((sec, mid))
            self.pnl.append((sec, s.cash + s.pos * mid - s.fees))

    def on_fill(self, sim, o, qty, ts, sweep_qty):
        self.sim, self.ts = sim, ts
        s = self.strat
        px, q = o.tick * self.tick, qty * self.mult
        side = self.Side.BUY if o.side == 0 else self.Side.SELL
        slot = s.slot["bid" if o.side == 0 else "ask"]
        is_exit = 1 if (slot is not None and slot["oid"] == o.tag and slot["exit"]) else 0
        s.on_fill(NS(symbol=self.usym, order_id=o.tag, side=side, price=px, quantity=q, fee=-REBATE * px * q, ts_ns=ts, is_maker=True))
        self.fills.append((ts, 1 if o.side == 0 else -1, px, q, s.pos, is_exit, (ts - o.rest_at) / 1e9))
        self._reports()

    def on_break(self, sim, ts):
        self.sim, self.ts = sim, ts
        for oid in list(self.open):                                   # 盘口重置:仿真器已把我方订单作废,按已撤回报给策略
            del self.open[oid]
            self.strat.on_order_report(NS(order_id=oid, status=self.OS.CANCELLED))


def run(sym, day):
    f = os.path.join(L2, "%s_%s.npz" % (sym, day))
    fb = os.path.join(OUT, "bn_%s_%s.npz" % (sym[:-1], day))
    if not (os.path.exists(f) and os.path.exists(fb)):
        print("ltk_live %s %s: 缺数据  LIVE_MISSING" % (sym, day), flush=True)
        return
    ev = dict(np.load(f))
    zb = np.load(fb)
    bn_ts, bn_px = zb["ts"], zb["px"]
    # 币安价发生变化的时刻 + 到达延迟:插入一条不改变盘口的事件,让策略在两次 KuCoin 行情之间也能被唤醒
    chg = np.r_[True, np.diff(bn_px) != 0]
    wt = bn_ts[chg] + int(REF_DELAY_MS * L.MS)
    wt = wt[(wt > ev["ts"][0]) & (wt < ev["ts"][-1])]
    n = len(wt)
    ts = np.r_[ev["ts"], wt]
    kind = np.r_[ev["kind"], np.full(n, S.K_LEVEL, np.int8)]
    side = np.r_[ev["side"], np.zeros(n, np.int8)]
    tick = np.r_[ev["tick"], np.full(n, WAKE_TICK, np.int32)]
    size = np.r_[ev["size"], np.ones(n, np.int32)]
    o = np.lexsort((kind, ts))                                        # 同一时刻成交(kind 0)在前,同 l2_prep 的约定
    ev = {"ts": ts[o], "kind": kind[o], "side": side[o], "tick": tick[o], "size": size[o]}
    lt = np.load(os.path.join(ROOT, "data", "research7", "latency_empirical_l2load.npz"))
    load = S.L2Load(ev["ts"])
    agents = [LiveAgent(name, L.EmpiricalLatency(load, lt, lead_ms=0.3, seed=SEED, md_jitter=True), sym, bn_ts, bn_px.tolist(), prm)
              for name, prm in VARIANTS.items() if name in RUN]
    sim = S.L2Sim(sym, L.Latency(fixed_ms=1.8), agents)
    with contextlib.redirect_stdout(io.StringIO()):                  # 策略逐笔打印 LTK_FILL / LTK_MARK,回放里不需要
        sim.run(ev)
    os.makedirs(OUT, exist_ok=True)
    for a in agents:
        base = os.path.join(OUT, "%s_%s_%s" % (sym, day, a.name))
        np.savez_compressed(base + ".npz", fills=np.asarray(a.fills, float).reshape(-1, 7), mids=np.asarray(a.mids, float).reshape(-1, 2),
                            pnl=np.asarray(a.pnl, float).reshape(-1, 2), tick=a.tick, mult=a.mult)
        st = a.strat._summary()
        st.update(n_place=a.n_place, n_cancel=a.n_cancel, breaks=sim.breaks, paired_qty=int(sim.paired_qty), trade_qty=int(sim.trade_qty))
        json.dump(st, open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False, default=str)
    print("ltk_live %s %s: " % (sym, day) + "  ".join("%s 成交 %d 笔 / 新单 %d" % (a.name, len(a.fills), a.n_place) for a in agents) + "  LIVE_DONE", flush=True)


def run_all(par):
    import subprocess
    import time
    todo = [(s, d) for s, d in JOBS if not os.path.exists(os.path.join(OUT, "%s_%s_%s.json" % (s, d, RUN[-1])))]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    running = []
    while todo or running:
        running = [p for p in running if p.poll() is None]
        while todo and len(running) < par:
            s, d = todo.pop(0)
            running.append(subprocess.Popen([sys.executable, os.path.abspath(__file__), "run", s, d], cwd=ROOT, env=env))
        time.sleep(2)
    print("LIVE_ALL_DONE", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2], sys.argv[3])
    else:
        run_all(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
