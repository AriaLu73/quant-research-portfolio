#!/usr/bin/env python3
"""A 步(用户 10-16:"做A"):回测里为什么没有"在我方价位排到"的成交 —— 10-14 实盘 vs 同一天的回测(R0F = 实盘参数,10-16 修过发帧 bug 后重跑)逐笔对照。只读。

数据
  实盘  data/research7/live_orders_20261014.jsonl.gz(服务器总线导出):策略挂单、撤单指令、交易所回报、成交
  回测  R0 那次运行的 broker_sim_wal.jsonl(每张单的挂出 / 撤单指令 / 成交,引擎时间)
  公共成交  data/research5/usdc_pairs/20261014/<hh>_ETHUSDTM_trades.jsonl.gz(本机自录,含 takerOrderId)
做什么
  ① 两边每笔挂单成交分类:同一张主动单有没有打到比我方更深的价位 → "打穿" / "在我方价位排到"(实盘按 tradeId 对上;
     回测按成交时刻前 3 毫秒内、方向对、价格够得着我方的公共成交找主动单)
  ② 实盘每一笔"在我方价位排到"的成交时刻 T、价位 P:回测在 T 时刻同侧同价有没有挂着的单 ——
       a 有、而且还挂着 → 回测里这张单在队列里没排到(排队模型的差别)
       b 有过、但在 T 之前已经撤了 → 回测撤得比实盘快(报 回测撤单指令时刻 − T,和实盘这张单的撤单指令时刻 − T 对比)
       c 附近 2 秒内回测在这个价位根本没挂过 → 两边的报价路径已经不同(持仓 / 因子状态不一样),不能逐张比
  ③ 两边"成交前已发出撤单"的比例和时间差
用法  Python314/python.exe scripts/research7/live_vs_bt_queue_20261016.py
"""
import collections
import glob
import gzip
import json
import os
import re

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE = os.path.join(ROOT, "data", "research7", "live_orders_20261014.jsonl.gz")
REC = os.path.join(ROOT, "data", "research5", "usdc_pairs", "20261014")
BT_DIR = glob.glob(os.path.join(ROOT, "data", "backtest_results", "*ETHUSDT_as_ETHUSDT_20261014_09_all4_1016063945_0"))[0]   # R0
INST = "MmAsEth-1be9e2b6"
H0, H1 = 9, 18
D0 = 1791936000 * 10**9                                              # 2026-10-14 00:00 UTC
T0, T1 = D0 + H0 * 3600 * 10**9, D0 + H1 * 3600 * 10**9


def q(a):
    a = np.asarray(a, float)
    return "n=%d 中位 %.2f / 10%% %.2f / 90%% %.2f 毫秒" % (len(a), *np.percentile(a, (50, 10, 90))) if len(a) else "n=0"


# ---- 公共成交 ----
pub, by_taker = {}, collections.defaultdict(list)
trades = []                                                          # (ts_ns, 主动方向, 价格, takerOrderId)
for fn in sorted(os.listdir(REC)):
    if not fn.endswith("_ETHUSDTM_trades.jsonl.gz"):
        continue
    with gzip.open(os.path.join(REC, fn), "rt", encoding="utf-8") as fh:
        try:
            for ln in fh:
                d = json.loads(ln.partition("\t")[2]).get("data") or {}
                if "tradeId" in d:
                    rec = (int(d["ts"]), d["side"], float(d["price"]), d.get("takerOrderId"))
                    pub[str(d["tradeId"])] = rec
                    by_taker[d.get("takerOrderId")].append(float(d["price"]))
                    trades.append(rec)
        except (EOFError, OSError, ValueError):
            pass
trades.sort()
tr_ts = np.array([t[0] for t in trades], dtype=np.int64)


def through_of(taker, my_px, my_side):
    pxs = by_taker.get(taker, [])
    if not pxs:
        return None
    return (min(pxs) < my_px - 1e-9) if my_side == "buy" else (max(pxs) > my_px + 1e-9)


