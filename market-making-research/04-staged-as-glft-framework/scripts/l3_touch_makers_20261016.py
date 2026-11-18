#!/usr/bin/env python3
"""KuCoin BTC-USDT 永续逐笔委托(L3):贴盘口挂单的人赚不赚钱(用户 10-16:"不是有L3数据吗?你看看那些贴盘口挂的人赚不赚钱")。只读。

数据  data/research5/usdc_pairs_l3usdt/<日>/<hh>_XBTUSDTM_l3.jsonl.gz(本机自录 /contractMarket/level3v2:received / open / match / done);
      中间价和买一卖一用 data/research7/mid24/XBTUSDTM_<日>.npz(自录 L2 重建的 10 毫秒网格)。
做法  每张挂单在 open 那一刻,按它离本侧最优价几跳分类(用 open 之前最后一个网格行):
        进价差 = 买单价 > 买一(卖单镜像),成为新的最优价;贴盘口 = 和本侧最优价同价;后 1–2 跳;后 3–10 跳;后 11–50 跳;更深。
      每笔成交(match;挂单方 = makerOrderId 那张)算 markout:挂单方向 × (τ 之后的中间价 − 成交价)/成交价 × 1e4(bp),
        τ = 10、50 毫秒,1、10、60 秒;按成交量加权。不含手续费 / 返佣(各人费率不同;我方费率档 返佣是 我方费率)。
      参与者:received 消息里的 clientOid 把数字换成 # 当"指纹"(同一套程序下的单格式一样);报贴盘口成交量最大的几个指纹各自的 markout。
      只统计这两个小时里 open 的单子(之前就挂着的单子不知道挂的时候在哪,不算);成交打印价不可靠(常为 0 或不是挂单价),成交价一律用挂单自己的限价。
用法  .venv/Scripts/python.exe scripts/research7/l3_touch_makers_20261016.py 20261014 14 17
"""
import gzip, os, re, sys
import numpy as np
import orjson
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
day, hours = sys.argv[1], [int(x) for x in sys.argv[2:]]
z = np.load(os.path.join(ROOT, "data", "research7", "mid24", "XBTUSDTM_%s.npz" % day))
g_t0, g_bp, g_ap, g_ok, TICK = int(z["t0"]), z["bp"].astype(np.int64), z["ap"].astype(np.int64), z["ok"], float(z["tick"])
mid = pd.Series(np.where(g_ok, (g_bp + g_ap) / 2 * TICK, np.nan)).ffill().to_numpy()
TAUS = (10, 50, 1000, 10000, 60000)
CATS = ["进价差", "贴盘口", "后1-2跳", "后3-10跳", "后11-50跳", "更深"]


def row_before(t):
    return int(np.ceil((t - g_t0) / 10_000_000)) - 1


orders, fills, oid_cid = {}, [], {}
for hh in hours:
    p = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt", day, "%02d_XBTUSDTM_l3.jsonl.gz" % hh)
    n = 0
    with gzip.open(p, "rb") as fh:
        try:
            for ln in fh:
                j = ln.index(b"\t")
                m = orjson.loads(ln[j + 1:])
                d = m.get("data") or {}
                s = m.get("subject")
                if s == "received":
                    oid_cid[d["orderId"]] = d.get("clientOid") or ""
                elif s == "open":
                    t = int(d["ts"])
                    r = row_before(t)
                    if 0 <= r < len(g_ok) and g_ok[r]:
                        pt = round(float(d["price"]) / TICK)
                        b = (int(g_bp[r]) - pt) if d["side"] == "buy" else (pt - int(g_ap[r]))   # 本侧最优价后面几跳;负 = 进了价差
                        cat = CATS[0] if b < 0 else CATS[1] if b == 0 else CATS[2] if b <= 2 else CATS[3] if b <= 10 else CATS[4] if b <= 50 else CATS[5]
                        orders[d["orderId"]] = (d["side"], cat, b, t, float(d["price"]))
                elif s == "match":
                    px = float(d.get("price") or 0)                  # 打印价常为 0 或不是挂单价(本机记忆 kucoin-l3-recording):成交价一律用挂单限价
                    fills.append((int(d["ts"]), d["makerOrderId"], px, float(d["size"]), d["side"]))
                n += 1
        except (EOFError, OSError):
            pass
    print("  %02d 时:%d 条消息,累计 open %d,成交 %d" % (hh, n, len(orders), len(fills)), flush=True)

