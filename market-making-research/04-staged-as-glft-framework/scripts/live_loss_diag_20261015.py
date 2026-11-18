#!/usr/bin/env python3
"""实盘 10-15 亏钱诊断 + 行情延迟实测(用户 10-15:"量,找为什么实盘亏钱")。只读本机数据。
输入:data/research7/live_orders_20261015.jsonl.gz(服务器总线记录,只读导出:下单 / 撤单 / 回报 / 成交)
      data/research7/l2/{ETHUSDTM,XBTUSDTM}_20261015.npz(本机自录 KuCoin 盘口事件,交易所时间)
      data/research5/usdc_pairs/20261015/*_trades(自录公共成交,含 takerOrderId,用于区分打穿 / 在我方价位排到)
① 行情延迟:对每一张被撤的挂单,找撤单发出前"我方价位变成最优价"(买单:买一 ≤ 我方价;卖单:卖一 ≥ 我方价)的最近一次交易所时刻,
   间隔 = 撤单发出(服务器时钟)− 那一刻(交易所时钟)= 行情送到 + 策略处理 + 发出撤单(含两边时钟差)。只算 1 秒以内的(多半是"成了盘口就撤"触发的)。
② 每笔成交:成交价相对当时中间价(交易所时间对齐的自录盘口)赚多少 bp(价差部分),成交后 1 / 10 / 60 秒中间价往哪走(按方向,正 = 对我方有利),
   返佣;按 合约 × 成交方式(在我方价位排到 / 打穿 / 主动吃单)汇总成美元。
"""
import bisect, collections, gzip, json, os, re, sys
import numpy as np
from sortedcontainers import SortedList

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "data", "research7", "live_orders_20261015.jsonl.gz")
NAT = {"ETH-USDT": ("ETHUSDTM", 0.01), "BTC-USDT": ("XBTUSDTM", 0.1)}
REC = os.path.join(ROOT, "data", "research5", "usdc_pairs", "20261015")


def bbo_series(nat):
    """返回 (时刻 ns 数组, 买一 tick, 卖一 tick):每个交易所毫秒结束后,只要买一或卖一变了就记一条。"""
    z = np.load(os.path.join(ROOT, "data", "research7", "l2", "%s_20261015.npz" % nat))
    ts, kind, side, tick, size = z["ts"], z["kind"], z["side"], z["tick"], z["size"]
    bids, asks, qty = SortedList(), SortedList(), [dict(), dict()]
    T, B, A = [], [], []
    lb = la = None
    n = len(ts)
    i = 0
    while i < n:
        t = ts[i]
        while i < n and ts[i] == t:
            k = kind[i]
            if k == 2:
                bids.clear(); asks.clear(); qty = [dict(), dict()]
            elif k == 1:
                s, p, q = int(side[i]), int(tick[i]), int(size[i])
                book = bids if s == 0 else asks
                if q > 0:
                    if p not in qty[s]:
                        book.add(p)
                    qty[s][p] = q
                elif p in qty[s]:
                    del qty[s][p]
                    book.remove(p)
            i += 1
        b = bids[-1] if bids else None
        a = asks[0] if asks else None
        if b is not None and a is not None and b < a and (b != lb or a != la):
            T.append(int(t)); B.append(b); A.append(a); lb, la = b, a
    return np.array(T, dtype=np.int64), np.array(B, dtype=np.int64), np.array(A, dtype=np.int64)


