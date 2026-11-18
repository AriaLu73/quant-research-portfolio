#!/usr/bin/env python3
"""实盘 vs 回测,同一口径比成交(用户 10-15:"跟回测比为什么亏钱?")。只读本机数据。
回测:十天回测里和实盘同设定的 ETH 组(实验 C + 上限 15 张,EXPL;frozen_v3 那一轮)的全部成交(引擎 fills.parquet)。
实盘:10-15 08:02–12:35 UTC 的全部策略挂单成交(服务器总线记录导出);手动一键平仓单列。
同一口径:中间价都取自 data/research7/mid24 的 10 毫秒网格(同一算法重建的盘口);
  价差 = 成交价相对成交前中间价;Δ1s/10s/60s = 之后中间价变动(按方向,正 = 对我方有利);返佣 = −手续费。
另报:每小时挂单成交笔数、成交额,持仓绝对值的时间平均与最大值(实盘按成交累计;回测按每小时从空仓起)。"""
import glob, gzip, json, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MID = {}


def mid_fn(day):
    if day not in MID:
        z = np.load(os.path.join(ROOT, "data", "research7", "mid24", "ETHUSDTM_%s.npz" % day))
        m = np.where(z["ok"], (z["bp"].astype(float) + z["ap"].astype(float)) / 2.0 * float(z["tick"]), np.nan)
        MID[day] = (int(z["t0"]), m)
    t0, m = MID[day]
    def f(t):
        i = (int(t) - t0) // 10_000_000
        return m[i] if 0 <= i < len(m) else np.nan
    return f


def decompose(rows, label, hours):
    """rows: [(day, ts_ns, side, price, qty, fee)];hours = 覆盖的小时数。"""
    acc = dict(n=0, notional=0.0, spread=0.0, rebate=0.0, mo1=0.0, mo10=0.0, mo60=0.0, skip=0)
    for day, t, side, px, q, fee in rows:
        f = mid_fn(day)
        m0 = f(t - 1)
        if not np.isfinite(m0):
            acc["skip"] += 1; continue
        s = 1.0 if side == "buy" else -1.0
        acc["n"] += 1; acc["notional"] += px * q; acc["spread"] += s * (m0 - px) * q; acc["rebate"] += -fee
        for h, k in ((1, "mo1"), (10, "mo10"), (60, "mo60")):
            m1 = f(t + h * 10**9)
            if np.isfinite(m1):
                acc[k] += s * (m1 - m0) * q
    N = acc["notional"] or 1.0
    bp = lambda x: x / N * 1e4
    print("%-34s 成交 %5d 笔(每小时 %.1f)成交额 $%10.0f(每小时 $%.0f)| 每成交额:价差 %+5.2f  返佣 %我方费率f  Δ1s %+6.2f  Δ10s %+6.2f  Δ60s %+6.2f  →(价差+返佣+Δ我方费率s)%+6.2f bp"
          % (label, acc["n"], acc["n"] / hours, acc["notional"], acc["notional"] / hours, bp(acc["spread"]), bp(acc["rebate"]), bp(acc["mo1"]), bp(acc["mo10"]), bp(acc["mo60"]),
             bp(acc["spread"] + acc["rebate"] + acc["mo60"])))
    return acc


def inventory(fills_sorted, t_start, t_end, reset_hourly):
    """持仓绝对值的时间平均和最大值(币)。fills_sorted: [(ts, signed_qty)]"""
    q, last, area, mx = 0.0, t_start, 0.0, 0.0
    hour = t_start // 3_600_000_000_000
    for t, dq in fills_sorted:
        if reset_hourly and t // 3_600_000_000_000 != hour:
            area += abs(q) * (hour * 3_600_000_000_000 + 3_600_000_000_000 - last)
            hour = t // 3_600_000_000_000; q = 0.0; last = hour * 3_600_000_000_000
        area += abs(q) * (t - last); last = t
        q += dq; mx = max(mx, abs(q))
    area += abs(q) * (t_end - last)
    return area / max(t_end - t_start, 1), mx


# 回测
bt, inv_avg, inv_max, hours_bt = [], [], [], 0
for f in sorted(glob.glob(os.path.join(ROOT, "data", "research7", "as2008_l3", "run_ETH-USDT_2026*_all4_EXPL.json"))):
    d = json.load(open(f, encoding="utf-8"))
    if d["h1"] - d["h0"] != 6:
        continue
    for hh in range(d["h0"], d["h1"]):
        g = glob.glob(os.path.join(ROOT, "data", "backtest_results", "*as_ETHUSDT_%s_%02d_all4_%s_0" % (d["day"], hh, d["run_id"]), "fills.parquet"))
        if not g:
            continue
        hours_bt += 1
        x = pd.read_parquet(g[0])
        x = x[x["symbol"] == "ETH-USDT"]
        fl = []
        for r in x.itertuples():
            px, q, fee = float(r.price), float(r.qty), float(r.fee)
            bt.append((d["day"], int(r.ts_ns), r.side, px, q, fee))
            fl.append((int(r.ts_ns), q if r.side == "buy" else -q))
        t0 = int(pd.Timestamp("%s %02d:00" % (d["day"], hh), tz="UTC").value)
        a, m = inventory(sorted(fl), t0, t0 + 3_600_000_000_000, False)
        inv_avg.append(a); inv_max.append(m)

# 实盘
live, manual, fl_live = [], [], []
with gzip.open(os.path.join(ROOT, "data", "research7", "live_orders_20261015.jsonl.gz"), "rt", encoding="utf-8") as fh:
    newsid = {}
    for l in fh:
        r = json.loads(l); o = r["obj"]
        if r["msg_type"] == "Order":
            newsid[o["order_id"]] = o.get("strategy_id")
        elif r["msg_type"] == "Fill" and o["symbol"] == "ETH-USDT":
            row = ("20261015", int(o["ts_ns"]), o["side"], float(o["price"]), float(o["quantity"]), float(o["fee"]))
            (live if o.get("is_maker") else manual).append(row)
            fl_live.append((int(o["ts_ns"]), float(o["quantity"]) if o["side"] == "buy" else -float(o["quantity"])))
T0 = int(pd.Timestamp("2026-10-15 08:02:25", tz="UTC").value); T1 = int(pd.Timestamp("2026-10-15 12:35:33", tz="UTC").value)
hours_live = (T1 - T0) / 3.6e12

print("ETH-USDT,同一口径(实验 C + 上限 15 张):")
decompose(bt, "回测 十天 %d 小时(挂单成交)" % hours_bt, hours_bt)
decompose(live, "实盘 10-15 %.1f 小时(挂单成交)" % hours_live, hours_live)
decompose(manual, "实盘 手动一键平仓(市价)", hours_live)
la, lm = inventory(sorted(fl_live), T0, T1, False)
print("持仓 |q|(ETH):回测 每小时时间平均的中位 %.2f、平均 %.2f,每小时最大值的中位 %.2f、最大 %.2f;实盘 时间平均 %.2f、最大 %.2f"
      % (np.median(inv_avg), np.mean(inv_avg), np.median(inv_max), np.max(inv_max), la, lm))
