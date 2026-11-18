#!/usr/bin/env python3
"""把策略文件本身(不是另写的简化版)放进 KuCoin 逐笔委托(L3)回放里跑,按真实排队位置撮合(用户 10-16:"做测试版,用L3回放验证")。只读,线下。

撮合   scripts/research7/l3sim.py:价格优先、时间优先;我方单进簿时排在同价位已有挂单后面;前面的单撤掉 / 成交后往前挪;
       延迟 = 实盘实测分布(latency_empirical.npz,按交易所负载分档抽样)+ 行情到达抖动;进簿不到 5 毫秒就被打掉的成交不算给我们
       (先挂后吃的对敲,10-11 审计)。只挂不吃:进簿时会穿过对面就被拒。
行情   KuCoin:L3 重建的盘口,前 5 档有变化才推给策略(实盘行情发布规则);逐笔成交推给 on_tick。盘口数量单位 = 币(张 × 0.001)。
       币安:BTCUSDT 永续官方逐笔成交(data/research5/binance_hist),到达时刻 = 币安撮合时间 + 抽样的行情延迟
       (我方机房实测分位 p50 1.4 / p90 5.6 / p99 12.5 毫秒,同 l3sim.EmpiricalLatency.MD_QUANTILES),推给 on_ref_tick。
       币安触发的动作只加下单延迟(不再加 KuCoin 行情延迟)。
接口   策略看到的 ctx:emit_signal(下单)、cancel(撤单)、position(返回 0)、latest_depth_at(返回 None)。
       回报:撤单生效 → cancelled;进簿被拒 → rejected;成交 → on_fill + filled / partially_filled。市价单按当时对手价立刻成交(本测试里不会用到)。
记账   每笔成交:价格 = 我方挂单价;返佣 我方费率。盈亏 = 现金 + 持仓 × 期末中间价。markout 用 data/research7/mid24 的 10 毫秒网格中间价。
用法   .venv/Scripts/python.exe scripts/research7/l3_strategy_replay.py <策略文件> <标签> <日> <时,时,...> [参数=值 ...]
输出   data/research7/l3_strategy/<标签>_<日>.json(汇总)+ _fills.csv(每笔成交:时刻、方向、价格、张数、进簿时离最优价几跳、前面排了多少张、等了多久、
       成交那一刻策略看到的自己的失衡与 tox_bnpush 卖侧 / 买侧值、决定挂单的时刻、进簿时刻、成交时前面还剩的张数、这次吃单的总张数)
"""
import bisect
import gzip
import io
import json
import math
import os
import re
import sys
import time
import zipfile
import zlib
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import pandas as pd
from sortedcontainers import SortedDict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l3sim as L          # noqa: E402
import l3_prep as P        # noqa: E402
from core.enums import OrderStatus, Side   # noqa: E402

SYM, SYMN = "XBTUSDTM", "BTC-USDT"
MULT = 0.001               # BTC / 张
REBATE_BP = OUR_FEE
OUT = os.path.join(ROOT, "data", "research7", "l3_strategy")


class SortedTouch(L.Touch):
    """同 l3sim.Touch,但每侧价位用有序字典,能取前 5 档。"""

    def __init__(self):
        self.size = (SortedDict(), SortedDict())

    def add(self, side, tick, qty):
        s = self.size[side]
        s[tick] = s.get(tick, 0) + qty

    def sub(self, side, tick, qty):
        s = self.size[side]
        if tick in s:
            v = s[tick] - qty
            if v > 0:
                s[tick] = v
            else:
                del s[tick]

    def best(self, side):
        s = self.size[side]
        if not s:
            return None
        return s.peekitem(-1)[0] if side == 0 else s.peekitem(0)[0]

    def top(self, side, n=5):
        s = self.size[side]
        keys = s.keys()
        if side == 0:
            ks = [keys[-1 - i] for i in range(min(n, len(keys)))]
        else:
            ks = [keys[i] for i in range(min(n, len(keys)))]
        return [(k, s[k]) for k in ks]

    def clear_through(self, side, tick):
        o = 1 - side
        s = self.size[o]
        while s:
            b = self.best(o)
            if b > tick if o == 1 else b < tick:
                return
            del s[b]


class Sim(L.L3Sim):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.touch = SortedTouch()

    def _reset(self):
        super()._reset()
        self.touch = SortedTouch()

    def _on_match(self, d, seq, ts):
        super()._on_match(d, seq, ts)
        if self.ready:
            tt = self.trade_ticks.get(d.get("tradeId"))
            for ag in self.agents:
                ag.on_public_trade(ts, 1 if d["side"] == "buy" else -1, tt, int(d["size"]))


