#!/usr/bin/env python3
"""策略第 11 步(拥堵加宽)负载分档门槛 load_edges 的每日标定,按实盘策略实际收到的行情条数来标(用户 10-15:"每天标定一次")。

为什么不用 as_offline.estimate_load_edges:那个函数数的是购买数据切片里的全部盘口增量 + 成交,只有到 09-24 的日子有;
  而实盘策略数的是"适配器发布给它的盘口帧 + 逐笔成交":适配器(adapters/kucoin/main.py)只在增量动到前 depth_publish_levels 档
  (实盘 exchanges.yaml 设为 5,10-13 起;代码默认 50)时才发布,并且同一合约 1 毫秒内的多次发布合并成一次(depth_conflate_ms 默认 1)。
做法:把自采的原始消息(data/research5/usdc_pairs/<day>/<hh>_<SYM>_{l2,trades,snap}.jsonl.gz,和实盘走同一路 KuCoin 公共行情)
  用实盘同一份订单簿代码 adapters/kucoin/l2book.KucoinL2Book 重放(REST 快照校准、序号缺口时等下一个快照),
  按上面两条规则数出"策略会收到的盘口帧",加上逐笔成交;时间用交易所时间(实盘策略记的也是交易所时间)。
  门槛的定法与 as_offline.estimate_load_edges 相同:12–18 时 UTC 每 100 毫秒一个格点,
  让"策略数到的条数"各档占的时间 = 实测撤单延迟表各档(按 BTC 的 L2 事件数 data/research7/l2/XBTUSDTM_<day>.npz 分)占的时间。
  没同步上的时段(序号缺口到下一个快照之间)不参加分位数。
用法:.venv/Scripts/python.exe scripts/research7/live_load_edges.py 20261014 XBTUSDTM ETHUSDTM
输出:打印每个合约的五个门槛,并写 data/research7/live_load_edges.json({日期: {合约: [...]}})。
"""
import array, gzip, heapq, json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from adapters.kucoin.l2book import KucoinL2Book   # noqa: E402

REC = os.path.join(ROOT, "data", "research5", "usdc_pairs")
TOP_N, CONFLATE_NS, WIN_NS = 5, 1_000_000, 100_000_000   # 10-15 更正:实盘 exchanges.yaml 设了 depth_publish_levels: 5(10-13 起),不是默认 50
LATENCY_TABLE = os.path.join(ROOT, "data", "research7", "latency_empirical_l2load.npz")
OUT = os.path.join(ROOT, "data", "research7", "live_load_edges.json")


