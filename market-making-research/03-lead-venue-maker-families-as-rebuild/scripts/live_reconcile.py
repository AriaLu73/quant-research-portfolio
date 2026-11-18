"""Read-only: every live fill of 2026-10-02 (bus journal since 18:28 UTC) against our own public recordings."""
import sys, json, glob, os, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, r"scripts\research5"); sys.path.insert(0, r"scripts\research4")
import active_mm_study as A, stale_take_replay as S, l3_parse as LP, kucoin_trades as KT
ev = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
U = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%H:%M:%S.%f")[:-3]
orders = {e["msg"]["order_id"]: e for e in ev if e["type"] == "Order"}
fills = [e for e in ev if e["type"] == "Fill"]
reports = {}
for e in ev:
    if e["type"] == "OrderReport":
        reports.setdefault(e["msg"]["order_id"], []).append(e)
print("orders sent by strategies:", len(orders), "| fills:", len(fills), "| by strategy:", pd.Series([o["msg"]["strategy_id"] for o in orders.values()]).value_counts().to_dict())
# ---------------- market data (own recordings, hours 18-21 UTC)
day, root = "20261002", A.PAIRS_DIR
def bbo(sym):
    files = [f for f in A.hour_files(day, sym, "l2", root) if os.path.basename(f)[:2] in ("18", "19", "20", "21")]
    snaps = []
    for f in A.hour_files(day, sym, "snap", root):
        if os.path.basename(f)[:2] in ("18", "19", "20", "21"):
            for m in A.json_lines(f):
                d = m.get("data") if isinstance(m, dict) else None
                if d and d.get("bids") and d.get("asks"):
                    snaps.append((int(d["sequence"]), d["bids"], d["asks"]))
    return S.bbo_from_events(sorted(snaps, key=lambda x: x[0]), A.l2_events(files), LP.Book())
bc, bt = bbo("XBTUSDCM"), bbo("XBTUSDTM")
print("recorded book rows: USDC", len(bc), U(bc.t.iloc[0]), "..", U(bc.t.iloc[-1]), "| USDT", len(bt), U(bt.t.iloc[0]), "..", U(bt.t.iloc[-1]))
def at(b, t):
    i = np.clip(np.searchsorted(b.t.to_numpy(np.int64), t, side="right") - 1, 0, len(b) - 1)
    r = b.iloc[i]
    return float(r.bb), float(r.ba)
tc, tt = bc.t.to_numpy(np.int64), bt.t.to_numpy(np.int64)
mid_c = ((bc.bb + bc.ba) / 2).to_numpy(float); mid_t = ((bt.bb + bt.ba) / 2).to_numpy(float)
def mid(b_t, m, t):
    return float(m[np.clip(np.searchsorted(b_t, t, side="right") - 1, 0, len(m) - 1)])
def basis600(t):                                             # median of ln(USDC mid / USDT mid) over the previous 600 s, 1 s samples
    g = np.arange(t - 600_000, t, 1000)
    return float(np.median(np.log(mid_c[np.clip(np.searchsorted(tc, g, side="right") - 1, 0, len(mid_c) - 1)] / mid_t[np.clip(np.searchsorted(tt, g, side="right") - 1, 0, len(mid_t) - 1)])))
# public USDC prints around our fills
pr = pd.DataFrame([r for f in A.hour_files(day, "XBTUSDCM", "trades", root) if os.path.basename(f)[:2] in ("18", "19", "20", "21") for r in map(KT.parse_line, A.gz_lines(f)) if r],
                  columns=["sym", "ts", "sgn", "px", "size", "tid", "age_ms", "liq"])