class StratAgent:
    def __init__(self, path, params, lat_md, lat_ref):
        src = open(path, encoding="utf-8").read()
        ns = {"__name__": "strat_under_test"}
        exec(compile(src, path, "exec"), ns)
        from modules.strategy.base import SwapBaseStrategy
        cls = [v for v in ns.values() if isinstance(v, type) and issubclass(v, SwapBaseStrategy) and v is not SwapBaseStrategy][0]
        self.S = cls(self)
        self.S.params.update(params)
        self.started = False
        self.orders = []
        self.lat_md, self.lat_ref, self.lat = lat_md, lat_ref, lat_md
        self.sim = None
        self.now = 0
        self.by_oid, self.seen = {}, {}
        self.n = 0
        self.fills = []
        self.q = self.cash = 0.0
        self.last_top = None
        self.n_depth = self.n_ref = 0

    # ---------------- ctx ----------------
    def emit_signal(self, *, symbol, side, quantity, price=None, **kw):
        self.n += 1
        oid = "sim%d" % self.n
        sd = 0 if side == "buy" else 1
        size = int(round(float(quantity) / MULT))
        if price is None:                                  # 市价单:按当时对手价立刻成交(本测试不用)
            b = self.sim.best(1 - sd)
            if b is None:
                return ""
            self._book_fill(sd, b, size, self.now, taker=True)
            return oid
        tick = int(round(float(price) / L.TICK))
        o = self.sim.place(self, sd, tick, size, self.now, tag=oid)
        self.by_oid[oid] = o
        self.seen[oid] = "pending"
        return oid

    def cancel(self, oid):
        o = self.by_oid.get(oid)
        if o is None or o.state not in ("pending", "live"):
            return False
        self.sim.cancel(o, self.now)
        return True

    def position(self, sym):
        return 0

    def latest_depth_at(self, ex, sym):
        return None

    # ---------------- 回报 ----------------
    def _report(self, oid, status):
        rep = SimpleNamespace(order_id=oid, status=status)
        self.S.on_order_report(rep)

    def _sync_reports(self):
        for oid, o in list(self.by_oid.items()):
            st = o.state
            if st == self.seen.get(oid):
                continue
            self.seen[oid] = st
            if st == "cancelled" or st == "lost":
                self._report(oid, OrderStatus("cancelled"))
            elif st == "rejected":
                self._report(oid, OrderStatus("rejected"))
            if st in ("cancelled", "lost", "rejected", "filled"):
                self.by_oid.pop(oid, None)
                self.seen.pop(oid, None)

    def _book_fill(self, sd, tick, size, ts, taker=False, o=None, sweep_qty=None):
        px = tick * L.TICK
        qty = size * MULT
        sgn = 1.0 if sd == 0 else -1.0
        fee = (OUR_FEE if taker else -REBATE_BP * 1e-4) * px * qty
        self.q += sgn * qty
        self.cash -= sgn * qty * px + fee
        st_obi = getattr(self.S, "own_obi", None)                      # 成交那一刻策略自己看到的状态(估表用)
        sc = self.S._fm_scores(ts) if hasattr(self.S, "_fm_scores") else None
        self.fills.append((ts, sd, tick, size, 0 if taker else 1, o.level0 if o else None, o.ahead0 if o else None,
                           (ts - o.rest_at) / 1e6 if o else None, (o.rest_at - o.born) / 1e6 if o else None,
                           st_obi, sc[0] if sc else None, sc[1] if sc else None,
                           o.born if o else None, o.rest_at if o else None, o.ahead if o else None, sweep_qty))
        f = SimpleNamespace(symbol=SYMN, side=Side("buy" if sd == 0 else "sell"), price=Decimal(str(round(px, 1))),
                            quantity=Decimal(str(round(qty, 6))), fee=Decimal(str(fee)), is_maker=not taker, ts_ns=ts)
        self.S.on_fill(f)

    # ---------------- L3Sim 回调 ----------------
    def _start(self):
        if not self.started:
            self.S.on_start()
            self.started = True

    def on_fill(self, sim, o, qty, ts, sweep_qty):
        self.now = ts
        self._book_fill(o.side, o.tick, qty, ts, o=o, sweep_qty=sweep_qty)
        if o.state == "filled":
            self.seen[o.tag] = "filled"
            self.by_oid.pop(o.tag, None)
            self._report(o.tag, OrderStatus("filled"))

    def on_break(self, sim, ts):
        self.last_top = None

    def on_public_trade(self, ts, taker_side, tick, size):
        if not self.started or tick is None:
            return
        self.now = ts
        t = SimpleNamespace(symbol=SYMN, price=Decimal(str(round(tick * L.TICK, 1))), size=Decimal(str(round(size * MULT, 6))),
                            side=Side("buy" if taker_side > 0 else "sell"), ts_ns=ts)
        self.S.on_tick(t)

    def on_event(self, sim, ts):
        self.sim = sim
        self._start()
        self.now = ts
        self.lat = self.lat_md
        self._sync_reports()
        bids, asks = sim.touch.top(0), sim.touch.top(1)
        if not bids or not asks:
            return
        top = (tuple(bids), tuple(asks))
        if top == self.last_top:
            return
        self.last_top = top
        d = SimpleNamespace(symbol=SYMN, ts_ns=ts,
                            bids=[SimpleNamespace(price=k * L.TICK, size=v * MULT) for k, v in bids],
                            asks=[SimpleNamespace(price=k * L.TICK, size=v * MULT) for k, v in asks])
        self.n_depth += 1
        self.S.on_depth(d)

    def on_ref(self, t_arr, side, qty, px):
        if not self.started:
            return
        self.now = t_arr
        self.lat = self.lat_ref
        self._sync_reports()
        tk = SimpleNamespace(symbol=SYMN, side=Side(side), size=Decimal(str(qty)), price=Decimal(str(px)), ts_ns=t_arr)
        self.n_ref += 1
        self.S.on_ref_tick(tk)
        self.lat = self.lat_md


