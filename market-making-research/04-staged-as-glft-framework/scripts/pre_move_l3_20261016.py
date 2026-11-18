#!/usr/bin/env python3
"""查时间戳:有没有人在币安行情出来之前就在 KuCoin 上动了(用户 10-16:"你去查时间戳，是不是有人比币安web Rock接口更高知道行情走向。
我觉得就是有人在行情出来之前就挂好单子了")。只读,线下。

数据   KuCoin BTC-USDT 永续逐笔委托(L3):data/research5/usdc_pairs_l3usdt/20261014/<hh>_XBTUSDTM_l3.jsonl.gz(本机录,用交易所时间戳 ts,毫秒精度;
       本机收到时刻那一列本机时钟偏了约 1.5 秒,不用)。
       币安 BTCUSDT 永续逐笔成交:data/research5/binance_hist/BTCUSDT-aggTrades-2026-10-14.zip(币安官方历史数据,成交时刻 = 币安撮合时间,毫秒)。
       两家交易所的时钟之间可能有几毫秒的偏差,本脚本没法单独校准;所以只看"事件前几十到几百毫秒"的变化,几毫秒以内的先后不下结论。
事件 A 币安大扫单:同一毫秒、同一方向的币安吃单把价格从上一笔成交价推动 ≥ 1 bp;之前 500 毫秒内同方向没有别的事件(前面干净)。
       时刻 T = 币安撮合时间。币安 WebSocket 推给我们最早也在 T 之后(我方机房实测行情中位约 1.4 毫秒)。
事件 B KuCoin 大扫单:同一张吃单(takerOrderId)打穿的挂单价跨度 ≥ 0.5 bp;之前 500 毫秒内同方向没有别的事件。时刻 T = KuCoin 撮合时间。
看什么 事件前后 [−500, +200] 毫秒,每 10 毫秒一格,KuCoin 上(和事件同方向对齐,d = +1 往上扫 / −1 往下扫):
         新挂单:顺方向一侧(往上扫时 = 新买单)、被扫一侧(往上扫时 = 新卖单)
         撤单:被扫一侧(往上扫时撤卖单 = 让路)、顺方向一侧
         KuCoin 吃单量:顺方向 − 逆方向(张)
         事件 B 另看币安吃单量:顺方向 − 逆方向(BTC)
       每格的值 ÷ 平时水平(同一批事件 [−3000, −1000) 毫秒的平均)= 倍数;1 = 和平时一样。
       另报事件前 [−50, 0) 毫秒里做"被扫一侧撤单"最多的几个参与者指纹(clientOid 数字换成 #)。
用法   .venv/Scripts/python.exe scripts/research7/pre_move_l3_20261016.py 13 14
"""
import gzip, io, os, re, sys, zipfile
from collections import Counter
import numpy as np
import orjson
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAY = "20261014"
hours = [int(x) for x in sys.argv[1:]] or [13, 14]
TICK = 0.1
BINS = np.arange(-500, 201, 10)                       # 毫秒
BASE = (-3000, -1000)

# ---------------- KuCoin L3 ----------------
o_ts, o_sd, o_cid = [], [], []                        # 新挂单(open):时刻毫秒、方向(+1 买 / −1 卖)、指纹编号
c_ts, c_sd, c_cid = [], [], []                        # 撤单
m_ts, m_sd, m_sz, m_tk, m_px = [], [], [], [], []     # 成交:时刻、吃单方向、张数、吃单 id、挂单价
side_of, cid_of, px_of = {}, {}, {}
fp_id, fp_name = {}, []


def fp(cid):
    f = re.sub(r"\d+", "#", cid or "") or "(无)"
    if f not in fp_id:
        fp_id[f] = len(fp_name)
        fp_name.append(f)
    return fp_id[f]


