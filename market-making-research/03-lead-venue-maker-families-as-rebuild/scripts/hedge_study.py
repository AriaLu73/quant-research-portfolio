#!/usr/bin/env python3
"""research5 UH-2a preparation: what happens on the hedge leg after a USDC fill (training hours only).

Inputs: a run_hours.py result set (data/research5/runs/<TAG>.json -> each slice's broker_sim_wal.jsonl) and the USDT mid
of the same slice (scripts/research2/run_panel.mid_series, cached).
Questions (written before looking, 2026-10-01):
  Q-a  drift: after one of our USDC fills, how far does the USDT mid move AGAINST the new position within h seconds?
       (+ = against us = what a passive hedge loses while it waits.) Unconditional, and split by the U15 urgency signal
       (reference moved >= 0.3 bp against the fill in the 500 ms before it).
       Taking at once costs 2h + f + r ~ 2.52 bp more than a passive fill at the touch (lit_hedging.md s3): a signal justifies
       a market order only if the expected adverse drift over the passive waiting time exceeds that.
  Q-b  passive hedge orders: fills per second posted (lambda_touch), time to fill, share cancelled.
  Q-c  realised disposal cost per USDC fill notional (hedge price vs USDT mid at the USDC fill + hedge fees), maker vs taker.
Usage: python scripts/research5/hedge_study.py TAG        (Python314; reads only)
"""
import json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research2"))
HORIZONS_S = (0.1, 0.5, 1, 2, 5, 10, 30)
PRE_NS = 500_000_000
SWITCH_BP = 2.52


def mid_at(ts, mid, t):
    """Last mid at or before each time in t."""
    return mid[np.clip(np.searchsorted(ts, t, side="right") - 1, 0, len(mid) - 1)]


def adverse_drift_bp(ts, mid, t_fill, sign, horizons_s=HORIZONS_S):
    """Mid move against a position opened at t_fill (sign +1 long / -1 short), in bp, one column per horizon."""
    m0 = mid_at(ts, mid, t_fill)
    return np.stack([-sign * (mid_at(ts, mid, t_fill + int(h * 1e9)) / m0 - 1) * 1e4 for h in horizons_s], axis=1)


def pre_move_bp(ts, mid, t_fill, sign, pre_ns=PRE_NS):
    """Mid move over the pre_ns before the fill, signed for the new position (+ = in its favour)."""
    return sign * (mid_at(ts, mid, t_fill) / mid_at(ts, mid, t_fill - pre_ns) - 1) * 1e4


