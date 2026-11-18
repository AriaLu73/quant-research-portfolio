#!/usr/bin/env python3
"""单小时:实盘 vs 回测(用户 10-16:"跑实盘有成交记录的某一个小时然后对比")。只读。
用法:Python314/python.exe scripts/research7/hour_compare_20261016.py <小时> <标签:结果目录> [<标签:结果目录> ...]
比:盈亏(成交现金流 + 返佣,小时末按中间价估值;实盘把这一小时之前带进来的持仓也算上,按小时开始时的中间价起算)、
    成交笔数、成交额、持仓绝对值的时间平均 / 最大、有仓时间占比、持仓段(从空仓到空仓)时长的中位 / 90 分位。
注意:回测每次从空仓起跑;实盘这一小时开始时可能带着仓位。"""
import gzip, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D0 = 1791936000 * 10**9
HH = int(sys.argv[1])
T0, T1 = D0 + HH * 3600 * 10**9, D0 + (HH + 1) * 3600 * 10**9
NAT = {"ETH-USDT": "ETHUSDTM", "BTC-USDT": "XBTUSDTM"}
INST = {"MmAsEth-1be9e2b6": "ETH-USDT", "MmAsBtc-bc24ee34": "BTC-USDT"}


def mid_fn(sym):
    z = np.load(os.path.join(ROOT, "data", "research7", "mid24", "%s_20261014.npz" % NAT[sym]))
    m = pd.Series(np.where(z["ok"], (z["bp"].astype(float) + z["ap"]) / 2 * float(z["tick"]), np.nan)).ffill().to_numpy()
    t0 = int(z["t0"])
    return lambda t: m[min(max((int(t) - t0) // 10_000_000, 0), len(m) - 1)]


def stats(fills, sym, q0=0.0):
    """fills: [(ts, 带号数量, 价格, 手续费)],只含这一小时;q0 = 小时开始时的持仓。"""
    m = mid_fn(sym)
    q, cash = q0, -q0 * m(T0)
    t_prev, area, mx, held = T0, 0.0, abs(q0), 0
    eps, ep_start = [], (T0 if abs(q0) > 1e-12 else None)
    vol = 0.0
    for t, dq, px, fee in fills:
        area += abs(q) * (t - t_prev); held += (t - t_prev) if abs(q) > 1e-12 else 0; t_prev = t
        was = abs(q) > 1e-12
        q += dq; cash -= dq * px + fee; vol += abs(dq) * px
        mx = max(mx, abs(q))
        if not was and abs(q) > 1e-12:
            ep_start = t
        elif was and abs(q) <= 1e-12 and ep_start is not None:
            eps.append((t - ep_start) / 1e9); ep_start = None
    area += abs(q) * (T1 - t_prev); held += (T1 - t_prev) if abs(q) > 1e-12 else 0
    if ep_start is not None:
        eps.append((T1 - ep_start) / 1e9)                           # 到小时末还没平:按截断算(偏短)
    e = np.array(eps) if eps else np.array([np.nan])
    return dict(盈亏=cash + q * m(T1), 成交=len(fills), 成交额=vol, 平均持仓=area / (T1 - T0), 最大持仓=mx, 小时末持仓=q,
                有仓时间=held / (T1 - T0), 持仓段数=len(eps), 持仓段中位秒=np.nanmedian(e), 持仓段90分位秒=np.nanpercentile(e, 90))


# 实盘
oid, live = {}, {s: [] for s in NAT}
with gzip.open(os.path.join(ROOT, "data", "research7", "live_orders_20261014.jsonl.gz"), "rt", encoding="utf-8") as fh:
    for l in fh:
        if '"Order"' not in l[:200] and '"Fill"' not in l[:200]:
            continue
        r = json.loads(l); o = r["obj"]
        if r["msg_type"] == "Order" and o.get("strategy_id") in INST:
            oid[o["order_id"]] = INST[o["strategy_id"]]
        elif r["msg_type"] == "Fill" and o["symbol"] in NAT and (o["order_id"] in oid or not o.get("is_maker")):
            live[o["symbol"]].append((int(o["ts_ns"]), (1 if o["side"] == "buy" else -1) * float(o["quantity"]), float(o["price"]), float(o["fee"])))
rows = []
for sym in NAT:
    f = sorted(live[sym])
    q0 = sum(x[1] for x in f if x[0] < T0)
    rows.append(dict(合约=sym, 方案="实盘(旧版 v3/v4)", **stats([x for x in f if T0 <= x[0] < T1], sym, q0)))
    for arg in sys.argv[2:]:
        tag, d = arg.split(":", 1)
        if ("_%s_" % sym.replace("-", "")) not in os.path.basename(d):
            continue
        x = pd.read_parquet(os.path.join(d, "fills.parquet"))
        x = x[x["symbol"] == sym].sort_values("ts_ns")
        bf = [(int(r.ts_ns), (1 if r.side == "buy" else -1) * float(r.qty), float(r.price), float(r.fee)) for r in x.itertuples() if T0 <= int(r.ts_ns) < T1]
        rows.append(dict(合约=sym, 方案=tag, **stats(bf, sym)))
df = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print("10-14 %02d–%02d 时 UTC" % (HH, HH + 1))
print(df.round(2).to_string(index=False))