pr["t"] = pr.ts // 1_000_000
rows = []
last_data = min(tc[-1], tt[-1])
for e in sorted(fills, key=lambda e: e["msg"]["ts_ms"]):
    m = e["msg"]; t = int(m["ts_ms"]); px, q = float(m["price"]), float(m["quantity"])
    o = orders.get(m["order_id"])
    sid = o["msg"]["strategy_id"][-8:] if o else "(not ours)"
    kind = "quote" if m["symbol"] == "BTC-USDC" else "hedge"
    s = 1.0 if m["side"] == "buy" else -1.0
    r = dict(time=U(t), strat=sid, sym=m["symbol"][-4:], kind=kind if o else "external", side=m["side"], px=px, usd=round(px * q, 1), maker=m["is_maker"], fee=round(float(m["fee"]), 4),
             otype=(o["msg"]["order_type"] + "/" + str(o["msg"]["time_in_force"])) if o else "")
    if o:
        r["rest_ms"] = t - o["msg"]["ts_ns"] // 1_000_000                       # how long the order had been resting when it filled
    if t < last_data - 60_000 and t > max(tc[0], tt[0]) + 600_000:
        mt0 = mid(tt, mid_t, t - 1)
        r["usdt_mid"] = round(mt0, 1)
        if m["symbol"] == "BTC-USDC":
            b = basis600(t)
            fair = mt0 * np.exp(b)
            bb, ba = at(bc, t - 1)
            r.update(basis_bp=round(b * 1e4, 1), fair=round(fair, 1), edge_bp=round(s * (fair - px) / px * 1e4, 2), usdc_bb=bb, usdc_ba=ba,
                     spread_bp=round((ba - bb) / fair * 1e4, 2))
            for h in (1_000, 5_000, 30_000):
                r[f"usdt_move_{h // 1000}s"] = round(s * (mid(tt, mid_t, t + h) / mt0 - 1) * 1e4, 2)       # + = the reference went our way after the fill
            near = pr[(pr.t >= t - 2) & (pr.t <= t + 2)]
            r["taker_usd_same_ms"] = round(float((near.px * near["size"] * 0.0001).sum()), 0)
            r["taker_self"] = bool(len(near) and (near.age_ms <= 20).all())
        else:
            r["vs_usdt_mid_bp"] = round(-s * (px - mt0) / mt0 * 1e4, 2)       # + = better than the mid at the moment of the hedge fill
    rows.append(r)
d = pd.DataFrame(rows)
pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40)
print(d.to_string(index=False))
d.to_csv(os.path.join(os.path.dirname(sys.argv[1]), "fills_reconciled.csv"), index=False)
# ---------------- quoting activity per strategy
od = pd.DataFrame([dict(t=o["msg"]["ts_ns"] // 1_000_000, strat=o["msg"]["strategy_id"][-8:], sym=o["msg"]["symbol"], side=o["msg"]["side"], qty=float(o["msg"]["quantity"]),
                        px=float(o["msg"]["price"]) if o["msg"]["price"] else np.nan, tif=o["msg"]["time_in_force"], typ=o["msg"]["order_type"]) for o in orders.values()])
for sid, g in od.groupby("strat"):
    hrs = (g.t.max() - g.t.min()) / 3.6e6
    print(f"\nstrategy {sid}: {U(g.t.min())} .. {U(g.t.max())} ({hrs:.2f} h) | orders {len(g)} ({len(g) / max(hrs, 1e-9):,.0f}/h) | USDC quotes {int((g.sym == 'BTC-USDC').sum())}, USDT hedges {int((g.sym == 'BTC-USDT').sum())} (market {int(((g.sym == 'BTC-USDT') & (g.typ == 'market')).sum())})")
    q = g[(g.sym == "BTC-USDC") & (g.t > max(tc[0], tt[0]) + 600_000) & (g.t < last_data)]
    if len(q):
        fair = np.array([mid(tt, mid_t, t) * np.exp(basis600(t)) for t in q.t.to_numpy()[:: max(1, len(q) // 400)]])
        qq = q.iloc[:: max(1, len(q) // 400)]
        dist = np.where(qq.side == "buy", (fair - qq.px) / fair, (qq.px - fair) / fair) * 1e4
        near = qq.qty.to_numpy() < 0.01
        bbv = np.array([at(bc, t - 1) for t in qq.t.to_numpy()])
        behind = np.where(qq.side == "buy", (bbv[:, 0] - qq.px) / fair, (qq.px - bbv[:, 1]) / fair) * 1e4      # + = behind the public best
        print(f"   sampled {len(qq)} USDC quotes: distance from fair (bp) near p10/50/90 {np.percentile(dist[near], [10, 50, 90]).round(1).tolist() if near.any() else None},"
              f" far {np.percentile(dist[~near], [10, 50, 90]).round(1).tolist() if (~near).any() else None} | near quotes behind the public best by (bp) p10/50/90 {np.percentile(behind[near], [10, 50, 90]).round(1).tolist() if near.any() else None}"
              f" | share of near quotes at or inside the best {np.mean(behind[near] <= 0.01):.0%}" if near.any() else "")