def main():
    new, cancel, fills = {}, {}, []
    with gzip.open(SRC, "rt", encoding="utf-8") as f:
        for l in f:
            r = json.loads(l)
            o, mt, w = r["obj"], r["msg_type"], r["wal_ts_ns"]
            if mt == "Order":
                new[o["order_id"]] = dict(w=w, sym=o["symbol"], side=o["side"], px=float(o["price"]) if o["price"] else None,
                                          qty=float(o["quantity"]), typ=o.get("order_type"), sid=o.get("strategy_id"), ro=o.get("reduce_only"))
            elif mt == "KVGroup":
                m = re.search(r'key: "order_id"\s*value: "([^"]+)"', o)
                if m and m.group(1) not in cancel:
                    cancel[m.group(1)] = w
            elif mt == "Fill":
                fills.append(o)
    ser = {}
    for sym, (nat, tk) in NAT.items():
        ser[sym] = bbo_series(nat)
        print("%s 盘口序列 %d 条变动,%s → %s" % (sym, len(ser[sym][0]), ser[sym][0][0], ser[sym][0][-1]), flush=True)

    # ① 行情延迟
    print("\n① 我方价位变成最优价 → 撤单发出(服务器时钟 − 交易所时钟,毫秒)")
    for sym, (nat, tk) in NAT.items():
        T, B, A = ser[sym]
        d = []
        for oid, cw in cancel.items():
            o = new.get(oid)
            if o is None or o["sym"] != sym or o["px"] is None:
                continue
            p = round(o["px"] / tk)
            j = bisect.bisect_right(T, cw) - 1
            if j < 0:
                continue
            touch = (lambda k: B[k] <= p) if o["side"] == "buy" else (lambda k: A[k] >= p)
            if not touch(j):
                continue
            while j > 0 and touch(j - 1):                  # 往回找这一段"成了最优价"的起点
                j -= 1
            if j == 0:
                continue
            dly = (cw - T[j]) / 1e6
            if 0 <= dly <= 1000 and T[j] >= o["w"]:        # 挂出之后才变成最优价、1 秒以内撤的
                d.append(dly)
        a = np.array(d)
        if len(a):
            print("  %s n=%d 中位 %.2f / 10%% %.2f / 90%% %.2f / 99%% %.2f 毫秒" % (sym, len(a), np.median(a), *np.percentile(a, [10, 90, 99])))

    # ② 成交拆解
    pub = {}
    for sym, (nat, tk) in NAT.items():
        for fn in sorted(os.listdir(REC)):
            if fn.endswith("_%s_trades.jsonl.gz" % nat):
                with gzip.open(os.path.join(REC, fn), "rt", encoding="utf-8") as fh:
                    try:
                        for ln in fh:
                            dd = json.loads(ln.partition("\t")[2]).get("data") or {}
                            if "tradeId" in dd:
                                pub[str(dd["tradeId"])] = (sym, float(dd["price"]), dd.get("takerOrderId"))
                    except (EOFError, OSError, ValueError):
                        pass
    by_taker = collections.defaultdict(list)
    for tid, (sym, px, tk_) in pub.items():
        by_taker[(sym, tk_)].append(px)

    def mid_at(sym, t):
        T, B, A = ser[sym]
        j = bisect.bisect_right(T, t) - 1
        if j < 0:
            return None
        return (B[j] + A[j]) / 2.0 * NAT[sym][1]

    agg = collections.defaultdict(lambda: collections.defaultdict(float))
    for o in fills:
        sym = o["symbol"]
        if sym not in ser:
            continue
        sgn = 1.0 if o["side"] == "buy" else -1.0
        px, q, t = float(o["price"]), float(o["quantity"]), int(o["ts_ns"])
        m0 = mid_at(sym, t - 1)                            # 成交前一刻的中间价
        if m0 is None:
            continue
        if not o.get("is_maker"):
            kind = "主动吃单(市价平仓等)"
        else:
            p = pub.get(str(o.get("trade_id")))
            if p is None:
                kind = "挂单·对不上公共成交"
            else:
                pxs = by_taker[(sym, p[2])]
                through = (min(pxs) < px - 1e-9) if o["side"] == "buy" else (max(pxs) > px + 1e-9)
                kind = "挂单·打穿" if through else "挂单·在我方价位排到"
        g = agg[(sym, kind)]
        g["n"] += 1; g["notional"] += px * q
        g["spread"] += sgn * (m0 - px) * q               # 价差部分:成交价相对成交前中间价
        g["rebate"] += -float(o["fee"])
        for h, lab in ((1, "mo1"), (10, "mo10"), (60, "mo60")):
            m1 = mid_at(sym, t + h * 10**9)
            if m1 is not None:
                g[lab] += sgn * (m1 - m0) * q              # 成交后中间价变动(对我方有利为正)
    print("\n② 实盘成交拆解(美元;价差 = 成交价相对成交前中间价;Δ1s/10s/60s = 之后中间价变动,按方向;返佣已单列)")
    tot = collections.defaultdict(float)
    for (sym, kind), g in sorted(agg.items()):
        print("  %s %-18s %3d 笔 成交额 $%9.0f | 价差 %+8.2f  返佣 %我方费率f | Δ1s %+8.2f  Δ10s %+8.2f  Δ60s %+8.2f | 每成交额(价差+返佣+Δ我方费率s) %+6.2f bp"
              % (sym, kind, g["n"], g["notional"], g["spread"], g["rebate"], g["mo1"], g["mo10"], g["mo60"],
                 (g["spread"] + g["rebate"] + g["mo60"]) / g["notional"] * 1e4 if g["notional"] else 0))
        for k in ("n", "notional", "spread", "rebate", "mo1", "mo10", "mo60"):
            tot[k] += g[k]
    print("  合计 %d 笔 成交额 $%.0f | 价差 %+.2f  返佣 %+.我方费率f | Δ1s %+.2f  Δ10s %+.2f  Δ60s %+.2f" % (tot["n"], tot["notional"], tot["spread"], tot["rebate"], tot["mo1"], tot["mo10"], tot["mo60"]))


if __name__ == "__main__":
    main()
