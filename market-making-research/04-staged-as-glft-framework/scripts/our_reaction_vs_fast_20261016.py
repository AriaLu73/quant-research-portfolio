#!/usr/bin/env python3
"""我们的实际反应时间 vs L3 里最快的人(用户 10-16:"去做")。只读,线下;实盘日志是已下载的本地文件,不连服务器。

数据   我方:data/research7/live_orders_20261014.jsonl.gz(实盘引擎记录:下单 / 撤单发出时刻 ts_ns = 服务器时钟;交易所单号 exchange_order_id)。
       KuCoin BTC-USDT 永续 L3:data/research5/usdc_pairs_l3usdt/20261014/<hh>_XBTUSDTM_l3.jsonl.gz(交易所时间 ts,毫秒)。
       我方的单在 L3 里也有(同一个交易所单号):received = 交易所收到我们这张单的时刻,done = 撤掉 / 成交完的时刻。
       币安:data/research5/binance_hist/BTCUSDT-aggTrades-2026-10-14.zip(币安撮合时间,毫秒)。
事件   同 pre_move_l3_20261016.py 的事件 A:币安同一毫秒同方向把价格推动 ≥ 1 bp,之前 500 毫秒同方向干净。T = 币安撮合时间。
看什么 ① 被扫一侧、离 KuCoin 最近成交价 2 bp 以内、在 T 之前已经挂着的单,T 之后多久被撤掉(只算 T 后 200 毫秒内撤掉的):我方 vs 其他人。
       ② 同样这些单里,我方的单 T 时在场的有几张、200 毫秒内撤掉 / 被成交 / 还挂着各几张。
       ③ 我方链路:撤单从引擎发出到交易所撤掉、下单从引擎发出到交易所收到(服务器时钟 → 交易所时钟,含两边时钟偏差)。
       ④ 我方撤单发出时刻相对 T 的分布(服务器时钟 vs 币安时钟,含偏差)。
时钟   三个时钟(币安、KuCoin、我方服务器)互相可能差几毫秒,这里没法单独校准;毫秒以内的先后不下结论。
用法   .venv/Scripts/python.exe scripts/research7/our_reaction_vs_fast_20261016.py 13 14
"""
import gzip, json, os, re, sys, zipfile
import numpy as np
import orjson
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
hours = [int(x) for x in sys.argv[1:]] or [13, 14]

# ---------------- 我方实盘日志 ----------------
new_sent, ex_of, cxl_sent = {}, {}, {}
with gzip.open(os.path.join(ROOT, "data", "research7", "live_orders_20261014.jsonl.gz"), "rt", encoding="utf-8") as f:
    for l in f:
        r = json.loads(l)
        o = r["obj"]
        mt = r["msg_type"]
        if mt == "Order" and o.get("symbol") == "BTC-USDT":
            new_sent[o["order_id"]] = int(o["ts_ns"])
        elif mt == "OrderReport" and o.get("exchange_order_id"):
            ex_of[o["order_id"]] = o["exchange_order_id"]
        elif mt == "KVGroup" and "BTC-USDT" in o:
            m1 = re.search(r'key: "exchange_order_id"\s*value: "(\d+)"', o)
            m2 = re.search(r"ts_ns: (\d+)", o)
            if m1 and m2:
                cxl_sent.setdefault(m1.group(1), int(m2.group(1)))
ours_new = {ex_of[k]: v for k, v in new_sent.items() if k in ex_of}
ours = set(ours_new)
print("我方 BTC:下单 %d 张(配上交易所单号 %d),撤单发出 %d 次" % (len(new_sent), len(ours), len(cxl_sent)), flush=True)

