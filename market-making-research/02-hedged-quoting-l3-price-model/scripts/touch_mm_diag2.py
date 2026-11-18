#!/usr/bin/env python3
"""MIDCAP-5:penny/touch 口径的成交拆类——钱到底从哪类吃单来,是不是时间戳/撮合假设的假象。
每张吃单(同毫秒同向)按 首档成交价 相对 成交前显示盘口 分类:
  at     = 成交在显示的最优价;  in1 = 比显示最优价好 1 tick(盘口内 1 档);  in2+ = 好 ≥ 2 tick(显示之外的新单被吃,行情流没来得及显示);
  beyond = 比显示最优价差(显示的那档已经不在了:连续扫单的后半段 / 行情滞后)。
再按 该侧最优价距上次变动的时间(age)和 上次变动方向(改善/恶化)分桶。
每桶:吃单额占比;若我方挂在 显示最优价内 1 tick(penny)或显示最优价(touch)且每张吃单成交 min($1k, 吃单额),不计库存上限的 1 s / 5 s / 30 s 每万 U 毛收益(不含返佣)。"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import touch_mm_replay as R

out = []
for tag in sys.argv[1].split(","):
    for day in sys.argv[2].split(","):
        d = R.find(tag, day)
        if not d:
            continue
        sym = tag[3:].upper() + "USDTM"; mult = float(R.SPECS[sym]["mult"]); tick = float(R.SPECS[sym]["tick"])
        q = pd.read_csv(os.path.join(d, f"quotes-{tag}-{day}.csv.gz"), usecols=["timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"])
        q = q[(q.bid_price > 0) & (q.ask_price > q.bid_price)]
        t = pd.read_csv(os.path.join(d, f"trades-{tag}-{day}.csv.gz"), usecols=["timestamp", "side", "price", "amount"])
        t["usd"] = t.price * t.amount * mult; t["sg"] = np.where(t.side == "buy", 1, -1)
        g = t.groupby(["timestamp", "sg"]).agg(pmin=("price", "min"), pmax=("price", "max"), usd=("usd", "sum")).reset_index()
        qts = q.timestamp.values; ap, bp = q.ask_price.values, q.bid_price.values; mid = (ap + bp) / 2
        ts = g.timestamp.values; i0 = np.searchsorted(qts, ts, side="left") - 1; ok = i0 >= 0; g = g[ok]; ts = ts[ok]; i0 = i0[ok]
        sg = g.sg.values; fpx = np.where(sg > 0, g.pmin.values, g.pmax.values); usd = g.usd.values
        touch = np.where(sg > 0, ap[i0], bp[i0]); spr = np.rint((ap[i0] - bp[i0]) / tick)
        k = np.rint(sg * (fpx - touch) / tick)             # >0: 比显示价差(beyond);<0: 盘口内
        cat = np.select([k == 0, k == -1, k <= -2], ["at", "in1", "in2+"], "beyond")
        da = np.r_[0, np.diff(ap)]; db = np.r_[0, np.diff(bp)]
        la = np.maximum.accumulate(np.where(da != 0, np.arange(len(qts)), 0)); lb = np.maximum.accumulate(np.where(db != 0, np.arange(len(qts)), 0))
        j = np.where(sg > 0, la[i0], lb[i0]); age = (ts - qts[j]) / 1000.0
        imp = np.where(sg > 0, da[j] < 0, db[j] > 0)        # 上次变动是向内改善
        ageb = np.select([age < 10, age < 50, age < 1000], ["<10ms", "10-50ms", "50ms-1s"], ">1s")
        def fut(h):
            return mid[np.clip(np.searchsorted(qts, ts + int(h * 1e6), side="right") - 1, 0, len(qts) - 1)]
        m1, m5, m30 = fut(1), fut(5), fut(30)
        f = np.minimum(R.CLIP, usd)
        for mode in ("touch", "penny"):
            ours = touch if mode == "touch" else np.where(spr >= 3, touch - sg * tick, touch)
            hit = sg * (fpx - ours) >= -tick * 0.5        # 吃单愿意付到我方价
            if mode == "touch":
                hit = k >= 0
            for h, m in (("e1", m1), ("e5", m5), ("e30", m30)):
                g[f"{mode}_{h}"] = np.where(hit, sg * (ours - m) / ours * f, 0.0)   # 我方卖(吃单买 sg=+1)赚 ours − 后续中价
            g[f"{mode}_f"] = np.where(hit, f, 0.0)
        g["cat"] = cat; g["ageb"] = ageb; g["imp"] = imp; g["sym"] = sym; g["day"] = day; g["wide"] = spr >= 3
        out.append(g)
G = pd.concat(out); tot = G.usd.sum()
pd.set_option("display.width", 250)
def table(keys):
    a = G.groupby(keys).agg(n=("usd", "size"), taker_usd=("usd", "sum"), tf=("touch_f", "sum"), t1=("touch_e1", "sum"), t5=("touch_e5", "sum"), t30=("touch_e30", "sum"),
                            pf=("penny_f", "sum"), p1=("penny_e1", "sum"), p5=("penny_e5", "sum"), p30=("penny_e30", "sum"))
    a["share"] = a.taker_usd / tot
    for m, fcol in (("t", "tf"), ("p", "pf")):
        for h in ("1", "5", "30"):
            a[f"{m}{h}_bp"] = a[f"{m}{h}"] / a[fcol].replace(0, np.nan) * 1e4
    a["p5_usd"] = a.p5; a["t5_usd"] = a.t5
    return a[["n", "share", "tf", "t1_bp", "t5_bp", "t30_bp", "t5_usd", "pf", "p1_bp", "p5_bp", "p30_bp", "p5_usd"]]
print("合约:", sorted(G.sym.unique()), "天:", sorted(G.day.unique()), f"吃单总额 ${tot:,.0f}")
print("\n== 按 首档成交价相对显示盘口 的类别(毛收益 bp,不含返佣 我方费率;t=touch 口径,p=penny 口径)=="); print(table(["cat"]).round(2).to_string())
print("\n== 类别 × age =="); print(table(["cat", "ageb"]).round(2).to_string())
print("\n== age × 上次变动方向(True = 向内改善)=="); print(table(["ageb", "imp"]).round(2).to_string())
print("\n== 按合约:penny 口径只算 age ≥ 50 ms 且 cat ∈ {at, in1} 的干净成交 ==")
C = G[(G.ageb.isin(["50ms-1s", ">1s"])) & (G.cat.isin(["at", "in1"]))]
c = C.groupby("sym").agg(pf=("penny_f", "sum"), p5=("penny_e5", "sum"), p30=("penny_e30", "sum"), tf=("touch_f", "sum"), t5=("touch_e5", "sum"), t30=("touch_e30", "sum"))
c["p5_bp"] = c.p5 / c.pf * 1e4; c["p30_bp"] = c.p30 / c.pf * 1e4; c["t5_bp"] = c.t5 / c.tf * 1e4; c["t30_bp"] = c.t30 / c.tf * 1e4
c["days"] = G.groupby("sym").day.nunique(); c["pf_day"] = c.pf / c.days
print(c.round(2).to_string())
