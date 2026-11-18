#!/usr/bin/env python3
"""research3:从订单日志反推 MM-UH 的报价几何随时间的变化(只读)。
一档买价距公允价 db、卖价距公允价 da(bp;公允价 = 离线复现的 A·(1+D̂),未偏斜)。
两侧都在报价带近端时:(db + da)/2 = 下限 + s/2("报价半宽"),(db − da)/2 = 库存偏斜造成的平移(> 0 = 买价更远 = 持多仓)。
用法:python uh_quote_path.py TAG DAY [HH]   → 每小时一行;给 HH 则打印该小时每 2 分钟一行 + 成交明细"""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uh_val as V

tag, day = sys.argv[1], sys.argv[2]; HH = sys.argv[3] if len(sys.argv) > 3 else None
rows = [r for r in json.load(open(os.path.join(V.ROOT, "data", "research5", "runs", tag + ".json"), encoding="utf-8")) if "net" in r]
pd.set_option("display.width", 230); pd.set_option("display.max_rows", 200)
out = []
for row in rows:
    S = V.read_slice(row); d, t0, t1, F = S["d"], S["t0"], S["t1"], S["F"]
    ot, od, _ = V.replicate_basis(d, t0, t1)
    Q = [(o["side"], 2 if o["px"] * o["qty"] > 1.5 * V.CLIP_USD else 1, o["px"], o["ts"], S["cancels"].get(oid, t1), o["qty"]) for oid, o in S["orders"].items() if o["sym"] == "BTC-USDC"]
    Q = pd.DataFrame(Q, columns=["side", "lvl", "px", "on", "off", "qty"])
    if not len(Q):
        continue
    f0 = V.at(d["ats"], d["amid"], Q.on.values) * (1 + V.at(ot, od, Q.on.values) / 1e4)
    Q["dist"] = Q.side.values * (f0 - Q.px.values) / f0 * 1e4            # 买:f0 − px;卖:px − f0
    Q["f0"] = f0
    iu = np.clip(np.searchsorted(d["uts"], Q.on.values, "right") - 1, 0, len(d["uts"]) - 1)
    Q["touch_dist"] = np.where(Q.side > 0, f0 - d["ubb"][iu], d["uba"][iu] - f0) / f0 * 1e4       # 同侧 USDC 最优价离公允价
    pu = F[F.symbol == "BTC-USDC"].sort_values("ts") if len(F) else pd.DataFrame(columns=["ts", "s", "q", "px"])
    cp = np.r_[0.0, np.cumsum(pu.s.values * pu.q.values)] if len(pu) else np.array([0.0])
    Q["pos_clips"] = cp[np.searchsorted(pu.ts.values, Q.on.values, "right")] * f0 / V.CLIP_USD if len(pu) else 0.0
    L1 = Q[Q.lvl == 1]
    b, a = L1[L1.side > 0], L1[L1.side < 0]
    rec = dict(hh=S["hh"], n_posts=len(Q), bid1=b.dist.median(), ask1=a.dist.median(), half_width=(b.dist.median() + a.dist.median()) / 2, shift=(b.dist.median() - a.dist.median()) / 2,
               bid2=Q[(Q.lvl == 2) & (Q.side > 0)].dist.median(), ask2=Q[(Q.lvl == 2) & (Q.side < 0)].dist.median(), bid1_min=b.dist.quantile(.05), ask1_min=a.dist.quantile(.05),
               touch=np.median(Q.touch_dist), pos_abs_max=float(np.abs(Q.pos_clips).max()), fills=row["usdc_fills"], net=row["net_corr"])
    out.append(rec)
    if HH is not None and S["hh"] == HH:
        Q["min"] = ((Q.on - t0) // 120_000_000 * 2).astype(int)
        g = L1.assign(min=((L1.on - t0) // 120_000_000 * 2).astype(int))
        tb = g[g.side > 0].groupby("min").agg(bid1=("dist", "median"), posts_b=("dist", "size"), pos=("pos_clips", "last"), touch_b=("touch_dist", "median"))
        ta = g[g.side < 0].groupby("min").agg(ask1=("dist", "median"), posts_a=("dist", "size"), touch_a=("touch_dist", "median"))
        T = tb.join(ta, how="outer"); T["half_width"] = (T.bid1 + T.ask1) / 2; T["shift"] = (T.bid1 - T.ask1) / 2
        print(f"== {day} {HH} 时,每 2 分钟(一档;距离单位 bp;pos = USDC 腿库存,单位 clip,+ 多 − 空)"); print(T.round(2).to_string())
        if len(pu):
            G = pu.assign(usd=pu.px * pu.q).groupby(["order_id", "ts"]).agg(s=("s", "first"), px=("px", "mean"), usd=("usd", "sum")).reset_index().sort_values("ts")
            fz = V.at(d["ats"], d["amid"], G.ts.values, strict=True) * (1 + V.at(ot, od, G.ts.values, strict=True) / 1e4)
            G["min"] = (G.ts - t0) / 60e6; G["margin_bp"] = G.s * (fz - G.px) / G.px * 1e4
            ah = lambda h: V.at(d["ats"], d["amid"], G.ts.values + h * 1_000_000); uh = lambda h: V.at(d["uts"], (d["ubb"] + d["uba"]) / 2, G.ts.values + h * 1_000_000)
            a0 = V.at(d["ats"], d["amid"], G.ts.values, strict=True)
            for h in (30, 300):
                G[f"r{h}"] = G.s * ((uh(h) - G.px) / G.px - (ah(h) - a0) / a0) * 1e4
            G["pos_after_clips"] = np.cumsum(G.s * G.usd) / V.CLIP_USD
            print("成交(s:+1 我方买 / −1 我方卖;margin = 成交价离公允价;r = 对冲后 markout):"); print(G[["min", "s", "px", "usd", "margin_bp", "r30", "r300", "pos_after_clips"]].round(2).to_string(index=False))
O = pd.DataFrame(out)
print(f"== {tag}:逐小时报价几何(中位;half_width ≈ 下限 + s/2;shift = 偏斜平移)"); print(O.round(2).to_string(index=False))
