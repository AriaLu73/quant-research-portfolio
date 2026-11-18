#!/usr/bin/env python3
"""research3:任一品种、某一小时的逐笔诊断(只读)。从切片重建两条合约的最优价,按成交算:
  成交价相对 USDC 中价的价差(bp)、相对"USDT 中价 ×(1+近 60 秒基差中位)"的边际(bp)、对冲后 markout(30 s / 5 min),以及盘口点差与基差走势。
用法:Python314/python.exe -X utf8 scripts/research3/uh_sym_fill_diag.py <结果集 tag> <HH> <USDC 合约> <USDT 合约>"""
import gzip, json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tag, hh, usym, asym = sys.argv[1:5]
R = [x for x in json.load(open(os.path.join(ROOT, "data", "research5", "runs", tag + ".json"), encoding="utf-8")) if "net" in x and x["feed"].endswith("_" + hh)][0]
day = R["feed"].split("/")[1].split("_")[0]


def tobs(sym):
    p = os.path.join(ROOT, "data", "oos", R["feed"].split("/")[0], f"{day}_{hh}", "kucoin", "swap", sym, "feed_raw", f"depth_deltas-{day}.jsonl.gz")
    B, A, ts, bb, ba = {}, {}, [], [], []
    with gzip.open(p, "rt") as f:
        for l in f:
            o = json.loads(l)
            if o.get("snapshot"):                          # 引擎遇快照帧重置盘口;不重置会留下假的过期档位
                B.clear(); A.clear()
            for side, book in (("bids", B), ("asks", A)):
                for px, q in o.get(side, []):
                    if float(q) == 0:
                        book.pop(float(px), None)
                    else:
                        book[float(px)] = float(q)
            if B and A:
                ts.append(o["ts_ns"]); bb.append(max(B)); ba.append(min(A))
    return np.array(ts), np.array(bb), np.array(ba)


def at(ts, v, t):
    return v[np.clip(np.searchsorted(ts, t, "right") - 1, 0, len(v) - 1)]


ut, ub, ua = tobs(usym); at_, ab, aa = tobs(asym)
um, am = (ub + ua) / 2, (ab + aa) / 2
g = np.arange(ut[0], ut[0] + 3_600_000_000_000, 1_000_000_000)
z = (at(ut, um, g) / at(at_, am, g) - 1) * 1e4
zm = pd.Series(z).rolling(60, min_periods=5).median().values
sp = (at(ut, ua, g) - at(ut, ub, g)) / at(ut, um, g) * 1e4
print(f"{tag} {hh} 时  净 {R['net_corr']:.2f}  USDC 成交 ${R['usdc_usd']:,.0f} / {R['usdc_fills']} 笔")
print("USDC 点差 bp 50/90/99%:", np.round(np.percentile(sp, [50, 90, 99]), 1), " 基差 z bp 每 10 分钟中位:", np.round([np.median(z[i:i + 600]) for i in range(0, 3600, 600)], 1))
print("对冲合约一小时涨跌 bp:", round((am[-1] / am[0] - 1) * 1e4, 1), " 振幅 bp:", round((am.max() / am.min() - 1) * 1e4, 1))
F = pd.read_parquet(os.path.join(R["out_dir"], "fills.parquet"))
F = F.assign(px=F.price.astype(float), q=F.qty.astype(float), s=np.where(F.side == "buy", 1, -1)).sort_values("ts_ns")
U = F[F.symbol == usym]; H = F[F.symbol != usym]
t = U.ts_ns.values; s = U.s.values; p = U.px.values; usd = p * U.q.values
u0 = at(ut, um, t - 1); a0 = at(at_, am, t - 1)
fv = a0 * (1 + at(g, np.nan_to_num(zm), t - 1) / 1e4)
cap = -s * (p - u0) / u0 * 1e4            # 相对成交前 USDC 中价的价差(正 = 赚到价差)
edge = -s * (p - fv) / fv * 1e4           # 相对公允价的边际
w = usd / usd.sum()
print(f"成交 {len(U)} 笔  买 {int((s > 0).sum())} / 卖 {int((s < 0).sum())}  价差捕获 {np.sum(cap * w):+.2f} bp  相对公允价边际 {np.sum(edge * w):+.2f} bp(10/50/90%: {np.round(np.percentile(edge, [10, 50, 90]), 1)})")
for h in (1, 5, 30, 300):
    U1 = at(ut, um, t + h * 1_000_000_000); A1 = at(at_, am, t + h * 1_000_000_000)
    r = s * ((U1 - p) / p - (A1 - a0) / a0) * 1e4
    d = s * (A1 - a0) / a0 * 1e4
    print(f"  {h:>3} s  对冲后 markout {np.sum(r * w):+.2f} bp   对冲合约顺我方方向移动 {np.sum(d * w):+.2f} bp")