class RefLatency:
    """币安触发的动作:只加下单 / 撤单的实测延迟(行情延迟已经加在币安成交的到达时刻上)。"""

    def __init__(self, emp):
        self.emp = emp

    def delay(self, ts, kind="open"):
        lead, jit = self.emp.lead, self.emp.md_jitter
        self.emp.lead, self.emp.md_jitter = 0, False
        try:
            return self.emp.delay(ts, kind)
        finally:
            self.emp.lead, self.emp.md_jitter = lead, jit


def md_sample(rng, n):
    qp = [p for p, _ in L.EmpiricalLatency.MD_QUANTILES]
    ql = [math.log(v) for _, v in L.EmpiricalLatency.MD_QUANTILES]
    u = rng.random(n)
    j = np.clip(np.searchsorted(qp, u, side="right") - 1, 0, len(qp) - 2)
    w = (u - np.take(qp, j)) / (np.take(qp, j + 1) - np.take(qp, j))
    return np.exp(np.take(ql, j) * (1 - w) + np.take(ql, j + 1) * w)      # 毫秒


def main():
    path, tag, day, hours = sys.argv[1], sys.argv[2], sys.argv[3], [h.zfill(2) for h in sys.argv[4].split(",")]
    over = dict(kv.split("=", 1) for kv in sys.argv[5:])
    src = open(path, encoding="utf-8").read()
    ns = {}
    exec(re.search(r"^DEFAULT_PARAMS = \{.*?\}\n", src, re.S | re.M).group(0), ns)
    params = dict(ns["DEFAULT_PARAMS"])
    for k, v in over.items():
        if k in params and isinstance(params[k], int) and not isinstance(params[k], bool) and not v.lstrip("-").isdigit():
            params[k] = float(v)                           # 默认值是整数、给的是小数(例如 pos_age_s = 0.01 秒)
        else:
            params[k] = type(params[k])(v) if k in params and not isinstance(params[k], str) else v
    table = np.load(os.path.join(ROOT, "data", "research7", "latency_empirical.npz"))
    load = P.Load()
    emp = L.EmpiricalLatency(load, table, lead_ms=0.3, seed=1, md_jitter=True)
    agent = StratAgent(path, params, emp, RefLatency(emp))
    sim = Sim(SYM, L.Latency(load=load), [agent], trade_ticks=P.load_trade_ticks(day, hours, SYM))
    sim.fresh_ns = 5 * L.MS
    agent.sim = sim
    # 币安成交,按到达时刻排好
    z = zipfile.ZipFile(os.path.join(ROOT, "data", "research5", "binance_hist", "BTCUSDT-aggTrades-%s-%s-%s.zip" % (day[:4], day[4:6], day[6:])))
    B = pd.read_csv(z.open(z.namelist()[0]))
    h0 = P.hour_start_ns(day, hours[0]) // 1_000_000 - 400_000
    h1 = P.hour_start_ns(day, hours[-1]) // 1_000_000 + 3_700_000
    B = B[(B["transact_time"] >= h0) & (B["transact_time"] <= h1)]
    rng = np.random.default_rng(7)
    arr = (B["transact_time"].to_numpy(np.int64) * 1_000_000 + (md_sample(rng, len(B)) * 1e6).astype(np.int64))
    o = np.argsort(arr, kind="stable")
    arr = arr[o]
    bside = np.where(B["is_buyer_maker"].astype(str).str.lower().to_numpy()[o] == "true", "sell", "buy")
    bq, bpx = B["quantity"].to_numpy(float)[o], B["price"].to_numpy(float)[o]
    print("币安成交 %d 笔;参数覆盖 %s" % (len(arr), over), flush=True)
    k = int(np.searchsorted(arr, P.hour_start_ns(day, hours[0])))     # 预热段(上一小时末尾)的币安成交不推给策略
    t_start = time.time()
    stop_ns = int(over.pop("_stop_min", 0) or 0) * 60 * 1_000_000_000   # 冒烟测试用:只跑前几分钟
    first = True
    for hh in hours:
        f = os.path.join(L.L3_DIR[SYM], day, f"{hh}_{SYM}_l3.jsonl.gz")
        if first:
            sim._prewarm(day, hh, 300)
            first = False
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    j = line.rfind(b'"ts":')
                    if j > 0 and sim.ready:
                        ts = int(line[j + 5:j + 24].split(b"}")[0].split(b",")[0])
                        if stop_ns and ts > P.hour_start_ns(day, hours[0]) + stop_ns:
                            break
                        while k < len(arr) and arr[k] <= ts:
                            sim._advance(int(arr[k]))
                            agent.on_ref(int(arr[k]), bside[k], bq[k], bpx[k])
                            k += 1
                    elif j > 0:
                        ts = int(line[j + 5:j + 24].split(b"}")[0].split(b",")[0])
                        while k < len(arr) and arr[k] <= ts:
                            k += 1
                    sim.feed(line)
        except (EOFError, OSError, zlib.error):
            sim.breaks += 1
            sim._reset()
        print("  %s 时完成:成交 %d,盘口推送 %d,币安推送 %d,用时 %.0f 秒" % (hh, len(agent.fills), agent.n_depth, agent.n_ref, time.time() - t_start), flush=True)
    sim._flush()
    # 汇总
    os.makedirs(OUT, exist_ok=True)
    F = pd.DataFrame(agent.fills, columns=["ts", "sd", "tick", "size", "maker", "level0", "ahead0", "wait_ms", "lat_ms", "obi", "bnA", "bnB", "born_ns", "rest_ns", "ahead_fill", "sweep_qty"])
    F.to_csv(os.path.join(OUT, "%s_%s_fills.csv" % (tag, day)), index=False)
    g = np.load(os.path.join(ROOT, "data", "research7", "mid24", "%s_%s.npz" % (SYM, day)))
    mid = pd.Series(np.where(g["ok"], (g["bp"] + g["ap"]) / 2.0 * float(g["tick"]), np.nan)).ffill().to_numpy()
    t0g = int(g["t0"])
    res = dict(tag=tag, day=day, hours=hours, params_override=over, fills=len(F), breaks=sim.breaks, fresh_excluded=sim.fresh_n,
               strategy_stats={k: v for k, v in agent.S.st.items()})
    if len(F):
        px = F["tick"].to_numpy() * L.TICK
        sg = np.where(F["sd"] == 0, 1.0, -1.0)
        w = F["size"].to_numpy() * MULT * px
        for tau, nm in ((0.1, "mo_0.1s"), (1, "mo_1s"), (10, "mo_10s"), (60, "mo_60s")):
            kk = np.clip((F["ts"].to_numpy() + int(tau * 1e9) - t0g) // 10_000_000, 0, len(mid) - 1)
            res[nm] = float(np.average(sg * (mid[kk] - px) / px * 1e4, weights=w))
        last = mid[min((int(F["ts"].max()) - t0g) // 10_000_000 + 1, len(mid) - 1)]
        end_k = min((P.hour_start_ns(day, hours[-1]) + 3_600_000_000_000 - t0g) // 10_000_000, len(mid) - 1)
        res["notional_usd"] = float(w.sum())
        res["pnl_usd"] = float(agent.cash + agent.q * mid[end_k])
        res["q_end"] = agent.q
        res["maker_share_at_touch"] = float((F["level0"] == 0).mean())
        res["ahead0_median"] = float(F["ahead0"].median())
        res["wait_ms_median"] = float(F["wait_ms"].median())
    json.dump(res, open(os.path.join(OUT, "%s_%s.json" % (tag, day)), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(res, ensure_ascii=False, default=str), flush=True)
    print("L3_STRATEGY_DONE", flush=True)


if __name__ == "__main__":
    main()
