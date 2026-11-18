#!/usr/bin/env python3
"""成交检查 A 的实盘部分:10-14 实盘 V2.1 BTC 的挂单成交,报价是不是过时;以及三个时钟是否对齐。只读,线下(实盘日志是本地副本)。

数据   实盘日志 data/research7/live_orders_20261014.jsonl.gz(服务器时钟:下单发出 ts_ns;成交回报);
       KuCoin L3(交易所时间):我方订单的 received(交易所收到)/ open(挂进盘口)/ match(成交);逐毫秒买一卖一(data/research7/market)。
       时段:10-14 的 10–17 时 UTC(逐毫秒买一卖一只做了这几个小时)。
报告   ① 时钟:交易所收到 − 服务器发出(中位 / 1% / 99%;出现负数说明服务器时钟比交易所快);
       ② 我方实盘成交:挂进盘口到成交的时长(订单年龄)、成交前 5 / 20 / 100 毫秒中间价变化(按挂单方向)、成交后 1 / 10 / 100 / 1,000 毫秒 markout;
          按"成交前 20 毫秒价格已朝我们压过来多少"分组。
用法   .venv/Scripts/python.exe scripts/research7/fill_check_live_20261017.py
"""
import gzip, json, os
import numpy as np
import orjson
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOURS = range(10, 18)
sent, ex_of = {}, {}
with gzip.open(os.path.join(ROOT, "data", "research7", "live_orders_20261014.jsonl.gz"), "rt", encoding="utf-8") as f:
    for l in f:
        r = json.loads(l)
        o = r["obj"]
        if r["msg_type"] == "Order" and o.get("symbol") == "BTC-USDT":
            sent[o["order_id"]] = int(o["ts_ns"])
        elif r["msg_type"] == "OrderReport" and o.get("exchange_order_id"):
            ex_of[o["order_id"]] = o["exchange_order_id"]
ours = {ex_of[k]: v for k, v in sent.items() if k in ex_of}
recv, opn, fills = {}, {}, []
for hh in HOURS:
    p = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt", "20261014", "%02d_XBTUSDTM_l3.jsonl.gz" % hh)
    with gzip.open(p, "rb") as fh:
        try:
            for ln in fh:
                if b"499" not in ln:                               # 粗筛(订单号都以 499 开头,仍需精确判断)
                    continue
                d = orjson.loads(ln[ln.index(b"\t") + 1:])
                s, dd = d.get("subject"), d.get("data") or {}
                if s == "received" and dd.get("orderId") in ours:
                    recv[dd["orderId"]] = int(dd["ts"])
                elif s == "open" and dd.get("orderId") in ours:
                    opn[dd["orderId"]] = (int(dd["ts"]), 0 if dd["side"] == "buy" else 1, float(dd["price"]))
                elif s == "match" and dd.get("makerOrderId") in ours:
                    fills.append((int(dd["ts"]), dd["makerOrderId"], float(dd["size"])))
        except (EOFError, OSError):
            pass
lines = []
P = lambda s="": (lines.append(s), print(s, flush=True))
lat = np.array([(recv[k] - ours[k]) / 1e6 for k in recv])
P("① 时钟对齐:交易所收到 − 服务器发出(毫秒,%d 张单):中位 %.2f,1%% %.2f,99%% %.2f,负数比例 %.2f%%" % (
    len(lat), np.median(lat), np.percentile(lat, 1), np.percentile(lat, 99), 100 * (lat < 0).mean()))
bb = np.concatenate([np.load(os.path.join(ROOT, "data", "research7", "market", "XBTUSDTM_20261014_%02d.npz" % h))["bbo"] for h in HOURS])
bb = bb[np.argsort(bb[:, 0], kind="stable")]
bt, mid = bb[:, 0], (bb[:, 1] + bb[:, 2]) / 2.0 * 0.1
at = lambda t: mid[np.clip(np.searchsorted(bt, np.asarray(t, np.int64), side="right") - 1, 0, len(mid) - 1)]
rows = []
for ts, oid, sz in fills:
    if oid not in opn:
        continue
    t_open, sd, px = opn[oid]
    rows.append((ts, sd, px, sz, (ts - t_open) / 1e6))
F = pd.DataFrame(rows, columns=["ts", "sd", "px", "sz", "age_ms"])
ts, px = F["ts"].to_numpy(np.int64), F["px"].to_numpy()
sg = np.where(F["sd"] == 0, 1.0, -1.0)
w = F["sz"].to_numpy() * 0.001 * px
for X in (5, 20, 100):
    F["pre%d" % X] = sg * (at(ts - 1_000_000) - at(ts - X * 1_000_000)) / px * 1e4
for tau in (1, 10, 100, 1000):
    F["mo%d" % tau] = sg * (at(ts + tau * 1_000_000) - px) / px * 1e4
F["w"] = w
wm = lambda g, c: float(np.average(g[c], weights=g["w"])) if len(g) else np.nan
P("\n② 实盘 V2.1 BTC 挂单成交(10–17 时,能在 L3 里对上挂单的):%d 笔,成交额 $%.0f" % (len(F), w.sum()))
P("   订单年龄(挂进盘口到成交,毫秒):中位 %.0f,10%% %.0f,90%% %.0f" % (F["age_ms"].median(), F["age_ms"].quantile(0.1), F["age_ms"].quantile(0.9)))
P("   成交前中间价变化(bp,按挂单方向,负 = 已朝我们压过来):5ms %+.2f  20ms %+.2f  100ms %+.2f" % (wm(F, "pre5"), wm(F, "pre20"), wm(F, "pre100")))
P("   成交后 markout(bp):1ms %+.2f  10ms %+.2f  100ms %+.2f  1000ms %+.2f" % (wm(F, "mo1"), wm(F, "mo10"), wm(F, "mo100"), wm(F, "mo1000")))
P("   按成交前 20 毫秒价格变化分组:")
b = np.searchsorted([-0.5, -0.1, -1e-9, 1e-9], F["pre20"], side="right")
for i, lab in enumerate(["≤ −0.5", "−0.5 … −0.1", "−0.1 … 0", "= 0", "> 0"]):
    g = F[b == i]
    if len(g):
        P("     %-12s %4d 笔  markout 1ms %+.2f  100ms %+.2f  1000ms %+.2f" % (lab, len(g), wm(g, "mo1"), wm(g, "mo100"), wm(g, "mo1000")))
open(os.path.join(ROOT, "data", "research7", "fill_check", "fill_check_A_live.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
