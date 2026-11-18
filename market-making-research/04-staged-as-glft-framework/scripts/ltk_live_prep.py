#!/usr/bin/env python3
"""research7 宽价差合约:把 9 月四个全合约日(09-10 / 18 / 21 / 24)的购买数据整理成仿真器输入,供实盘策略类回放。

用途      用户 2026-10-09:"这个策略拿 8–9 月的数据也跑一下"。8–9 月里有这五个股票合约数据的只有这四天(用户 10-01 重下的全合约
          盘口 + 成交,落在 data/<DD>/;memory purchased-data-pending)。没有逐笔委托 → 用 L2 推断排队(用户 2026-10-08 裁决)。
所属阶段  阶段 8 探针的补充检验;基础设施,不对应报价公式中的某一项。
输出      data/research7/l2/<合约>_<day>.npz(格式同 l2_prep.py)
          data/research7/ltk_live/bn_<币安合约>_<day>.npz:币安逐笔成交 ts(纳秒,成交时间)、px(美元)
数据来源  KuCoin:data/<DD>/<合约>.csv.gz 与 <合约>.csv(1).gz(盘口与成交同目录,靠表头 is_snapshot 判别;只读不移动)
          币安:data/research5/binance_hist/<合约>-aggTrades-<日期>.zip(币安官方历史数据;只读参考,用户 2026-10-06 裁决)
用法      Python314/python.exe scripts/research7/ltk_live_prep.py <YYYYMMDD> <KuCoin 合约> [...]
"""
import gzip
import os
import sys
import zipfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l2_prep as LP

ROOT = LP.ROOT
OUT = os.path.join(ROOT, "data", "research7", "ltk_live")


def _files(sym, day):
    """返回 (盘口文件, 成交文件)。"""
    d = os.path.join(ROOT, "data", day[6:])
    book = trades = None
    for nm in (sym + ".csv(1).gz", sym + ".csv.gz"):
        f = os.path.join(d, nm)
        if not os.path.exists(f):
            continue
        with gzip.open(f, "rt") as fh:
            head = fh.readline()
        if "is_snapshot" in head:
            book = f
        else:
            trades = f
    return book, trades


def kucoin(sym, day):
    if os.path.exists(os.path.join(LP.OUT, "%s_%s.npz" % (sym, day))):
        return                                                         # 已整理过(金属 / 大宗的 20 天由 l2_prep.py 生成)
    std = os.path.join(ROOT, "data", "book_l2", day[:4], day[4:6], day[6:], sym + ".csv.gz")
    if os.path.exists(std):
        LP.tardis(day, sym)                                            # 标准布局(08-26 … 09-24 的金属、大宗合约)
        return
    fb, ft = _files(sym, day)
    if fb is None or ft is None:
        print("ltk_live_prep %s %s: 缺文件  PREP_MISSING" % (sym, day), flush=True)
        return
    tick = LP.tick_of(sym)
    b = pd.read_csv(fb, usecols=["timestamp", "is_snapshot", "side", "price", "amount"],
                    dtype={"timestamp": np.int64, "is_snapshot": bool, "side": "category", "price": np.float64, "amount": np.float64})
    snap = b.is_snapshot.values
    start = snap & ~np.r_[False, snap[:-1]]                            # 每个快照块的第一行之前插入一条重置(同 l2_prep.tardis)
    ts = b.timestamp.values * 1000                                     # 单位换算:微秒 → 纳秒
    side = (b.side.values == "ask").astype(np.int8)
    tk = np.rint(b.price.values / tick).astype(np.int32)
    size = np.rint(b.amount.values).astype(np.int32)
    kind = np.full(len(b), LP.K_LEVEL, np.int8)
    idx = np.nonzero(start)[0]
    ts = np.insert(ts, idx, ts[idx])
    kind = np.insert(kind, idx, LP.K_RESET)
    side = np.insert(side, idx, 0)
    tk = np.insert(tk, idx, 0)
    size = np.insert(size, idx, 0)
    t = pd.read_csv(ft, usecols=["timestamp", "side", "price", "amount"])
    LP._save(sym, day,
             np.r_[ts, t.timestamp.values.astype(np.int64) * 1000], np.r_[kind, np.full(len(t), LP.K_TRADE, np.int8)],
             np.r_[side, (t.side.values == "buy").astype(np.int8)], np.r_[tk, np.rint(t.price.values / tick).astype(np.int32)],
             np.r_[size, np.rint(t.amount.values).astype(np.int32)])
    print("ltk_live_prep %s %s: 盘口行 %d,成交 %d 笔,一跳 %s" % (sym, day, len(b), len(t), tick), flush=True)


def binance(bsym, day):
    f = os.path.join(ROOT, "data", "research5", "binance_hist", "%s-aggTrades-%s-%s-%s.zip" % (bsym, day[:4], day[4:6], day[6:]))
    if os.path.exists(os.path.join(OUT, "bn_%s_%s.npz" % (bsym, day))):
        return
    if not os.path.exists(f):
        print("ltk_live_prep %s %s: 没有币安文件  PREP_MISSING" % (bsym, day), flush=True)
        return
    with zipfile.ZipFile(f) as z:
        d = pd.read_csv(z.open(z.namelist()[0]))
    d.columns = [c.strip().lower() for c in d.columns]
    t = d["transact_time"].values.astype(np.int64)
    t = t * (1_000_000 if t[0] < 10**14 else 1000)                    # 单位换算:毫秒(或微秒)→ 纳秒
    o = np.argsort(t, kind="stable")
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(os.path.join(OUT, "bn_%s_%s.npz" % (bsym, day)), ts=t[o], px=d["price"].values.astype(np.float64)[o])
    print("ltk_live_prep %s %s: 币安成交 %d 笔" % (bsym, day, len(d)), flush=True)


if __name__ == "__main__":
    day = sys.argv[1]
    for sym in sys.argv[2:]:
        kucoin(sym, day)
        binance(sym[:-1], day)
    print("PREP_DONE", flush=True)