if len(H):
    ht = H.ts_ns.values; hs = H.s.values; hp = H.px.values; hm = at(at_, am, ht - 1); hw = hp * H.q.values
    liq = H.liquidity.values if "liquidity" in H else None
    print(f"对冲 {len(H)} 笔 ${hw.sum():,.0f}  相对当时中价 {np.sum(-hs * (hp - hm) / hm * 1e4 * hw) / hw.sum():+.2f} bp", "" if liq is None else dict(pd.Series(liq).value_counts()))
    # 从 USDC 成交到净敞口归零的等待
    net = np.cumsum(F.s.values * F.q.values); ts = F.ts_ns.values; lot = float(F.q.astype(float).min()); waits = []; o = None
    for i in range(len(F)):
        flat = abs(net[i]) < 10 * 0.5 * lot + 1e-12
        if not flat and o is None:
            o = ts[i]
        elif flat and o is not None:
            waits.append((ts[i] - o) / 1e9); o = None
    if waits:
        print(f"净敞口从出现到抹平:{len(waits)} 次,中位 {np.median(waits):.1f} s,90% {np.quantile(waits, .9):.1f} s,最长 {max(waits):.0f} s")
if len(sys.argv) > 5:                      # 明细:按分钟的基差与成交
    t0 = g[0]
    M = pd.DataFrame(dict(m=((t - t0) // 60_000_000_000).astype(int), s=s, usd=usd, cap=cap, edge=edge))
    U5 = at(ut, um, t + 300_000_000_000); A5 = at(at_, am, t + 300_000_000_000)
    M["r300"] = s * ((U5 - p) / p - (A5 - a0) / a0) * 1e4
    M["ub"] = at(ut, ub, t - 1); M["ua"] = at(ut, ua, t - 1); M["px"] = p
    zmin = pd.DataFrame(dict(m=np.arange(len(z)) // 60, z=z, sp=sp)).groupby("m").agg(z_med=("z", "median"), z_min=("z", "min"), z_max=("z", "max"), sp_med=("sp", "median"))
    G = M.groupby("m").apply(lambda d: pd.Series(dict(n=len(d), buy_usd=d.usd[d.s > 0].sum(), sell_usd=d.usd[d.s < 0].sum(), cap=(d.cap * d.usd).sum() / d.usd.sum(), edge=(d.edge * d.usd).sum() / d.usd.sum(), r300=(d.r300 * d.usd).sum() / d.usd.sum())))
    pd.set_option("display.width", 200); pd.set_option("display.max_rows", 200)
    print(zmin.join(G, how="left").round(1).to_string())
if len(sys.argv) > 6:                      # 某一分钟的逐笔明细
    mm = int(sys.argv[6]); k = np.where(M.m.values == mm)[0]
    D = pd.DataFrame(dict(sec=np.round((t[k] - t0) / 1e9 - mm * 60, 3), side=s[k], px=p[k], usd=np.round(usd[k]), u_bid=at(ut, ub, t[k] - 1), u_ask=at(ut, ua, t[k] - 1),
                          a_mid=np.round(a0[k], 3), fv=np.round(fv[k], 3), edge=np.round(edge[k], 1),
                          a_mid_1s_ago=np.round(at(at_, am, t[k] - 1_000_000_000), 3), a_mid_5s_later=np.round(at(at_, am, t[k] + 5_000_000_000), 3), oid=U.order_id.values[k] if "order_id" in U else ""))
    print(D.to_string())
    W = [json.loads(l) for l in open(os.path.join(R["out_dir"], "broker_sim_wal.jsonl"), encoding="utf-8")]
    lo, hi = t0 + mm * 60_000_000_000 - 20_000_000_000, t0 + (mm + 1) * 60_000_000_000
    print("订单日志(该分钟及之前 20 秒)的前 60 行:")
    n = 0
    for o in W:
        if lo <= o.get("ts_ns", 0) < hi and n < 60:
            n += 1; print(round((o["ts_ns"] - t0) / 1e9 - mm * 60, 3), {k2: v for k2, v in o.items() if k2 not in ("ts_ns",)})