# ---------------- L3 ----------------
recv_ts = {}
side_of, px_of, open_of = {}, {}, {}
rows = []                                            # 已结束的单:开挂时刻、结束时刻、方向、价格、是否撤单、是否我方
lp_t, lp_p = [], []                                  # 成交(挂单价)时间序列,作参考价
for hh in hours:
    p = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt", "20261014", "%02d_XBTUSDTM_l3.jsonl.gz" % hh)
    with gzip.open(p, "rb") as fh:
        try:
            for ln in fh:
                m = orjson.loads(ln[ln.index(b"\t") + 1:])
                s = m.get("subject")
                d = m.get("data") or {}
                if s == "received":
                    if d["orderId"] in ours:
                        recv_ts[d["orderId"]] = int(d["ts"])
                elif s == "open":
                    oid = d["orderId"]
                    side_of[oid] = 1 if d["side"] == "buy" else -1
                    px_of[oid] = float(d["price"])
                    open_of[oid] = int(d["ts"]) // 1_000_000
                elif s == "done":
                    oid = d["orderId"]
                    if oid in side_of:
                        rows.append((open_of[oid], int(d["ts"]) // 1_000_000, side_of[oid], px_of[oid], d.get("reason") == "canceled", oid in ours,
                                     int(d["ts"]) if oid in ours else 0, oid if oid in ours else ""))
                        side_of.pop(oid); px_of.pop(oid); open_of.pop(oid)
                elif s == "match":
                    mp = px_of.get(d["makerOrderId"])
                    if mp:
                        lp_t.append(int(d["ts"]) // 1_000_000); lp_p.append(mp)
        except (EOFError, OSError):
            pass
    print("  L3 %02d 时读完,累计结束的单 %d" % (hh, len(rows)), flush=True)
# 还挂着没结束的我方单(文件末尾):记为一直在场
R = pd.DataFrame(rows, columns=["t_open", "t_done", "sd", "px", "cxl", "ours", "done_ns", "oid"])
lp_t, lp_p = np.array(lp_t), np.array(lp_p)
t_lo, t_hi = int(lp_t.min()) + 5000, int(lp_t.max()) - 1000

# ---------------- 币安事件 ----------------
z = zipfile.ZipFile(os.path.join(ROOT, "data", "research5", "binance_hist", "BTCUSDT-aggTrades-2026-10-14.zip"))
B = pd.read_csv(z.open(z.namelist()[0]))
B = B[(B["transact_time"] >= t_lo - 5000) & (B["transact_time"] <= t_hi)].reset_index(drop=True)
B["sd"] = np.where(B["is_buyer_maker"].astype(str).str.lower() == "true", -1, 1)
g = B.groupby(["transact_time", "sd"]).agg(last=("price", "last")).reset_index()
prev = B.groupby("transact_time")["price"].last().shift(1)
g["prev"] = g["transact_time"].map(prev)
g["mv"] = g["sd"] * (g["last"] - g["prev"]) / g["prev"] * 1e4
ev = g[(g["mv"] >= 1.0) & (g["transact_time"] > t_lo) & (g["transact_time"] < t_hi)].sort_values("transact_time")
E, last = [], {1: -10**15, -1: -10**15}
for t, sd in zip(ev["transact_time"].to_numpy(), ev["sd"].to_numpy()):
    if t - last[sd] >= 500:
        E.append((int(t), int(sd)))
    last[sd] = t
print("币安大扫单事件 %d 个" % len(E), flush=True)

# ---------------- ①② 被扫一侧近处的单,T 后多久撤 ----------------
R = R.sort_values("t_done").reset_index(drop=True)
td = R["t_done"].to_numpy()
lat_others, lat_ours = [], []
our_alive = {"在场": 0, "200ms内撤掉": 0, "200ms内被成交": 0, "200ms后还在": 0}
oursR = R[R["ours"]]
for T, d in E:
    k = np.searchsorted(lp_t, T, "right") - 1
    if k < 0:
        continue
    P0 = lp_p[k]
    hit = -d                                           # 往上扫 → 被扫的是卖单(sd = −1)
    a, b = np.searchsorted(td, T, "right"), np.searchsorted(td, T + 200, "right")
    w = R.iloc[a:b]
    w = w[(w["sd"] == hit) & (w["t_open"] < T) & ((w["px"] - P0).abs() / P0 * 1e4 <= 2.0) & w["cxl"]]
    lat_others += list(w.loc[~w["ours"], "t_done"] - T)
    lat_ours += list(w.loc[w["ours"], "t_done"] - T)
    o = oursR[(oursR["sd"] == hit) & (oursR["t_open"] < T) & (oursR["t_done"] > T) & ((oursR["px"] - P0).abs() / P0 * 1e4 <= 2.0)]
    for _, x in o.iterrows():
        our_alive["在场"] += 1
        if x["t_done"] <= T + 200:
            our_alive["200ms内撤掉" if x["cxl"] else "200ms内被成交"] += 1
        else:
            our_alive["200ms后还在"] += 1


def q(v):
    v = np.asarray(v, float)
    if not len(v):
        return "无"
    return "笔数 %6d | 10%% %4.0f  25%% %4.0f  中位 %4.0f  75%% %4.0f  90%% %4.0f 毫秒 | 5 毫秒内 %4.1f%%  10 毫秒内 %4.1f%%" % (
        len(v), *np.percentile(v, [10, 25, 50, 75, 90]), 100 * (v <= 5).mean(), 100 * (v <= 10).mean())


print("\n① 币安大扫单之后,KuCoin 被扫一侧、离最近成交价 2 bp 以内、事前就挂着的单,在 T 后 200 毫秒内被撤的:撤单时刻 − T")
print("  其他人:", q(lat_others))
print("  我方  :", q(lat_ours))
print("\n② 我方在 T 时、被扫一侧 2 bp 以内在场的单:", our_alive)

# ---------------- ③ 我方链路 ----------------
c_lat, n_lat = [], []
for _, x in oursR.iterrows():
    oid = x["oid"]
    if x["cxl"] and oid in cxl_sent:
        c_lat.append((x["done_ns"] - cxl_sent[oid]) / 1e6)
for oid, t in recv_ts.items():
    n_lat.append((t - ours_new[oid]) / 1e6)
c_lat, n_lat = np.array(c_lat), np.array(n_lat)
c_lat, n_lat = c_lat[np.abs(c_lat) < 5000], n_lat[np.abs(n_lat) < 5000]
print("\n③ 我方链路(服务器时钟 → 交易所时钟,毫秒,含时钟偏差;交易所时间是毫秒精度)")
for name, v in (("撤单:引擎发出 → 交易所撤掉", c_lat), ("下单:引擎发出 → 交易所收到", n_lat)):
    if len(v):
        print("  %-24s 笔数 %6d | 10%% %6.2f  中位 %6.2f  90%% %6.2f  99%% %7.2f" % (name, len(v), *np.percentile(v, [10, 50, 90, 99])))

# ---------------- ④ 我方撤单发出时刻相对币安事件 ----------------
cs = np.array(sorted(v / 1e6 for v in cxl_sent.values()))
rel = []
for T, d in E:
    a, b = np.searchsorted(cs, T), np.searchsorted(cs, T + 200)
    if b > a:
        rel.append(cs[a] - T)
print("\n④ 币安事件后 200 毫秒内我方发出的第一张撤单(不分侧):有 %d / %d 个事件;" % (len(rel), len(E)), q(rel))
