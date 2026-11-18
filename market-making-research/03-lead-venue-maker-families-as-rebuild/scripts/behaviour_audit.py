#!/usr/bin/env python3
"""research5: behaviour audit of backtest runs from the engine's order log (broker_sim_wal.jsonl), strategy-agnostic.

Why: U16 passed its unit comparisons and then sent 28,000 orders an hour in the exam (a re-quote band that collapsed
to zero) - nobody had looked at what the strategy DID. This runs before any P&L number is read.

Per slice, for the quoted contract (the one that is not the hedge contract):
  orders_h, cancels_h       limit orders and cancel requests per hour
  life_p10/p50/p90_s        lifetime of a quote (send -> cancel request or last fill)
  bid_on, ask_on            share of the slice during which at least one bid / ask quote of ours was live
  peak_w30                  largest message weight in any 30 s (KuCoin Futures pool: order 2, cancel 1; OUR_FEE_TIER-1 limit 2000 / 30 s)
  fills, fill_usd           maker fills on the quoted contract
  hedge_taker_share         share of hedge notional done with market orders
  blocked                   orders refused by the risk layer (report.json)
Gates (fixed 2026-10-01, before any stage-2 run):
  B1 peak_w30 <= 1000 (half of the lowest rate-limit tier)      B2 blocked == 0
  B3 orders_h <= 3 x the stage-1 reference on the same slice (only when --ref TAG is given)
Usage: python scripts/research5/behaviour_audit.py TAG [--ref REFTAG]     (reads data/research5/runs/<TAG>.json)
       python scripts/research5/behaviour_audit.py --dir <result dir> [...]
"""
import argparse, bisect, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS = os.path.join(ROOT, "data", "research5", "runs")
W30 = 30_000_000_000
LIMIT_W30 = 1000


def union_ns(intervals):
    """Total length of the union of [a, b) intervals."""
    tot, end = 0, None
    for a, b in sorted(intervals):
        if end is None or a > end:
            tot += b - a
            end = b
        elif b > end:
            tot += b - end
            end = b
    return tot


def peak_weight(msgs, window=W30):
    """Largest summed weight of (ts, weight) messages inside any window of the given length."""
    msgs = sorted(msgs)
    ts = [m[0] for m in msgs]
    cum = [0]
    for m in msgs:
        cum.append(cum[-1] + m[1])
    best = 0
    for i, t in enumerate(ts):
        j = bisect.bisect_left(ts, t + window)
        best = max(best, cum[j] - cum[i])
    return best


def quantile(xs, q):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def audit_wal(lines, hedge_symbol):
    """lines: iterable of WAL dicts. Returns the metrics dict for one slice."""
    orders, cancel_ts, last_fill, fills = {}, {}, {}, []
    t_min = t_max = None
    for m in lines:
        ts = m.get("ts_ns")
        if ts is not None:
            t_min = ts if t_min is None else min(t_min, ts)
            t_max = ts if t_max is None else max(t_max, ts)
        if m["t"] == "order":
            orders[m["id"]] = m
        elif m["t"] == "cancel":
            cancel_ts.setdefault(m["id"], ts)
        elif m["t"] == "fill":
            last_fill[m["id"]] = ts
            fills.append(m)
    if not orders:
        return dict(orders_h=0.0, cancels_h=0.0, fills=0, fill_usd=0.0, peak_w30=0, bid_on=0.0, ask_on=0.0, hedge_taker_share=float("nan"),
                    life_p10_s=float("nan"), life_p50_s=float("nan"), life_p90_s=float("nan"), hours=0.0)
    hours = max((t_max - t_min) / 3.6e12, 1e-9)
    quotes = {i: o for i, o in orders.items() if o["symbol"] != hedge_symbol and o["order_type"] == "limit"}
    life, on = [], {"buy": [], "sell": []}
    for i, o in quotes.items():
        end = min(x for x in (cancel_ts.get(i), last_fill.get(i), t_max) if x is not None) if (i in cancel_ts or i in last_fill) else t_max
        end = max(end, o["ts_ns"])
        life.append((end - o["ts_ns"]) / 1e9)
        on[o["side"]].append((o["ts_ns"], end))
    msgs = [(o["ts_ns"], 2) for o in orders.values()] + [(t, 1) for t in cancel_ts.values()]
    h_usd = {"limit": 0.0, "market": 0.0}
    q_fills, q_usd = 0, 0.0
    for f in fills:
        o = orders.get(f["id"])
        if o is None:
            continue
        usd = float(f["qty"]) * float(f["px"])
        if o["symbol"] == hedge_symbol:
            h_usd[o["order_type"]] += usd
        else:
            q_fills += 1
            q_usd += usd
    span = t_max - t_min
    return dict(hours=hours, orders_h=len(quotes) / hours, cancels_h=sum(1 for i in cancel_ts if i in quotes) / hours,
                life_p10_s=quantile(life, 0.1), life_p50_s=quantile(life, 0.5), life_p90_s=quantile(life, 0.9),
                bid_on=union_ns(on["buy"]) / span if span else 0.0, ask_on=union_ns(on["sell"]) / span if span else 0.0,
                peak_w30=peak_weight(msgs), fills=q_fills, fill_usd=q_usd,
                hedge_taker_share=h_usd["market"] / (h_usd["market"] + h_usd["limit"]) if h_usd["market"] + h_usd["limit"] > 0 else float("nan"))