def lines(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        try:
            for ln in f:
                t, _, js = ln.partition("\t")
                yield int(t), js
        except (EOFError, OSError):
            return                                         # 采集器重启留下的不完整文件:读到哪算哪


def stream(day, sym, kind, hours):
    for hh in hours:
        for rns, js in lines(os.path.join(REC, day, "%02d_%s_%s.jsonl.gz" % (hh, sym, kind))):
            yield rns, kind, js


def own_events(day, sym, hours):
    """返回 (事件时间 ns 数组, 同步时段 [(开始, 结束)])。"""
    ev, synced_spans = array.array("q"), []
    streams = []                                           # 每个文件各自按接收时间有序,归并成一条流(不整小时读进内存)
    for kind in ("l2", "trades", "snap"):
        for hh in hours:
            p = os.path.join(REC, day, "%02d_%s_%s.jsonl.gz" % (hh, sym, kind))
            if not os.path.exists(p):
                raise SystemExit("缺文件 %s" % p)
        streams.append(stream(day, sym, kind, list(hours)))
    book = KucoinL2Book(sym)                               # 跨小时沿用同一本簿,和实盘一样
    last_pub, dirty_ts, sync_from = 0, None, None
    if True:
        for rns, kind, js in heapq.merge(*streams, key=lambda x: x[0]):
            if dirty_ts is not None and rns >= last_pub + CONFLATE_NS:      # 合并窗口到点,补发一次
                ev.append(dirty_ts); last_pub, dirty_ts = last_pub + CONFLATE_NS, None
            m = json.loads(js)
            if kind == "snap":
                d = m.get("data") or {}
                if not book.synced and d.get("sequence"):
                    if book.load_snapshot(int(d["sequence"]), d.get("bids") or [], d.get("asks") or [], int(d.get("ts", 0) or 0) // 10**6) == "ok":
                        sync_from = None
                continue
            d = m.get("data") or {}
            if kind == "trades":
                ts = int(d.get("ts") or 0) or int(d.get("time") or 0)
                if ts:
                    ev.append(ts if ts > 10**15 else ts * 10**6)
                continue
            if "sequence" not in d or "change" not in d:            # 订阅回执等非增量消息
                continue
            was = book.synced
            r = book.on_update(int(d["sequence"]), str(d["change"]), int(d.get("timestamp") or 0), TOP_N)
            if was and not book.synced and sync_from is not None:
                synced_spans.append((sync_from, int(d.get("timestamp") or 0) * 10**6))
                sync_from = None
            if book.synced and sync_from is None:
                sync_from = int(d.get("timestamp") or 0) * 10**6
            if r != "top":
                continue
            ts = book.last_ts_ms * 10**6
            if rns - last_pub >= CONFLATE_NS:
                ev.append(ts); last_pub, dirty_ts = rns, None
            else:
                dirty_ts = ts
        if sync_from is not None:
            synced_spans.append((sync_from, int(day_t0(day)) + (max(hours) + 1) * 3600 * 10**9))
    return np.sort(np.frombuffer(ev, dtype=np.int64)), synced_spans


def day_t0(day):
    import datetime as dt
    return int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9


def edges_for(day, sym, h0=12, h1=18):
    t0 = day_t0(day)
    ts_l2 = np.load(os.path.join(ROOT, "data", "research7", "l2", "XBTUSDTM_%s.npz" % day))["ts"]
    edges = np.load(LATENCY_TABLE)["edges"]
    own, spans = own_events(day, sym, range(h0, h1))
    g = np.arange(t0 + h0 * 3600 * 10**9 + 10**9, t0 + h1 * 3600 * 10**9, WIN_NS)
    ok = np.zeros(len(g), bool)
    for a, b in spans:
        ok |= (g >= a + WIN_NS) & (g < b)
    cnt = lambda ts: np.searchsorted(ts, g, side="right") - np.searchsorted(ts, g - WIN_NS, side="right")
    l2, mine = cnt(ts_l2)[ok], cnt(own)[ok]
    res = [float(np.quantile(mine, min(float((l2 < e).mean()), 1.0))) for e in edges[1:]]
    return res, float(ok.mean()), float(mine.mean())


if __name__ == "__main__" and sys.argv[1] != "msgroup":
    day, syms = sys.argv[1], sys.argv[2:]
    allr = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    for s in syms:
        e, cov, mean = edges_for(day, s)
        print("%s %s 门槛 %s;同步覆盖 %.0f%% 的格点;平均每 100 毫秒 %.1f 条" % (day, s, [round(x, 1) for x in e], 100 * cov, mean), flush=True)
        allr.setdefault(day, {})[s] = e
    json.dump(allr, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------------------------------
# 2026-10-15(用户:实盘改成跟回测一样,门槛按回测同一办法标):实盘适配器改为按交易所毫秒成组发布(depth_group: exchange_ms、
# depth_trigger: any)后,策略每 100 毫秒数到的条数 = 这段时间里"有价位变化的交易所毫秒数 + 成交笔数"——和回测数据每毫秒一行完全同口径。
# 门槛就按 as_offline.estimate_load_edges 的办法:前一天 12–18 时 UTC,每 100 毫秒格点数上面的条数,与实测撤单延迟表各档(按 BTC 的 L2 事件数分)对齐。
# 用法:.venv/Scripts/python.exe scripts/research7/live_load_edges.py msgroup 20261014 XBTUSDTM ETHUSDTM
def msgroup_events(day, sym, hours):
    ev = []
    for hh in hours:
        last = None
        for rns, js in lines(os.path.join(REC, day, "%02d_%s_l2.jsonl.gz" % (hh, sym))):
            d = json.loads(js).get("data") or {}
            if "timestamp" not in d or "change" not in d:
                continue
            ms = int(d["timestamp"])
            if ms != last:
                ev.append(ms * 10**6)
                last = ms
        for rns, js in lines(os.path.join(REC, day, "%02d_%s_trades.jsonl.gz" % (hh, sym))):
            d = json.loads(js).get("data") or {}
            ts = int(d.get("ts") or 0)
            if ts:
                ev.append(ts if ts > 10**15 else ts * 10**6)
    return np.sort(np.array(ev, dtype=np.int64))


def edges_msgroup(day, sym, h0=12, h1=18):
    t0 = day_t0(day)
    ts_l2 = np.load(os.path.join(ROOT, "data", "research7", "l2", "XBTUSDTM_%s.npz" % day))["ts"]
    ed = np.load(LATENCY_TABLE)["edges"]
    own = msgroup_events(day, sym, range(h0, h1))
    g = np.arange(t0 + h0 * 3600 * 10**9 + 10**9, t0 + h1 * 3600 * 10**9, WIN_NS)
    cnt = lambda ts: np.searchsorted(ts, g, side="right") - np.searchsorted(ts, g - WIN_NS, side="right")
    l2, mine = cnt(ts_l2), cnt(own)
    return [float(np.quantile(mine, min(float((l2 < e).mean()), 1.0))) for e in ed[1:]], float(mine.mean())


if __name__ == "__main__" and sys.argv[1] == "msgroup":
    day, syms = sys.argv[2], sys.argv[3:]
    OUT2 = os.path.join(ROOT, "data", "research7", "live_load_edges_msgroup.json")
    allr = json.load(open(OUT2, encoding="utf-8")) if os.path.exists(OUT2) else {}
    for s_ in syms:
        e, mean = edges_msgroup(day, s_)
        print("%s %s 门槛(按回测办法,交易所毫秒成组)%s;平均每 100 毫秒 %.1f 条" % (day, s_, [round(x, 1) for x in e], mean), flush=True)
        allr.setdefault(day, {})[s_] = e
    json.dump(allr, open(OUT2, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