# ---- 实盘 ----
new, cancel_sent, cancelled_ex, fills = {}, {}, {}, []
rx = re.compile(r'key: "order_id"\s*value: "([^"]+)"')
with gzip.open(LIVE, "rt", encoding="utf-8") as f:
    for l in f:
        r = json.loads(l)
        o, mt, w = r["obj"], r["msg_type"], r["wal_ts_ns"]
        if mt == "Order" and o.get("strategy_id") == INST and o.get("order_type") == "limit":
            new[o["order_id"]] = (w, o["side"], float(o["price"]))
        elif mt == "KVGroup":
            m = rx.search(o)
            if m and m.group(1) in new and m.group(1) not in cancel_sent:
                cancel_sent[m.group(1)] = w
        elif mt == "OrderReport" and o["order_id"] in new and o["status"] == "cancelled" and o["order_id"] not in cancelled_ex:
            cancelled_ex[o["order_id"]] = int(o["ts_ns"])
        elif mt == "Fill" and o["order_id"] in new and o.get("is_maker"):
            fills.append(o)
live_rows = []
for o in fills:
    t = int(o["ts_ns"])
    if not (T0 <= t < T1):
        continue
    p = pub.get(str(o.get("trade_id")))
    kind = "未对上" if p is None else ("打穿" if through_of(p[3], float(o["price"]), o["side"]) else "排到")
    cs = cancel_sent.get(o["order_id"])
    live_rows.append(dict(t=t, side=o["side"], px=float(o["price"]), kind=kind, oid=o["order_id"],
                          cancel_before=None if cs is None or cs > t else (t - cs) / 1e6))

# ---- 回测 ----
bt_orders, bt_cancel, bt_fills = {}, {}, []
with open(os.path.join(BT_DIR, "broker_sim_wal.jsonl"), encoding="utf-8") as f:
    for l in f:
        r = json.loads(l)
        if r["t"] == "order" and r.get("symbol") == "ETH-USDT":
            bt_orders[r["id"]] = (int(r["ts_ns"]), r["side"], float(r["price"]))
        elif r["t"] == "cancel" and r["id"] not in bt_cancel:
            bt_cancel[r["id"]] = int(r["ts_ns"])
        elif r["t"] == "fill" and r["id"] in bt_orders:
            bt_fills.append((int(r["ts_ns"]), r["id"], float(r["px"])))
bt_rows = []
for t, oid, px in bt_fills:
    if not (T0 <= t < T1):
        continue
    side = bt_orders[oid][1]
    taker_side = "sell" if side == "buy" else "buy"
    lo = np.searchsorted(tr_ts, t - 3_000_000)
    hi = np.searchsorted(tr_ts, t, side="right")
    cand = [trades[i] for i in range(lo, hi) if trades[i][1] == taker_side and
            ((trades[i][2] <= px + 1e-9) if side == "buy" else (trades[i][2] >= px - 1e-9))]
    if not cand:
        kind = "未对上"
    else:
        kind = "打穿" if any(through_of(c[3], px, side) for c in cand) else "排到"
    cs = bt_cancel.get(oid)
    bt_rows.append(dict(t=t, side=side, px=px, kind=kind, cancel_before=None if cs is None or cs > t else (t - cs) / 1e6))

print("10-14 %02d–%02d 时 UTC,ETH-USDT,挂单成交分类(同一张主动单有没有打到比我方更深的价位)" % (H0, H1))
for name, rows in (("实盘", live_rows), ("回测 R0F", bt_rows)):
    k = collections.Counter(r["kind"] for r in rows)
    at = [r for r in rows if r["kind"] == "排到"]
    th = [r for r in rows if r["kind"] == "打穿"]
    print("  %-7s 成交 %4d 笔:%s" % (name, len(rows), dict(k)))
    print("          排到的里成交前已发出撤单 %d / %d(撤单指令在成交前:%s)" % (sum(r["cancel_before"] is not None for r in at), len(at),
                                                              q([r["cancel_before"] for r in at if r["cancel_before"] is not None])))
    print("          打穿的里成交前已发出撤单 %d / %d" % (sum(r["cancel_before"] is not None for r in th), len(th)))

# ---- ② 实盘"排到"的成交在回测里对应什么 ----
bt_by_level = collections.defaultdict(list)                          # (方向, 价位) → [(挂出, 撤单指令 / 成交 / 无穷)]
bt_fill_t = {oid: t for t, oid, _ in bt_fills}
for oid, (ts, side, px) in bt_orders.items():
    end = min(bt_cancel.get(oid, 1 << 62), bt_fill_t.get(oid, 1 << 62))
    bt_by_level[(side, round(px, 2))].append((ts, end, oid))
