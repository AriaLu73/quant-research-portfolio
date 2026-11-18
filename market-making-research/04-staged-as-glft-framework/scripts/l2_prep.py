#!/usr/bin/env python3
"""research7 把两种来源的价位汇总盘口(L2)与逐笔成交,转成同一种按时间排序的事件数组。

用途      没有逐笔委托的日子(2026-08-26 … 09-24,购买的 Tardis 数据)要用 L2 模拟排队(用户 2026-10-08 裁决);
          有逐笔委托的两天(10-01、10-02,自采)也转成同样的格式,用来标定 L2 排队推断相对真实排队的误差。
所属阶段  阶段 0 的补充(研究基础设施)。不属于研究模块,不对应报价公式中的某一项。
输出      data/research7/l2/<SYM>_<YYYYMMDD>.npz,五个等长数组(按 ts、同一时刻内按 kind 排序):
            ts    int64  交易所时间(纳秒;原始精度 1 毫秒)
            kind  int8   0 = 成交(吃单打到 side 一侧的挂单);1 = 某价位的新数量;2 = 盘口重置(其后紧跟整本盘口的 kind 1);
                         3 = 数据空档开始(断流,到下一次重置为止盘口不可信)
            side  int8   挂单方一侧:0 = 买盘,1 = 卖盘
            tick  int32  价格 / 0.1
            size  int32  张数(kind 0:成交张数;kind 1:该价位的新总张数,0 = 该价位清空)
          同一毫秒内成交排在盘口变化之前:成交造成的数量减少随后才体现在 L2 上,仿真器据此区分"成交减少"与"撤单减少"。
变量与 <符号表> 的对应  无(原始数据整理)。
数据来源  Tardis:data/book_l2/2026/<mm>/<dd>/<SYM>.csv.gz(incremental_book_L2)与 data/trades/2026/<mm>/<dd>/<SYM>.csv.gz
                  (列与单位见 data/README.md;timestamp 为交易所时间,微秒;amount 为张)
          自采:  data/research5/usdc_pairs/<day>/<hh>_<SYM>_{l2,trades,snap}.jsonl.gz(KuCoin /contractMarket/level2、execution、
                  REST 盘口快照;采集器 scripts/research5/usdc_pair_recorder.py)
用法      Python314/python.exe scripts/research7/l2_prep.py tardis <YYYYMMDD> [SYM]
          .venv/Scripts/python.exe scripts/research7/l2_prep.py own <YYYYMMDD> [SYM]
"""
import glob
import gzip
import os
import sys
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research7", "l2")
TICK = 0.1                 # 美元 / tick(合约接口存档 2026-10-02;XBTUSDTM 与 XBTUSDCM 相同)
K_TRADE, K_LEVEL, K_RESET, K_GAP = 0, 1, 2, 3


def tick_of(sym):
    """合约的最小价格变动(美元)。来源:KuCoin 公开合约接口的存档 data/research5/kucoin_contracts_20261002.json(2026-10-02)。
    2026-10-08 起按品种读取(此前写死为 XBTUSDTM 的 0.1);转换其它品种时必须用它,否则价格取整到错误的档位。"""
    import json
    j = json.load(open(os.path.join(ROOT, "data", "research5", "kucoin_contracts_20261002.json"), encoding="utf8"))
    for c in (j["data"] if isinstance(j, dict) else j):
        if c["symbol"] == sym:
            return float(c["tickSize"])
    raise KeyError(sym)


def _save(sym, day, ts, kind, side, tick, size):
    """按 (ts, kind) 稳定排序后保存。kind 的数值大小就是同一时刻内的处理顺序,但重置必须排在它带来的整本盘口之前:
    重置行与随后的 kind 1 行时间相同,稳定排序保持它们的原始先后,所以写入前调用方已保证重置行在前。"""
    order = np.lexsort((np.where(kind == K_TRADE, 0, 1), ts))        # 同一时刻:成交在前,其余保持原顺序
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(os.path.join(OUT, f"{sym}_{day}.npz"), ts=ts[order], kind=kind[order].astype(np.int8),
                        side=side[order].astype(np.int8), tick=tick[order].astype(np.int32), size=size[order].astype(np.int32))
    print(f"l2 {sym} {day}: 事件 {len(ts):,}  成交 {int((kind == K_TRADE).sum()):,}  重置 {int((kind == K_RESET).sum())}  空档 {int((kind == K_GAP).sum())}  L2PREP_DONE", flush=True)


