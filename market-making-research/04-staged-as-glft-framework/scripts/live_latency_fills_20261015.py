#!/usr/bin/env python3
"""B 步(用户 10-15:"B 做完之后再 A"):用实盘总线记录量这次部署真实的下单 / 撤单延迟,以及每笔成交是怎么来的。
输入:data/research7/live_orders_20261015.jsonl.gz(scripts/research7/export_live_orders.py 从服务器 WAL 只读导出)
      data/research5/usdc_pairs/20261015/*_{ETHUSDTM,XBTUSDTM}_trades.jsonl.gz(本机自录 KuCoin 公共成交,含 takerOrderId)
量什么:
  ① 下单:总线发出(order.new 的落盘时刻)→ 交易所受理(第一条 submitted 回报里的交易所时间)、→ 回报到本机(回报的落盘时刻)
  ② 撤单:撤单指令发出 → 交易所撤掉(cancelled 回报的交易所时间)、→ 回报到本机
     (服务器时钟和交易所时钟的差:用全部下单的"交易所时间 − 发出时刻"的最小值近似为单程的下限,不另做校正,原样报)
  ③ 每笔成交:按 tradeId 对上公共成交,同一个 takerOrderId 的主动单有没有打到比我方更深的价位 → 打穿 / 在我方价位排到
  ④ 在我方价位排到的成交:成交前这张单有没有已经发出撤单、发出了多久
"""
import collections, gzip, json, os, re, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "data", "research7", "live_orders_20261015.jsonl.gz")
REC = os.path.join(ROOT, "data", "research5", "usdc_pairs", "20261015")
NATIVE = {"ETH-USDT": "ETHUSDTM", "BTC-USDT": "XBTUSDTM"}

new, cancel, fills = {}, {}, []
first_rep = {}                                   # order_id → (状态, 交易所 ns, 落盘 ns)
cancelled = {}                                   # order_id → (交易所 ns, 落盘 ns)
rejected = collections.Counter()
with gzip.open(SRC, "rt", encoding="utf-8") as f:
    for l in f:
        r = json.loads(l)
        o, mt, w = r["obj"], r["msg_type"], r["wal_ts_ns"]
        if mt == "Order":
            new[o["order_id"]] = (w, o["symbol"], o["side"], o["price"], o["quantity"], o.get("strategy_id"), o.get("order_type"))
        elif mt == "KVGroup":
            m = re.search(r'key: "order_id"\s*value: "([^"]+)"', o)
            if m and m.group(1) not in cancel:
                cancel[m.group(1)] = w
        elif mt == "OrderReport":
            oid, s = o["order_id"], o["status"]
            if s in ("submitted", "partially_filled", "filled", "cancelled", "rejected") and oid not in first_rep:
                first_rep[oid] = (s, o["ts_ns"], w)
            if s == "cancelled" and oid not in cancelled:
                cancelled[oid] = (o["ts_ns"], w)
            if s == "rejected":
                rejected[o.get("error_msg", "")[:60]] += 1
        elif mt == "Fill":
            fills.append((w, o))

def q(a, ps=(50, 90, 99, 99.9)):
    a = np.asarray(a, float)
    return "n=%d 中位 %.2f / 90%% %.2f / 99%% %.2f / 99.9%% %.2f / 最大 %.1f 毫秒" % ((len(a),) + tuple(np.percentile(a, ps)) + (a.max(),)) if len(a) else "n=0"

ack_rt, ack_ex = [], []
for oid, (w, *_r) in new.items():
    fr = first_rep.get(oid)
    if fr and fr[0] != "rejected":
        ack_rt.append((fr[2] - w) / 1e6)
        ack_ex.append((fr[1] - w) / 1e6)
can_rt, can_ex = [], []
for oid, w in cancel.items():
    c = cancelled.get(oid)
    if c and c[1] >= w:
        can_rt.append((c[1] - w) / 1e6)
        can_ex.append((c[0] - w) / 1e6)
print("下单 发出 → 受理回报到本机:", q(ack_rt))
print("下单 发出 → 交易所受理(交易所时间 − 本机发出时刻,含两边时钟差):", q(ack_ex))
print("撤单 发出 → 撤单回报到本机:", q(can_rt))
print("撤单 发出 → 交易所撤掉(交易所时间 − 本机发出时刻,含时钟差):", q(can_ex))
print("被拒 %d 条,原因前几:%s" % (sum(rejected.values()), rejected.most_common(4)))

# ③④ 成交分类
pub = {}
for sym, nat in NATIVE.items():
    for fn in sorted(os.listdir(REC)):
        if fn.endswith("_%s_trades.jsonl.gz" % nat):
            with gzip.open(os.path.join(REC, fn), "rt", encoding="utf-8") as fh:
                try:
                    for ln in fh:
                        d = json.loads(ln.partition("\t")[2]).get("data") or {}
                        if "tradeId" in d:
                            pub[str(d["tradeId"])] = (sym, float(d["price"]), d.get("takerOrderId"), d.get("side"), int(d["ts"]))
                except (EOFError, OSError, ValueError):
                    pass                                 # 正在写的那个小时文件结尾不完整:读到哪算哪
by_taker = collections.defaultdict(list)
for tid, (sym, px, tk, sd, ts) in pub.items():
    by_taker[(sym, tk)].append(px)
rows = []
for w, o in fills:
    if o.get("order_id") not in new:
        continue                                 # 手动平仓等
    p = pub.get(str(o.get("trade_id")))
    if p is None:
        rows.append(dict(sym=o["symbol"], kind="未对上", sent_cancel=None)); continue
    sym, px, tk, sd, ts = p
    my_px = float(o["price"])
    pxs = by_taker[(sym, tk)]
    # 我方挂买单 → 主动卖;打穿 = 同一张主动单有成交价低于我方价
    through = (min(pxs) < my_px - 1e-9) if o["side"] == "buy" else (max(pxs) > my_px + 1e-9)
    cw = cancel.get(o["order_id"])
    sent = None if cw is None or cw > w else (o["ts_ns"] - cw) / 1e6   # 撤单在成交(交易所时间)之前多少毫秒发出
    rows.append(dict(sym=sym, kind="打穿" if through else "在我方价位排到", sent_cancel=sent, maker=o.get("is_maker")))
for sym in NATIVE:
    rs = [r for r in rows if r["sym"] == sym]
    k = collections.Counter(r["kind"] for r in rs)
    at = [r for r in rs if r["kind"] == "在我方价位排到"]
    sc = [r["sent_cancel"] for r in at if r["sent_cancel"] is not None]
    print("%s 成交 %d 笔:%s;在我方价位排到的 %d 笔里,成交前已经发出撤单的 %d 笔(撤单发出到成交:%s)"
          % (sym, len(rs), dict(k), len(at), len(sc), q(sc) if sc else "—"))
    th = [r for r in rs if r["kind"] == "打穿"]
    sc2 = [r["sent_cancel"] for r in th if r["sent_cancel"] is not None]
    print("    打穿的 %d 笔里,成交前已发出撤单的 %d 笔(%s)" % (len(th), len(sc2), q(sc2) if sc2 else "—"))