cats = collections.Counter()
lead_bt, lead_live = [], []
for r in live_rows:
    if r["kind"] != "排到":
        continue
    lst = bt_by_level.get((r["side"], round(r["px"], 2)), [])
    alive = [x for x in lst if x[0] <= r["t"] < x[1]]
    recent = [x for x in lst if x[0] <= r["t"] and x[1] <= r["t"] and r["t"] - x[1] <= 2 * 10**9]
    if alive:
        cats["a 回测同价单还挂着、没排到"] += 1
    elif recent:
        cats["b 回测同价单在成交前已撤"] += 1
        lead_bt.append((r["t"] - max(x[1] for x in recent)) / 1e6)
        if r["cancel_before"] is not None:
            lead_live.append(r["cancel_before"])
    else:
        cats["c 回测 2 秒内没在这个价位挂过"] += 1
print("\n实盘 %d 笔'排到'的成交,在回测同一时刻同侧同价:%s" % (sum(cats.values()), dict(cats)))
print("  b 类:回测撤单指令比实盘这笔成交早 %s" % q(lead_bt))
print("  b 类里实盘这张单也已发出撤单的:撤单指令比成交早 %s" % q(lead_live))

# ---- ④ 挂单离本侧最优价几跳:挂出时、成交前 10 毫秒(盘口用本机自录 L2 重建的 10 毫秒网格 data/research7/mid24)----
z = np.load(os.path.join(ROOT, "data", "research7", "mid24", "ETHUSDTM_20261014.npz"))
g_t0, g_bp, g_ap, g_ok, tick = int(z["t0"]), z["bp"], z["ap"], z["ok"], float(z["tick"])


