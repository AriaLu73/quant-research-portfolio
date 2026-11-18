#!/usr/bin/env python3
"""本机自录的 KuCoin 盘口 / 成交(data/research7/l2/<合约>_<日>.npz,由 l2_prep.py own 生成)→ 回测引擎的数据切片格式,
和购买数据的切片(data/oos/ku_buyc/<日>_<时>/kucoin/swap/<合约>/feed_raw/)完全同格式:
  depth_deltas-<日>.jsonl.gz:每个交易所毫秒一行,含这一毫秒全部价位变化(价格字符串、数量换算成币);每个小时文件第一行是整本快照;
  ticks-<日>.jsonl.gz:逐笔成交(主动方方向)。
用途(用户 10-15:"昨天的啊你直接测不就行了"):用 10-14 自录数据跑回测,和 10-14 实盘逐小时对比。
输出 data/oos/ku_rec/<日>_<时>/kucoin/swap/<引擎合约名>/feed_raw/。
用法:Python314/python.exe scripts/research7/rec_to_feed.py 20261014 8 18 ETHUSDTM XBTUSDTM SOLUSDTM
"""
import datetime as dt, gzip, json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = {"XBTUSDTM": ("BTC-USDT", 0.1, 0.001), "ETHUSDTM": ("ETH-USDT", 0.01, 0.01), "SOLUSDTM": ("SOL-USDT", 0.001, 0.1)}


def fmt(x, step):
    d = max(0, -int(np.floor(np.log10(step) + 1e-9)))
    return ("%.*f" % (d, x)).rstrip("0").rstrip(".") if d else "%d" % round(x)


def convert(day, h0, h1, nat):
    sym, tick, mult = SPEC[nat]
    z = np.load(os.path.join(ROOT, "data", "research7", "l2", "%s_%s.npz" % (nat, day)))
    ts, kind, side, tk, size = z["ts"], z["kind"], z["side"], z["tick"], z["size"]
    t0 = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    book = [dict(), dict()]
    px = lambda t: fmt(t * tick, tick)
    qs = lambda q: fmt(q * mult, mult)
    n = len(ts); i = 0; seq = 0; cur_h = None; fd = ft = None; lines = 0
    def open_hour(h):
        nonlocal fd, ft, seq
        if fd:
            fd.close(); ft.close()
        out = os.path.join(ROOT, "data", "oos", "ku_rec", "%s_%02d" % (day, h), "kucoin", "swap", sym, "feed_raw")
        os.makedirs(out, exist_ok=True)
        fd = gzip.open(os.path.join(out, "depth_deltas-%s.jsonl.gz" % day), "wt", encoding="utf-8")
        ft = gzip.open(os.path.join(out, "ticks-%s.jsonl.gz" % day), "wt", encoding="utf-8")
        tsn = t0 + h * 3_600_000_000_000                  # 每个小时文件第一行:当时的整本盘口快照
        seq += 1
        fd.write(json.dumps({"ts_ns": tsn, "ts_ms": tsn // 10**6,
                             "bids": [[px(p), qs(q)] for p, q in sorted(book[0].items(), reverse=True)],
                             "asks": [[px(p), qs(q)] for p, q in sorted(book[1].items())],
                             "seq": seq, "prev_seq": seq - 1, "snapshot": True}) + "\n")
    while i < n:
        t = int(ts[i])
        h = (t - t0) // 3_600_000_000_000
        if h >= h1:
            break
        if h >= h0 and h != cur_h:
            open_hour(h); cur_h = h
        j = i
        bids, asks, snap = [], [], False
        trades = []
        while j < n and ts[j] == ts[i]:
            k = kind[j]
            if k == 0:
                trades.append(("sell" if side[j] == 0 else "buy", int(tk[j]), int(size[j])))   # side = 挂单方;主动方相反
            elif k == 2:
                book = [dict(), dict()]; snap = True; bids, asks = [], []
            elif k == 1:
                s, p, q = int(side[j]), int(tk[j]), int(size[j])
                if q > 0:
                    book[s][p] = q
                else:
                    book[s].pop(p, None)
                (bids if s == 0 else asks).append([px(p), qs(q)])
            j += 1
        if h >= h0 and cur_h is not None:
            for k_, (sd, p, q) in enumerate(trades):
                ft.write(json.dumps({"ts_ns": t + k_ * 1000, "ts_ms": t // 10**6, "price": px(p), "size": qs(q), "side": sd, "trade_id": ""}) + "\n")
            if snap:
                seq += 1
                fd.write(json.dumps({"ts_ns": t + 500, "ts_ms": t // 10**6,
                                     "bids": [[px(p), qs(q)] for p, q in sorted(book[0].items(), reverse=True)],
                                     "asks": [[px(p), qs(q)] for p, q in sorted(book[1].items())],
                                     "seq": seq, "prev_seq": seq - 1, "snapshot": True}) + "\n")
            elif bids or asks:
                seq += 1
                fd.write(json.dumps({"ts_ns": t + 500, "ts_ms": t // 10**6, "bids": bids, "asks": asks,
                                     "seq": seq, "prev_seq": seq - 1, "snapshot": False}) + "\n")
                lines += 1
        i = j
    if fd:
        fd.close(); ft.close()
    print("%s %s %02d–%02d 时:盘口行 %d" % (day, sym, h0, h1, lines), flush=True)


if __name__ == "__main__":
    day, h0, h1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    for nat in sys.argv[4:]:
        convert(day, h0, h1, nat)
