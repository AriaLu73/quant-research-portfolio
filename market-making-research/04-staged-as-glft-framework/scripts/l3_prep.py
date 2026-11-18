#!/usr/bin/env python3
"""research7 逐笔委托数据的两个预处理步骤(都只读原始文件,结果写到 data/research7/)。

用途      load    每个小时、每毫秒的公开逐笔消息条数(XBTUSDTM + XBTUSDCM 合计)→ 延迟模型判定"交易所拥堵"用
          market  每个小时的买一卖一变化序列与每张吃单的成交明细 → 估计 σ、成交强度、计算 markout 用
所属阶段  阶段 0(研究基础设施)。不属于任何研究模块,不对应报价公式中的某一项。
变量与 <符号表> 的对应
          bb / ba   买一 / 卖一的整数 tick;S_t = (bb + ba) / 2 * TICK
          ε         吃单方向:taker_buy = +1(打到卖出报价),taker_sell = −1(打到买入报价);
                    对做市商(挂单方)而言成交方向 ε_mm = −ε_taker
用法      .venv/Scripts/python.exe scripts/research7/l3_prep.py load <YYYYMMDD> <HH>
          .venv/Scripts/python.exe scripts/research7/l3_prep.py market <YYYYMMDD> <HH>
"""
import datetime as dt
import gzip
import os
import sys
import zlib

import numpy as np
import orjson

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l3sim as L

OUT = os.path.join(L.ROOT, "data", "research7")
# 每个小时文件前后各留 2 秒的余量:消息的交易所时间戳与文件切分用的本机时间相差不到 2 秒
# (数据核对:10-01 14 时文件首条消息 ts 比文件名整点早 0.6 秒)。ASSUMPTION,只影响边界上极少数消息。
PAD_MS = 2000
HOUR_MS = 3_600_000


def hour_start_ns(day, hh):
    """UTC 的 day(YYYYMMDD)hh 时整点 → 纳秒时间戳。"""
    return int(dt.datetime.strptime(day + hh, "%Y%m%d%H").replace(tzinfo=dt.timezone.utc).timestamp()) * L.NS


def hours_of(day, sym="XBTUSDTM"):
    """这一天有逐笔委托文件的小时列表(字符串,升序)。"""
    d = os.path.join(L.L3_DIR[sym], day)
    return sorted(f[:2] for f in os.listdir(d) if f.endswith(f"_{sym}_l3.jsonl.gz")) if os.path.isdir(d) else []


# --------------------------------------------------------------------------------------------- load:拥堵判定的输入
def build_load(day, hh):
    """统计 [整点 − PAD, 整点 + 1 小时 + PAD) 内每毫秒的公开逐笔消息条数(两个合约合计,包含"received")。
    输出 data/research7/load/<day>_<hh>.npy:int32 累计条数 C,C[i] = 起点到第 i 毫秒(含)为止的总条数。
    没有用到未来数据:C 只是计数,使用时只取 C[i] − C[i − 100],即过去 100 毫秒。"""
    t0 = hour_start_ns(day, hh) // L.MS - PAD_MS            # 纳秒 → 毫秒
    n = HOUR_MS + 2 * PAD_MS
    cnt = np.zeros(n, np.int32)
    for sym in ("XBTUSDTM", "XBTUSDCM"):
        f = os.path.join(L.L3_DIR[sym], day, f"{hh}_{sym}_l3.jsonl.gz")
        if not os.path.exists(f):
            print(f"load {day} {hh}: 缺 {sym} 文件", flush=True)
            continue
        idx = []
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    j = line.rfind(b'"ts":')               # data.ts 总在行尾附近
                    if j > 0:
                        idx.append(int(line[j + 5:j + 18]) - t0)   # 取前 13 位 = 毫秒
        except (EOFError, OSError, zlib.error):
            pass
        a = np.asarray(idx, np.int64)
        a = a[(a >= 0) & (a < n)]
        cnt += np.bincount(a, minlength=n).astype(np.int32)
    os.makedirs(os.path.join(OUT, "load"), exist_ok=True)
    np.save(os.path.join(OUT, "load", f"{day}_{hh}.npy"), np.cumsum(cnt, dtype=np.int64).astype(np.int32))
    print(f"load {day} {hh}: {int(cnt.sum()):,} 条  LOAD_DONE", flush=True)