for hh in hours:
    p = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt", DAY, "%02d_XBTUSDTM_l3.jsonl.gz" % hh)
    n = 0
    with gzip.open(p, "rb") as fh:
        try:
            for ln in fh:
                j = ln.index(b"\t")
                m = orjson.loads(ln[j + 1:])
                s = m.get("subject")
                d = m.get("data") or {}
                if s == "received":
                    cid_of[d["orderId"]] = d.get("clientOid") or ""
                elif s == "open":
                    oid = d["orderId"]
                    sd = 1 if d["side"] == "buy" else -1
                    side_of[oid] = sd
                    px_of[oid] = float(d["price"])
                    f = fp(cid_of.pop(oid, ""))
                    cid_of[oid] = f
                    o_ts.append(int(d["ts"]) // 1_000_000); o_sd.append(sd); o_cid.append(f)
                elif s == "done":
                    oid = d["orderId"]
                    if d.get("reason") == "canceled" and oid in side_of:
                        c_ts.append(int(d["ts"]) // 1_000_000); c_sd.append(side_of[oid]); c_cid.append(cid_of.get(oid, 0) if isinstance(cid_of.get(oid), int) else 0)
                    side_of.pop(oid, None); px_of.pop(oid, None); cid_of.pop(oid, None)
                elif s == "match":
                    mo = d["makerOrderId"]
                    m_ts.append(int(d["ts"]) // 1_000_000); m_sd.append(1 if d["side"] == "buy" else -1); m_sz.append(float(d["size"]))
                    m_tk.append(d["takerOrderId"]); m_px.append(px_of.get(mo, np.nan))
                n += 1
        except (EOFError, OSError):
            pass
    print("  KuCoin %02d 时:%d 条消息,新挂单 %d,撤单 %d,成交 %d" % (hh, n, len(o_ts), len(c_ts), len(m_ts)), flush=True)

O = (np.array(o_ts), np.array(o_sd), np.array(o_cid))
C = (np.array(c_ts), np.array(c_sd), np.array(c_cid))
M = pd.DataFrame(dict(ts=m_ts, sd=m_sd, sz=m_sz, tk=m_tk, px=m_px))
t_lo, t_hi = int(M["ts"].min()) + 5000, int(M["ts"].max()) - 1000

# ---------------- 币安 ----------------
z = zipfile.ZipFile(os.path.join(ROOT, "data", "research5", "binance_hist", "BTCUSDT-aggTrades-2026-10-14.zip"))
B = pd.read_csv(z.open(z.namelist()[0]))
B = B[(B["transact_time"] >= t_lo - 5000) & (B["transact_time"] <= t_hi + 1000)].reset_index(drop=True)
B["sd"] = np.where(B["is_buyer_maker"].astype(str).str.lower() == "true", -1, 1)     # 买方是挂单方 = 卖方吃单
b_ts, b_sd, b_q = B["transact_time"].to_numpy(np.int64), B["sd"].to_numpy(), B["quantity"].to_numpy(float)

# 事件 A:同一毫秒同方向把价格推动 ≥ 1 bp(相对上一毫秒最后一笔成交价)
g = B.groupby(["transact_time", "sd"]).agg(last=("price", "last")).reset_index()
lastpx = B.groupby("transact_time")["price"].last()
prev = lastpx.shift(1)
g["prev"] = g["transact_time"].map(prev)
g["mv"] = g["sd"] * (g["last"] - g["prev"]) / g["prev"] * 1e4
evA = g[(g["mv"] >= 1.0) & (g["transact_time"] > t_lo) & (g["transact_time"] < t_hi)][["transact_time", "sd", "mv"]].to_numpy()

# 事件 B:KuCoin 一张吃单打穿的挂单价跨度 ≥ 0.5 bp
gb = M.dropna(subset=["px"]).groupby("tk").agg(ts=("ts", "min"), sd=("sd", "first"), lo=("px", "min"), hi=("px", "max"))
gb["span"] = (gb["hi"] - gb["lo"]) / gb["lo"] * 1e4
evB = gb[(gb["span"] >= 0.5) & (gb["ts"] > t_lo) & (gb["ts"] < t_hi)][["ts", "sd", "span"]].to_numpy()


def clean(ev):
    ev = ev[np.argsort(ev[:, 0])]
    keep, last = [], {1: -10**15, -1: -10**15}
    for t, sd, mv in ev:
        if t - last[int(sd)] >= 500:
            keep.append((int(t), int(sd), mv))
        last[int(sd)] = t
    return keep


def profile(events, ts, sgn, w=None, same=True):
    """对齐后的计数 / 量:same=True 取和事件同方向的那一类(sgn·d = +1),False 取反方向。返回每格的倍数(相对平时)。"""
    ts = np.asarray(ts); sgn = np.asarray(sgn); w = np.ones(len(ts)) if w is None else np.asarray(w)
    by = {}
    for s in (1, -1):
        k = sgn == s
        o = np.argsort(ts[k], kind="stable")
        by[s] = (ts[k][o], w[k][o])
    tot = np.zeros(len(BINS) - 1); base = 0.0
    for t, d, _ in events:
        tsd, wd = by[d if same else -d]
        a, b = np.searchsorted(tsd, t + BASE[0]), np.searchsorted(tsd, t + BINS[-1])
        tt, ww = tsd[a:b], wd[a:b]
        base += ww[(tt >= t + BASE[0]) & (tt < t + BASE[1])].sum() / (BASE[1] - BASE[0])
        h, _ = np.histogram(tt - t, bins=BINS, weights=ww)
        tot += h / 10.0
    return tot / base if base > 0 else tot * np.nan


def show(name, events, extra_bn=False):
    print("\n%s:%d 个事件(之前 500 毫秒同方向干净)" % (name, len(events)))
    rows = {
        "新挂单·顺方向一侧": profile(events, O[0], O[1], same=True),
        "新挂单·被扫一侧": profile(events, O[0], O[1], same=False),
        "撤单·被扫一侧(让路)": profile(events, C[0], C[1], same=False),
        "撤单·顺方向一侧": profile(events, C[0], C[1], same=True),
        "KuCoin 吃单·顺方向": profile(events, M["ts"].to_numpy(), M["sd"].to_numpy(), M["sz"].to_numpy(), same=True),
        "KuCoin 吃单·逆方向": profile(events, M["ts"].to_numpy(), M["sd"].to_numpy(), M["sz"].to_numpy(), same=False),
    }
    if extra_bn:
        rows["币安吃单·顺方向"] = profile(events, b_ts, b_sd, b_q, same=True)
        rows["币安吃单·逆方向"] = profile(events, b_ts, b_sd, b_q, same=False)
    show_bins = [(-500, -200), (-200, -100), (-100, -50), (-50, -20), (-20, -10), (-10, 0), (0, 10), (10, 20), (20, 50), (50, 200)]
    print("  倍数 = 这段时间的速率 ÷ 平时速率(1 = 和平时一样)")
    print("  %-22s" % "毫秒(相对事件)" + "".join("%11s" % ("[%d,%d)" % ab) for ab in show_bins))
    for k, v in rows.items():
        cells = []
        for a, b in show_bins:
            i0, i1 = np.searchsorted(BINS, a), np.searchsorted(BINS, b)
            cells.append("%11.2f" % v[i0:i1].mean())
        print("  %-22s" % k + "".join(cells))


evA_c = clean(evA)
evB_c = clean(evB)
show("事件 A 币安大扫单(T = 币安撮合时间)", evA_c)
show("事件 B KuCoin 大扫单(T = KuCoin 撮合时间)", evB_c, extra_bn=True)

# 事件前 [−50, 0) 毫秒,被扫一侧撤单最多的指纹(事件 A)
cnt, tot_pre = Counter(), 0
ts, sg, cf = C
order = np.argsort(ts); ts, sg, cf = ts[order], sg[order], cf[order]
for t, d, _ in evA_c:
    a, b = np.searchsorted(ts, t - 50), np.searchsorted(ts, t)
    for k in range(a, b):
        if sg[k] == -d:
            cnt[fp_name[cf[k]] if cf[k] < len(fp_name) else "?"] += 1
            tot_pre += 1
print("\n事件 A 前 50 毫秒内,被扫一侧的撤单:共 %d 笔;按参与者指纹:" % tot_pre)
for f, c in cnt.most_common(10):
    print("  %-40s %6d  %5.1f%%" % (f[:40], c, 100 * c / max(tot_pre, 1)))