def read_wal(path, hedge_symbol):
    """-> (usdc fills [(ts, sign, usd)], hedge orders {id: dict(ts, side, type, end, filled_usd, fill_ts)})."""
    orders, fills_q, hedge = {}, [], {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = json.loads(line)
            if m["t"] == "order":
                orders[m["id"]] = m
                if m["symbol"] == hedge_symbol:
                    hedge[m["id"]] = dict(ts=m["ts_ns"], sign=1 if m["side"] == "buy" else -1, type=m["order_type"], end=None, usd=0.0, fill_ts=None,
                                          px=float(m["price"]) if m["price"] else None, fills=[])
            elif m["t"] == "cancel":
                if m["id"] in hedge and hedge[m["id"]]["end"] is None:
                    hedge[m["id"]]["end"] = m["ts_ns"]
            elif m["t"] == "fill":
                o = orders.get(m["id"])
                if o is None:
                    continue
                usd = float(m["qty"]) * float(m["px"])
                if o["symbol"] == hedge_symbol:
                    h = hedge[m["id"]]
                    h["usd"] += usd
                    h["fill_ts"] = m["ts_ns"]
                    h["fills"].append((m["ts_ns"], float(m["qty"]), float(m["px"])))
                else:
                    fills_q.append((m["ts_ns"], 1 if o["side"] == "buy" else -1, usd, float(m["qty"])))
    return fills_q, hedge


def main():
    import run_panel as RP
    tag = sys.argv[1]
    rows = [r for r in json.load(open(os.path.join(ROOT, "data", "research5", "runs", tag + ".json"), encoding="utf-8")) if "net" in r]
    D, P, W, posted_s, n_fill, n_post, life_fill, taker_usd, maker_usd = [], [], [], 0.0, 0, 0, [], 0.0, 0.0
    cost_num = {"limit": 0.0, "market": 0.0}
    for r in rows:
        anchor = r["sym"].split("-")[0] + "-USDT"
        fq, hedge = read_wal(os.path.join(r["out_dir"], "broker_sim_wal.jsonl"), anchor)
        if not fq:
            continue
        ts, mid = RP.mid_series(r["feed"], anchor)
        t = np.array([f[0] for f in fq], dtype=np.int64)
        s = np.array([f[1] for f in fq], dtype=float)
        D.append(adverse_drift_bp(ts, mid, t, s))
        P.append(pre_move_bp(ts, mid, t, s))
        W.append(np.array([f[2] for f in fq]))
        t_end = int(ts[-1])
        for h in hedge.values():
            if h["type"] == "limit":
                n_post += 1
                end = h["fill_ts"] if h["fill_ts"] is not None else (h["end"] if h["end"] is not None else t_end)
                posted_s += max(end - h["ts"], 0) / 1e9
                if h["usd"] > 0:
                    n_fill += 1
                    life_fill.append((h["fill_ts"] - h["ts"]) / 1e9)
                    maker_usd += h["usd"]
            else:
                taker_usd += h["usd"]
            # disposal cost of this hedge order's fills vs the USDT mid when the hedge was sent (lower bound of the wait cost)
            for ft, q, px in h["fills"]:
                m0 = float(mid_at(ts, mid, np.array([h["ts"]]))[0])
                cost_num[h["type"]] += q * px * (h["sign"] * (px - m0) / m0 * 1e4)
    D, P, W = np.concatenate(D), np.concatenate(P), np.concatenate(W)
    print(tag, "USDC fills", len(W), "notional", round(W.sum()))
    print("Q-a adverse USDT drift after our USDC fills, bp, notional-weighted (+ = against the new position)")
    print("  group               n   " + "  ".join(f"{h:>5}s" for h in HORIZONS_S))
    for name, m in (("all", np.ones(len(W), bool)), ("pre-move <= -0.3 bp", P <= -0.3), ("pre-move in (-0.3, 0.3)", (P > -0.3) & (P < 0.3)), ("pre-move >= +0.3 bp", P >= 0.3)):
        if m.sum():
            print(f"  {name:22s} {int(m.sum()):4d} " + "  ".join(f"{np.average(D[m, j], weights=W[m]):+6.2f}" for j in range(D.shape[1])))
    print(f"  a market order is justified only if the drift over the passive wait exceeds {SWITCH_BP} bp")
    lam = n_fill / posted_s if posted_s else float("nan")
    q = np.quantile(life_fill, [0.5, 0.9, 0.99]) if life_fill else [float("nan")] * 3
    print(f"Q-b passive hedge orders: posted {n_post}, filled {n_fill} ({n_fill / max(n_post, 1):.0%}), posted seconds {posted_s:.0f}, "
          f"lambda_touch {lam:.3f}/s (E[T] {1 / lam if lam else float('nan'):.1f} s), time to fill p50/p90/p99 {q[0]:.1f}/{q[1]:.1f}/{q[2]:.1f} s")
    tot = maker_usd + taker_usd
    print(f"Q-c hedge notional: maker {maker_usd:.0f} ({maker_usd / tot:.0%}), taker {taker_usd:.0f} ({taker_usd / tot:.0%}); "
          f"hedge price vs USDT mid when the order was sent: maker {cost_num['limit'] / max(maker_usd, 1):+.3f} bp, taker {cost_num['market'] / max(taker_usd, 1):+.3f} bp (before fees: maker -0.7, taker +1.8)")


if __name__ == "__main__":
    main()