def audit_dir(d, hedge_symbol):
    p = os.path.join(d, "broker_sim_wal.jsonl")
    with open(p, encoding="utf-8") as fh:
        r = audit_wal((json.loads(x) for x in fh), hedge_symbol)
    rp = os.path.join(d, "report.json")
    r["blocked"] = json.load(open(rp, encoding="utf-8")).get("risk_blocked", 0) if os.path.exists(rp) else None
    return r


def gates(r, ref=None):
    out = {"B1": r["peak_w30"] <= LIMIT_W30, "B2": (r.get("blocked") or 0) == 0}
    if ref is not None:
        out["B3"] = r["orders_h"] <= 3 * max(ref["orders_h"], 1.0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?")
    ap.add_argument("--ref", default="")
    ap.add_argument("--dir", nargs="*", default=[])
    ap.add_argument("--hedge-symbol", default="BTC-USDT")
    ns = ap.parse_args()
    if ns.dir:
        for d in ns.dir:
            print(os.path.basename(d), {k: (round(v, 3) if isinstance(v, float) else v) for k, v in audit_dir(d, ns.hedge_symbol).items()})
        return
    rows = [r for r in json.load(open(os.path.join(RUNS, ns.tag + ".json"), encoding="utf-8")) if "net" in r]
    ref = {r["feed"]: r for r in json.load(open(os.path.join(RUNS, ns.ref + ".json"), encoding="utf-8")) if "net" in r} if ns.ref else {}
    print(f"{'slice':22s} {'ord/h':>7s} {'cxl/h':>7s} {'life50':>7s} {'life90':>7s} {'bid_on':>6s} {'ask_on':>6s} {'w30':>5s} {'fills':>5s} {'fill$':>8s} {'hTaker':>6s} {'blk':>4s}  gates")
    fail = 0
    for r in sorted(rows, key=lambda x: x["feed"]):
        a = audit_dir(r["out_dir"], ns.hedge_symbol)
        g = gates(a, audit_dir(ref[r["feed"]]["out_dir"], ns.hedge_symbol) if r["feed"] in ref else None)
        fail += sum(1 for v in g.values() if not v)
        print(f"{r['feed']:22s} {a['orders_h']:7.0f} {a['cancels_h']:7.0f} {a['life_p50_s']:7.2f} {a['life_p90_s']:7.1f} {a['bid_on']:6.2f} {a['ask_on']:6.2f} "
              f"{a['peak_w30']:5d} {a['fills']:5d} {a['fill_usd']:8.0f} {a['hedge_taker_share']:6.2f} {str(a['blocked']):>4s}  "
              + " ".join(k + ("+" if v else "-FAIL") for k, v in g.items()))
        st = r.get("stats")
        if st:
            print("   strategy counters:", {k: v for k, v in st.items() if v})
    print("BEHAVIOUR", "PASS" if fail == 0 else f"FAIL ({fail} gate failures)")


if __name__ == "__main__":
    main()
