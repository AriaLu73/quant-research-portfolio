#!/usr/bin/env python3
"""research5: how long and how large is the unhedged exposure (USDC leg + USDT leg, base coin) in a result set.

From the engine order log of every slice: net(t) = cumulative signed fill quantity over both contracts. An episode is a
maximal interval with |net| >= min_qty (default 0.001, the hedge lot). Reports episode count, duration quantiles, the
largest |net| in USD, and exposure still open at the end of a slice (it would be carried, here it is cut by the slice end).
Usage: python scripts/research5/exposure_study.py TAG [TAG ...]        (reads only)
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def episodes(fills, t_end, min_qty=0.001):
    """fills: [(ts_ns, signed_qty)] in time order -> [(start_ns, end_ns, max_abs_qty, closed)]."""
    out, net, start, peak = [], 0.0, None, 0.0
    for ts, q in fills:
        net += q
        if abs(net) >= min_qty - 1e-12:
            if start is None:
                start, peak = ts, 0.0
            peak = max(peak, abs(net))
        elif start is not None:
            out.append((start, ts, peak, True))
            start = None
    if start is not None:
        out.append((start, t_end, peak, False))
    return out


def qty_seconds(fills, t_end):
    """Integral of |net| over time (base coin x seconds) for fills [(ts_ns, signed_qty)] in time order."""
    tot, net, last = 0.0, 0.0, None
    for ts, q in fills:
        if last is not None:
            tot += abs(net) * (ts - last) / 1e9
        net += q
        last = ts
    if last is not None:
        tot += abs(net) * (t_end - last) / 1e9
    return tot


def quantile(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float("nan")


def main():
    for tag in sys.argv[1:]:
        rows = [r for r in json.load(open(os.path.join(ROOT, "data", "research5", "runs", tag + ".json"), encoding="utf-8")) if "net" in r]
        dur, peak_usd, open_end, usd_s, hours = [], [], 0, 0.0, 0
        for r in rows:
            orders, fills, t_end, px = {}, [], 0, 0.0
            with open(os.path.join(r["out_dir"], "broker_sim_wal.jsonl"), encoding="utf-8") as fh:
                for line in fh:
                    m = json.loads(line)
                    t_end = max(t_end, m.get("ts_ns") or 0)
                    if m["t"] == "order":
                        orders[m["id"]] = 1.0 if m["side"] == "buy" else -1.0
                    elif m["t"] == "fill" and m["id"] in orders:
                        fills.append((m["ts_ns"], orders[m["id"]] * float(m["qty"])))
                        px = float(m["px"])
            hours += 1
            usd_s += qty_seconds(sorted(fills), t_end) * px
            for a, b, pk, closed in episodes(sorted(fills), t_end):
                dur.append((b - a) / 1e9)
                peak_usd.append(pk * px)
                open_end += 0 if closed else 1
        print(f"{tag}: episodes {len(dur)}  duration s p50 {quantile(dur, .5):.1f} / p90 {quantile(dur, .9):.1f} / p99 {quantile(dur, .99):.1f} / max {max(dur) if dur else 0:.1f}"
              f"  | peak exposure $ p50 {quantile(peak_usd, .5):.0f} / p99 {quantile(peak_usd, .99):.0f} / max {max(peak_usd) if peak_usd else 0:.0f}"
              f"  | exposure-seconds {sum(dur):.0f}  | open at slice end {open_end}"
              f"  | average unhedged exposure ${usd_s / (hours * 3600):.1f} (time-weighted over {hours} h)")


if __name__ == "__main__":
    main()