rows = []
for t, moid, px, sz, tside in fills:
    o = orders.get(moid)
    if o is None:
        continue
    sgn = 1.0 if o[0] == "buy" else -1.0
    lim = o[4]                                                       # 10-16 改:用挂单自己的限价(强平接管等记录的打印价不是挂单成交价)
    bad = abs(px - lim) > TICK / 2
    px = lim
    r = dict(cat=o[1], behind=o[2], qty=sz * 0.001, notional=sz * 0.001 * px, wait_s=(t - o[3]) / 1e9, print_mismatch=bad,
             fp=re.sub(r"\d+", "#", oid_cid.get(moid, "")) or "(无)")
    for tau in TAUS:
        k = int((t + tau * 1_000_000 - g_t0) // 10_000_000)
        mm = mid[k] if 0 <= k < len(mid) else np.nan
        r["mo_%d" % tau] = sgn * (mm - px) / px * 1e4
    rows.append(r)
df = pd.DataFrame(rows)
print("成交打印价和挂单限价对不上的:%d 笔(成交额 $%.0f),已改用挂单限价,统计里全部保留" % (df['print_mismatch'].sum(), df.loc[df['print_mismatch'], 'notional'].sum()))
df_all = df
out = os.path.join(ROOT, "data", "research7", "l3_touch_makers_%s_%s.csv" % (day, "_".join(map(str, hours))))
df_all.to_csv(out, index=False, encoding="utf-8-sig")


def wavg(g, c):
    x = g[c].to_numpy(); w = g["notional"].to_numpy(); m = np.isfinite(x)
    return np.average(x[m], weights=w[m]) if m.any() else np.nan


tot = df["notional"].sum()
print("\nBTC-USDT %s %s 时 UTC:这两小时里挂出、且有成交的挂单方成交 %d 笔,成交额 $%.0f" % (day, hours, len(df), tot))
print("按挂出时离本侧最优价分类;markout(bp,按成交额加权,正 = 挂单方赚;不含费率,我方费率档 返佣另 我方费率)")
print("  %-10s %7s %7s %7s %7s %7s %7s %7s %9s" % ("挂出位置", "成交额占比", "10ms", "50ms", "1s", "10s", "60s", "中位等待s", "1s+0.7"))
for c in CATS:
    g = df[df["cat"] == c]
    if not len(g):
        continue
    print("  %-10s %6.1f%% %+7.2f %+7.2f %+7.2f %+7.2f %+7.2f %7.1f %+9.2f" % (c, 100 * g["notional"].sum() / tot, wavg(g, "mo_10"), wavg(g, "mo_50"),
          wavg(g, "mo_1000"), wavg(g, "mo_10000"), wavg(g, "mo_60000"), g["wait_s"].median(), wavg(g, "mo_1000") + 0.7))
touch = df[df["cat"].isin(["进价差", "贴盘口"])]
print("\n贴盘口 / 进价差成交量最大的 10 个参与者指纹(clientOid 数字换成 #)")
print("  %-34s %8s %7s %7s %7s %7s %10s" % ("指纹", "成交额$", "占贴盘口", "50ms", "1s", "10s", "他全部成交里贴盘口占比"))
for fp, g in sorted(touch.groupby("fp"), key=lambda kv: -kv[1]["notional"].sum())[:10]:
    allv = df[df["fp"] == fp]["notional"].sum()
    print("  %-34s %8.0f %6.1f%% %+7.2f %+7.2f %+7.2f %9.0f%%" % (fp[:34], g["notional"].sum(), 100 * g["notional"].sum() / touch["notional"].sum(),
          wavg(g, "mo_50"), wavg(g, "mo_1000"), wavg(g, "mo_10000"), 100 * g["notional"].sum() / allv))
print("写入", out)
