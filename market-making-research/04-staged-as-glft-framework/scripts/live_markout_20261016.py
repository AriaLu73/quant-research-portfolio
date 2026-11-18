#!/usr/bin/env python3
"""实盘挂单成交之后的 markout(用户 10-16:"查一下成交之后的markout")。只读。

数据  实盘总线导出 data/research7/live_orders_<日>.jsonl.gz(策略实例 MmAs* 的挂单成交);
      中间价 data/research7/mid24/<合约>_<日>.npz(自录盘口重建的 10 毫秒网格);
      成交分类用自录公共成交 data/research5/usdc_pairs/<日>/<hh>_<合约>_trades.jsonl.gz 的 takerOrderId:
        打穿 = 同一张主动单有成交价比我方更深;排到 = 主动单最深就到我方价位。
markout(bp)= 方向 × (τ 之后的中间价 − 成交价) / 成交价 × 1e4;τ = −10 毫秒(成交前)、0、5、10、50、100 毫秒、1、5、10、60 秒。
      τ = −10 毫秒那一列 = 成交前一刻我方价位离中间价多远(挂单本来能赚到的半价差);之后变成负数 = 价格往不利方向走。
      返佣 我方费率 另算(最后一列 = 60 秒 markout + 0.7)。
用法  Python314/python.exe scripts/research7/live_markout_20261016.py
"""
import collections, gzip, json, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NAT = {"ETH-USDT": "ETHUSDTM", "BTC-USDT": "XBTUSDTM"}
TAUS_MS = (-10, 0, 5, 10, 50, 100, 1000, 5000, 10000, 60000)


def mid_fn(nat, day):
    p = os.path.join(ROOT, "data", "research7", "mid24", "%s_%s.npz" % (nat, day))
    if not os.path.exists(p):
        return None
    z = np.load(p)
    m = pd.Series(np.where(z["ok"], (z["bp"].astype(float) + z["ap"]) / 2 * float(z["tick"]), np.nan)).ffill().to_numpy()
    t0 = int(z["t0"])
    return lambda t: m[int((t - t0) // 10_000_000)] if 0 <= (t - t0) // 10_000_000 < len(m) else np.nan


def taker_worst(day, nat):
    d = os.path.join(ROOT, "data", "research5", "usdc_pairs", day)
    pub, worst = {}, {}
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not fn.endswith("_%s_trades.jsonl.gz" % nat):
            continue
        with gzip.open(os.path.join(d, fn), "rt", encoding="utf-8") as fh:
            try:
                for ln in fh:
                    x = json.loads(ln.partition("\t")[2]).get("data") or {}
                    if "tradeId" in x:
                        px, tk = float(x["price"]), x.get("takerOrderId")
                        pub[str(x["tradeId"])] = tk
                        w = worst.get(tk)
                        worst[tk] = px if w is None else (max(w, px) if x["side"] == "buy" else min(w, px))
            except (EOFError, OSError, ValueError):
                pass
    return pub, worst


rows = []
for day in ("20261014", "20261015"):
    oid = {}
    fills = []
    with gzip.open(os.path.join(ROOT, "data", "research7", "live_orders_%s.jsonl.gz" % day), "rt", encoding="utf-8") as fh:
        for l in fh:
            if '"Order"' not in l[:200] and '"Fill"' not in l[:200]:
                continue
            r = json.loads(l); o = r["obj"]
            if r["msg_type"] == "Order" and str(o.get("strategy_id", "")).startswith("MmAs") and o.get("order_type") == "limit":
                oid[o["order_id"]] = o["symbol"]
            elif r["msg_type"] == "Fill" and o["order_id"] in oid and o.get("is_maker"):
                fills.append(o)
    for sym, nat in NAT.items():
        mf = mid_fn(nat, day)
        if mf is None:
            continue
        pub, worst = taker_worst(day, nat)
        for o in fills:
            if o["symbol"] != sym:
                continue
            t, P = int(o["ts_ns"]), float(o["price"])
            s = 1.0 if o["side"] == "buy" else -1.0
            tk = pub.get(str(o.get("trade_id")))
            if tk is None:
                kind = "未对上"
            else:
                w = worst.get(tk)
                kind = "打穿" if (w is not None and ((s > 0 and w < P - 1e-9) or (s < 0 and w > P + 1e-9))) else "排到"
            row = dict(day=day, sym=sym, kind=kind, hour=(t // 3_600_000_000_000) % 24, notional=P * float(o["quantity"]))
            for tau in TAUS_MS:
                m = mf(t + tau * 1_000_000)
                row["mo_%d" % tau] = s * (m - P) / P * 1e4 if np.isfinite(m) else np.nan
            rows.append(row)

df = pd.DataFrame(rows)
df.to_csv(os.path.join(ROOT, "data", "research7", "live_markout_20261016.csv"), index=False, encoding="utf-8-sig")
cols = ["mo_%d" % t for t in TAUS_MS]
hdr = " ".join("%7s" % (("%dms" % t) if abs(t) < 1000 else ("%ds" % (t // 1000))) for t in TAUS_MS)
print("实盘挂单成交的 markout(bp,按成交额加权;正 = 对我们有利;不含返佣)")
for keys, g in [((d, s, "全部"), g) for (d, s), g in df.groupby(["day", "sym"])] + [((d, s, k), g) for (d, s, k), g in df.groupby(["day", "sym", "kind"])]:
    w = g["notional"].to_numpy()
    vals = []
    for c in cols:
        x = g[c].to_numpy(); m = np.isfinite(x)
        vals.append(np.average(x[m], weights=w[m]) if m.any() else np.nan)
    print("%s %s %-4s %4d 笔 | %s | 60s+返佣 %我方费率f" % (keys[0][4:], keys[1][:3], keys[2], len(g), " ".join("%+7.2f" % v for v in vals), vals[-1] + 0.7))
print("列:", hdr)