class Load:
    """给 l3sim.Latency 用:count(ts) = ts 之前 100 毫秒内(含 ts 所在毫秒)的消息条数。
    窗口 100 毫秒来源:docs/research6/step1 第 2 节(拥堵判定的口径,ASSUMPTION)。"""
    WIN_MS = 100

    def __init__(self):
        self.cache = {}

    def count(self, ts):
        h0 = ts // (HOUR_MS * L.MS) * HOUR_MS              # 所在小时的整点(毫秒)
        c = self.cache.get(h0)
        if c is None:
            t = dt.datetime.fromtimestamp(h0 / 1000, dt.timezone.utc)
            f = os.path.join(OUT, "load", f"{t.strftime('%Y%m%d')}_{t.strftime('%H')}.npy")
            c = self.cache[h0] = np.load(f) if os.path.exists(f) else False
            if len(self.cache) > 3:
                self.cache.pop(next(iter(self.cache)))
        if c is False:
            return 0                                       # 没有负载数据:按不拥堵(调用方在报告里注明)
        i = ts // L.MS - h0 + PAD_MS                       # 毫秒下标
        return int(c[i] - c[i - self.WIN_MS])


# --------------------------------------------------------------------------------------------- market:盘口与成交
def load_trade_ticks(day, hours, sym="XBTUSDTM"):
    """公开成交流:tradeId → 成交价 tick。给"没见过 open 的旧挂单"定成交价用(逐笔委托里 match.price 是吃单方的限价)。"""
    out = {}
    for hh in hours:
        f = os.path.join(L.TRD_DIR, day, f"{hh}_{sym}_trades.jsonl.gz")
        if not os.path.exists(f):
            continue
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    i = line.find(b"\t")
                    if i <= 0 or b'"match"' not in line:
                        continue
                    d = orjson.loads(line[i + 1:])["data"]
                    out[d["tradeId"]] = L.to_tick(d["price"])
        except (EOFError, OSError, zlib.error):
            pass
    return out


class Recorder:
    """收集买一卖一的每次变化、每张吃单的成交明细。"""

    def __init__(self):
        self.bbo, self.sw = [], []

    def on_bbo(self, ts, bb, ba, bsz, asz):
        self.bbo.append((ts, bb, ba, bsz, asz))

    def on_sweep(self, ts, maker_side, sweep):
        # 一张吃单:时间、挂单方一侧(0 = 打到买单,即吃单方卖出)、总张数、最先成交的 tick、最后(最差)成交的 tick、成交笔数
        self.sw.append((ts, maker_side, sum(s for _, s, _ in sweep), sweep[0][0], sweep[-1][0], len(sweep)))


def build_market(day, hh, sym="XBTUSDTM"):
    """重放一个小时(先用上一小时末尾 300 秒预热盘口),输出 data/research7/market/<sym>_<day>_<hh>.npz:
    bbo [n, 5] int64:时间(纳秒)、买一 tick、卖一 tick、买一张数、卖一张数(每次变化一行)
    sw  [m, 6] int64:见 Recorder.on_sweep
    meta:断流次数、可用起点(预热结束的时间)。"""
    rec = Recorder()
    sim = L.L3Sim(sym, L.Latency(), [], recorder=rec, trade_ticks=load_trade_ticks(day, [hh], sym))
    sim.run(day, [hh])
    os.makedirs(os.path.join(OUT, "market"), exist_ok=True)
    np.savez_compressed(os.path.join(OUT, "market", f"{sym}_{day}_{hh}.npz"),
                        bbo=np.asarray(rec.bbo, np.int64).reshape(-1, 5), sw=np.asarray(rec.sw, np.int64).reshape(-1, 6),
                        breaks=sim.breaks)
    print(f"market {sym} {day} {hh}: 买一卖一变化 {len(rec.bbo):,}  吃单 {len(rec.sw):,}  断流 {sim.breaks}  MARKET_DONE", flush=True)


if __name__ == "__main__":
    {"load": build_load, "market": build_market}[sys.argv[1]](*sys.argv[2:])
