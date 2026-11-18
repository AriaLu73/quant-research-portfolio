#!/usr/bin/env python3
"""回测日子的负载门槛 load_edges,按"实盘发布规则"重新标定(2026-10-15,配合回测引擎 HFT_BT_DEPTH_TOPN=50 / HFT_BT_DEPTH_CONFLATE_MS=1)。

为什么要重标:回测引擎改成和实盘一样只在前 50 档有变化时才给策略发盘口、1 毫秒内合并之后,策略数到的"过去 100 毫秒行情条数"变少了,
  原来按"全部增量"标的门槛(as_offline.estimate_load_edges)就偏高。门槛要按策略实际会数到的条数重标。
做法:读 data/research7/l2/<合约>_<日>.npz 的事件(kind 0 成交、1 某价位新数量、2 整本重置、3 断流),重建订单簿,
  按回测引擎(engine/backtest/runner.py)同样的规则数"发给策略的盘口帧":增量动到前 50 档(改之前或之后)才算;
  距上次发布不足 1 毫秒的记为待发,到点补发一次;来了成交而有待发时先补发;整本重置算一帧。再加上逐笔成交条数。
  门槛定法与 as_offline.estimate_load_edges 相同:12–18 时 UTC 每 100 毫秒一个格点,
  让策略数到的条数各档占的时间 = 实测撤单延迟表各档(按 BTC 的 L2 事件数分)占的时间。
用法:Python314/python.exe scripts/research7/bt_load_edges.py ETHUSDTM 20260918 [更多日期 ...]
输出:data/research7/bt_load_edges_live.json({日期: {合约: [五个门槛]}}),as_offline 用 AS_LOAD_EDGES_JSON 指向它。
"""
import json, os, sys
import numpy as np
from sortedcontainers import SortedList

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L2 = os.path.join(ROOT, "data", "research7", "l2")
OUT = os.path.join(ROOT, "data", "research7", "bt_load_edges_live.json")
TOPN, CONF_NS, WIN = 5, 1_000_000, 100_000_000   # 10-15 更正:实盘发布前 5 档


def frames(sym, day, t_end):
    z = np.load(os.path.join(L2, "%s_%s.npz" % (sym, day)))
    ts, kind, side, tick, size = z["ts"], z["kind"], z["side"], z["tick"], z["size"]
    n = int(np.searchsorted(ts, t_end))
    bids, asks = SortedList(), SortedList()
    qty = [dict(), dict()]
    out = []
    last_pub, pend = -CONF_NS, None
    i = 0
    while i < n:
        t, k = int(ts[i]), int(kind[i])
        if pend is not None and t >= pend:                 # 到点补发
            out.append(pend); last_pub, pend = pend, None
        if k == 0:                                         # 成交:有待发先补发,再记一条成交
            if pend is not None:
                out.append(t); last_pub, pend = t, None
            out.append(t)
            i += 1
            continue
        if k == 2:                                         # 整本重置:清空,其后同一时刻的 kind 1 是整本盘口,一起算一帧
            bids.clear(); asks.clear(); qty = [dict(), dict()]
            j = i + 1
            while j < n and ts[j] == ts[i] and kind[j] == 1:
                s, p, q = int(side[j]), int(tick[j]), int(size[j])
                (bids if s == 0 else asks).add(p) if p not in qty[s] and q > 0 else None
                if q > 0:
                    qty[s][p] = q
                j += 1
            out.append(t); last_pub, pend = t, None
            i = j
            continue
        if k == 3:                                         # 断流开始
            i += 1
            continue
        # 同一时刻的一串价位变化 = 购买数据里的一行增量 = 回测引擎里的一条盘口事件:整串一起算"动没动到前 50 档"
        j, top = i, False
        while j < n and ts[j] == ts[i] and kind[j] == 1:
            s, p, q = int(side[j]), int(tick[j]), int(size[j])
            book = bids if s == 0 else asks
            thr_b = (book[-TOPN] if len(book) >= TOPN else None) if s == 0 else (book[TOPN - 1] if len(book) >= TOPN else None)
            if q > 0:
                if p not in qty[s]:
                    book.add(p)
                qty[s][p] = q
            elif p in qty[s]:
                del qty[s][p]
                book.remove(p)
            if not top:
                thr_a = (book[-TOPN] if len(book) >= TOPN else None) if s == 0 else (book[TOPN - 1] if len(book) >= TOPN else None)
                top = any(th is None or (p >= th if s == 0 else p <= th) for th in (thr_b, thr_a))
            j += 1
        if top:
            if t - last_pub < CONF_NS:
                pend = last_pub + CONF_NS
            else:
                out.append(t); last_pub, pend = t, None
        i = max(j, i + 1)
    return np.sort(np.array(out, dtype=np.int64))