def tardis(day, sym="XBTUSDTM"):
    """购买的 Tardis 数据 → 事件数组。快照块(is_snapshot = true 的连续行)前插入一条重置。"""
    import pandas as pd
    f = os.path.join(ROOT, "data", "book_l2", day[:4], day[4:6], day[6:], f"{sym}.csv.gz")
    b = pd.read_csv(f, usecols=["timestamp", "is_snapshot", "side", "price", "amount"],
                    dtype={"timestamp": np.int64, "is_snapshot": bool, "side": "category", "price": np.float64, "amount": np.float64})
    TICK = tick_of(sym)                                              # 本函数内用该品种的 tick(覆盖模块级的 BTC 默认值)
    snap = b.is_snapshot.values
    start = snap & ~np.r_[False, snap[:-1]]                           # 每个快照块的第一行
    ts = b.timestamp.values * 1000                                     # 单位换算:微秒 → 纳秒
    side = (b.side.values == "ask").astype(np.int8)
    tick = np.rint(b.price.values / TICK).astype(np.int32)             # 单位换算:美元 → tick
    size = np.rint(b.amount.values).astype(np.int32)
    kind = np.full(len(b), K_LEVEL, np.int8)
    idx = np.nonzero(start)[0]                                         # 在这些行之前各插入一条重置
    ts = np.insert(ts, idx, ts[idx]); kind = np.insert(kind, idx, K_RESET)
    side = np.insert(side, idx, 0); tick = np.insert(tick, idx, 0); size = np.insert(size, idx, 0)
    ft = os.path.join(ROOT, "data", "trades", day[:4], day[4:6], day[6:], f"{sym}.csv.gz")
    t = pd.read_csv(ft, usecols=["timestamp", "side", "price", "amount"])
    # 成交的 side 是吃单方向:buy = 打到卖盘(挂单方一侧 1),sell = 打到买盘(0)
    _save(sym, day,
          np.r_[ts, t.timestamp.values.astype(np.int64) * 1000], np.r_[kind, np.full(len(t), K_TRADE, np.int8)],
          np.r_[side, (t.side.values == "buy").astype(np.int8)], np.r_[tick, np.rint(t.price.values / TICK).astype(np.int32)],
          np.r_[size, np.rint(t.amount.values).astype(np.int32)])


def own(day, sym="XBTUSDTM"):
    """自采数据 → 事件数组。
    盘口:REST 快照给出整本盘口与它对应的序号;增量消息按序号接在快照之后。文件开头、以及每次重连(connect 标记)之后,
          用其后的第一份快照重置;重连到那份快照之间的增量丢弃,并在重连处记一条"空档开始"。
    没有用未来数据的问题:这里只是整理原始记录;快照在它的序号对应的时刻生效。"""
    import orjson
    global TICK
    TICK = tick_of(sym)          # 2026-10-11 修复:此前本函数一直用模块默认的 BTC 一跳(0.1),ETH / SOL 的价格被取整到错误的档位
    d = os.path.join(ROOT, "data", "research5", "usdc_pairs", day)
    ts, kind, side, tick, size = [], [], [], [], []
    add = lambda a, k, s, p, q: (ts.append(a), kind.append(k), side.append(s), tick.append(p), size.append(q))
    for f in sorted(glob.glob(os.path.join(d, f"??_{sym}_trades.jsonl.gz"))):
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    i = line.find(b"\t")
                    if i > 0 and b'"match"' in line:
                        m = orjson.loads(line[i + 1:])["data"]
                        add(int(m["ts"]), K_TRADE, 1 if m["side"] == "buy" else 0, int(round(float(m["price"]) / TICK)), int(m["size"]))
        except (EOFError, OSError, zlib.error):
            pass
    snaps = []                                                         # (序号, 买盘, 卖盘)
    for f in sorted(glob.glob(os.path.join(d, f"??_{sym}_snap.jsonl.gz"))):
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    i = line.find(b"\t")
                    if i > 0:
                        m = orjson.loads(line[i + 1:]).get("data")
                        if m and "sequence" in m:
                            snaps.append((int(m["sequence"]), m["bids"], m["asks"]))
        except (EOFError, OSError, zlib.error):
            pass
    snaps.sort(key=lambda x: x[0])
    need, si, last_ts, gap_seq = True, 0, 0, None                                     # need:正在等一份快照来重置
    for f in sorted(glob.glob(os.path.join(d, f"??_{sym}_l2.jsonl.gz"))):
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    i = line.find(b"\t")
                    if i <= 0:
                        continue
                    if b'"_marker"' in line:
                        if b'"connect"' in line and not need:
                            add(last_ts, K_GAP, 0, 0, 0)               # 重连:中间丢了多少不知道
                            need = True
                        continue
                    m = orjson.loads(line[i + 1:]).get("data")
                    if not m or "change" not in m:
                        continue
                    seq, t = int(m["sequence"]), int(m["timestamp"]) * 1_000_000      # 单位换算:毫秒 → 纳秒
                    last_ts = t
                    if need:
                        if gap_seq is None:
                            gap_seq = seq                              # 空档之后收到的第一条增量的序号
                        while si < len(snaps) and snaps[si][0] < gap_seq - 1:
                            si += 1                                    # 跳过空档之前拍的快照:它们接不上现在的增量
                        if si >= len(snaps) or seq <= snaps[si][0]:
                            continue                                   # 这条增量已包含在将要使用的快照里(或没有可用快照):丢弃
                        add(t, K_RESET, 0, 0, 0)                       # 快照在"序号刚超过它的第一条增量"的时刻生效
                        for s_, lv in ((0, snaps[si][1]), (1, snaps[si][2])):
                            for p, q in lv:
                                add(t, K_LEVEL, s_, int(round(float(p) / TICK)), int(q))
                        need, gap_seq = False, None
                        si += 1
                    p, s_, q = m["change"].split(",")
                    add(t, K_LEVEL, 0 if s_ == "buy" else 1, int(round(float(p) / TICK)), int(q))
        except (EOFError, OSError, zlib.error):
            add(last_ts, K_GAP, 0, 0, 0)
            need = True
    _save(sym, day, np.asarray(ts, np.int64), np.asarray(kind, np.int8), np.asarray(side, np.int8),
          np.asarray(tick, np.int32), np.asarray(size, np.int32))


if __name__ == "__main__":
    {"tardis": tardis, "own": own}[sys.argv[1]](*sys.argv[2:])