def behind(t, side, px):
    """t 时刻(取 t 之前最后一个网格行)我方价位在本侧最优价后面几跳;0 = 和最优价同价,负 = 比最优价更好(进了价差里)。"""
    i = int((t - g_t0) // 10_000_000) - 1
    if i < 0 or i >= len(g_ok) or not g_ok[i]:
        return np.nan
    p = round(px / tick)
    return (int(g_bp[i]) - p) if side == "buy" else (p - int(g_ap[i]))


def dist(vals):
    v = np.asarray([x for x in vals if np.isfinite(x)])
    if not len(v):
        return "n=0"
    c = collections.Counter(np.clip(v, -1, 5).astype(int))
    return "n=%d " % len(v) + " ".join("%s跳 %.0f%%" % ("≥5" if k == 5 else ("<0" if k == -1 else k), 100 * c[k] / len(v)) for k in sorted(c))


print("\n挂单离本侧最优价几跳(0 = 和最优价同价)")
lv_place = [behind(w, s, p) for oid, (w, s, p) in new.items() if T0 <= w < T1]
bt_place = [behind(t, s, p) for oid, (t, s, p) in bt_orders.items() if T0 <= t < T1]
print("  挂出时      实盘 %s" % dist(lv_place))
print("              回测 %s" % dist(bt_place))
for name, rows in (("实盘", live_rows), ("回测", bt_rows)):
    for kind in ("排到", "打穿"):
        print("  成交前 10 毫秒 %s·%s %s" % (name, kind, dist([behind(r["t"], r["side"], r["px"]) for r in rows if r["kind"] == kind])))
pl = [behind(new[r["oid"]][0], r["side"], r["px"]) for r in live_rows if r["kind"] == "排到"]
print("  实盘·排到 的那些单挂出时 %s" % dist(pl))

# ---- ⑤ 回测挂着的单,公共成交里有没有"恰好打到这个价位"(主动单最深打到我方价位)的成交,回测给没给成交 ----
taker_worst = {}
for ts, sd, px, tk in trades:
    w0 = taker_worst.get(tk)
    taker_worst[tk] = px if w0 is None else (max(w0, px) if sd == "buy" else min(w0, px))
hit_alive = hit_filled = hit_through_alive = 0
gap_ms = []
for oid, (ts, side, px) in bt_orders.items():
    if not (T0 <= ts < T1):
        continue
    end = min(bt_cancel.get(oid, 1 << 62), bt_fill_t.get(oid, 1 << 62))
    lo, hi = np.searchsorted(tr_ts, ts), np.searchsorted(tr_ts, end)
    tside = "sell" if side == "buy" else "buy"
    ends_here = [trades[i] for i in range(lo, hi) if trades[i][1] == tside and abs(trades[i][2] - px) < 1e-9
                 and abs(taker_worst.get(trades[i][3], 0) - px) < 1e-9]
    if ends_here:
        hit_alive += 1
        if oid in bt_fill_t:
            hit_filled += 1
        gap_ms.append((ends_here[0][0] - ts) / 1e6)
print("\n回测挂着的单里,期间有主动单恰好打到这个价位(最深就到这)的:%d 张,其中回测给了成交的 %d 张;"
      "这类成交离挂出 %s" % (hit_alive, hit_filled, q(gap_ms)))

# ---- ⑥ 被扫到之前,盘口什么时候开始逼近:往前找最后一个"我方价位还在最优价后面 ≥ 2 跳"的网格时刻 ----
def approach_ms(t, side, px, need=2, back_s=5):
    i = int((t - g_t0) // 10_000_000) - 1
    p = round(px / tick)
    for k in range(i, max(i - back_s * 100, 0), -1):
        if not g_ok[k]:
            continue
        d = (int(g_bp[k]) - p) if side == "buy" else (p - int(g_ap[k]))
        if d >= need:
            return (t - (g_t0 + (k + 1) * 10_000_000)) / 1e6
    return np.nan


for name, rows in (("实盘", live_rows), ("回测", bt_rows)):
    for kind in ("排到", "打穿"):
        a = [approach_ms(r["t"], r["side"], r["px"]) for r in rows if r["kind"] == kind]
        a = np.array([x for x in a if np.isfinite(x)])
        if len(a):
            print("  %s·%s:离最优价 ≥2 跳的最后时刻 → 成交 %s;其中 ≤10 毫秒(一笔扫到)%.0f%%,>50 毫秒 %.0f%%"
                  % (name, kind, q(a), 100 * np.mean(a <= 10), 100 * np.mean(a > 50)))
nc = [r for r in live_rows if r["kind"] == "排到" and r["cancel_before"] is None]
a = np.array([approach_ms(r["t"], r["side"], r["px"]) for r in nc])
a = a[np.isfinite(a)]
print("  实盘·排到·成交前没发撤单的 %d 笔:%s;>50 毫秒的 %.0f%%" % (len(nc), q(a), 100 * np.mean(a > 50)))
print("  挂单数:实盘 %d 张,回测 %d 张(同一时段)" % (sum(T0 <= v[0] < T1 for v in new.values()), sum(T0 <= v[0] < T1 for v in bt_orders.values())))

# ---- ⑦ 挂单暴露:每张单挂了多久、挂在离最优价几跳(按挂出时),两边合计"单·秒";以及每小时挂单数 ----
def expo(orders, end_of):
    lt, buck = [], collections.Counter()
    for oid, (ts, side, px) in orders.items():
        if not (T0 <= ts < T1):
            continue
        e = end_of(oid)
        if e is None or e <= ts:
            continue
        life = (e - ts) / 1e9
        lt.append(life)
        b = behind(ts, side, px)
        if np.isfinite(b):
            buck[int(np.clip(b, -1, 5))] += life
    return np.array(lt), buck


lv_end = lambda oid: min([x for x in (cancelled_ex.get(oid), cancel_sent.get(oid)) if x is not None] or [None]) if (oid in cancel_sent or oid in cancelled_ex) else None
lv_lt, lv_b = expo(new, lv_end)
bt_lt, bt_b = expo(bt_orders, lambda oid: min(bt_cancel.get(oid, 1 << 62), bt_fill_t.get(oid, 1 << 62)) if (oid in bt_cancel or oid in bt_fill_t) else None)
for name, lt, b in (("实盘", lv_lt, lv_b), ("回测", bt_lt, bt_b)):
    tot = sum(b.values())
    print("  %s:单子寿命 中位 %.3f 秒 / 90%% %.2f 秒;挂单总时长 %.0f 单·秒(两侧合计,9 小时 = %.0f 秒);按挂出时离最优价:%s"
          % (name, np.median(lt), np.percentile(lt, 90), tot, 9 * 3600,
             " ".join("%s跳 %.0f%%" % ("≥5" if k == 5 else ("<0" if k == -1 else k), 100 * b[k] / tot) for k in sorted(b))))