def edges(sym, day, h0=12, h1=18):
    import datetime as dt
    t0 = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    own = frames(sym, day, t0 + h1 * 3600 * 10**9)
    ts_l2 = np.load(os.path.join(L2, "XBTUSDTM_%s.npz" % day))["ts"]
    ed = np.load(os.path.join(ROOT, "data", "research7", "latency_empirical_l2load.npz"))["edges"]
    g = np.arange(t0 + h0 * 3600 * 10**9 + 10**9, t0 + h1 * 3600 * 10**9, WIN)
    cnt = lambda a: np.searchsorted(a, g, side="right") - np.searchsorted(a, g - WIN, side="right")
    l2, mine = cnt(ts_l2), cnt(own)
    return [float(np.quantile(mine, min(float((l2 < e).mean()), 1.0))) for e in ed[1:]], float(mine.mean())


ENGINE_SYM = {"ETHUSDTM": "ETH_USDT", "XBTUSDTM": "BTC_USDT", "XBTUSDCM": "BTC_USDC"}


def edges_engine(sym, day, h0=12, h1=18, src=None):
    """按回测引擎自己记下的"发给策略的盘口帧 + 逐笔成交"(HFT_BT_FRAME_DUMP=1 的 frames.npz)标门槛:和回测里策略数到的条数完全一致。
    src = 从哪个合约的回测里取帧(引擎合约名去掉横杠,例 ETHUSDT:ETH 的回测同时喂了 BTC-USDT 行情);不给 = 本合约自己的回测。"""
    import datetime as dt, glob
    t0 = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    parts = []
    for hh in range(h0, h1):
        fs = sorted(glob.glob(os.path.join(ROOT, "data", "backtest_results", "*as_%s_%s_%02d_all4_*" % (src or ENGINE_SYM[sym].replace("_", ""), day, hh), "frames.npz")),
                    key=os.path.getmtime)
        if not fs:
            raise SystemExit("缺 %s %s %02d 时的 frames.npz:先跑 scripts/research7/bt_frames_dump_20261015.py" % (sym, day, hh))
        z = np.load(fs[-1])
        parts += [z["depth_" + ENGINE_SYM[sym]], z["tick_" + ENGINE_SYM[sym]]]
    own = np.sort(np.concatenate(parts))
    ts_l2 = np.load(os.path.join(L2, "XBTUSDTM_%s.npz" % day))["ts"]
    ed = np.load(os.path.join(ROOT, "data", "research7", "latency_empirical_l2load.npz"))["edges"]
    g = np.arange(t0 + h0 * 3600 * 10**9 + 10**9, t0 + h1 * 3600 * 10**9, WIN)
    cnt = lambda a: np.searchsorted(a, g, side="right") - np.searchsorted(a, g - WIN, side="right")
    l2, mine = cnt(ts_l2), cnt(own)
    return [float(np.quantile(mine, min(float((l2 < e).mean()), 1.0))) for e in ed[1:]], float(mine.mean())


if __name__ == "__main__":
    if sys.argv[1] == "engine":                            # 用回测引擎记下的帧标定(推荐;与回测完全一致)
        sym, days = sys.argv[2], sys.argv[3:]
        src = None
        if sym.count(":"):                                 # 例 XBTUSDTM:ETHUSDT = 从 ETH 回测记下的帧里取 BTC-USDT
            sym, src = sym.split(":")
        for day in days:
            e, m = edges_engine(sym, day, src=src)
            allr = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
            allr.setdefault(day, {})[sym] = e
            json.dump(allr, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("%s %s 门槛(引擎帧)%s;平均每 100 毫秒 %.1f 条" % (day, sym, [round(x, 1) for x in e], m), flush=True)
        sys.exit(0)
    sym, days = sys.argv[1], sys.argv[2:]
    for day in days:
        e, m = edges(sym, day)
        allr = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}   # 每天写一次,几个进程并行也不互相覆盖整份
        allr.setdefault(day, {})[sym] = e
        json.dump(allr, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("%s %s 门槛 %s;平均每 100 毫秒 %.1f 条" % (day, sym, [round(x, 1) for x in e], m), flush=True)
