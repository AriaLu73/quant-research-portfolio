#!/usr/bin/env python3
"""research5: compare two run_hours.py result sets slice by slice (same manifest), or print one.

net = engine P&L + 0.5 bp x USDC fill notional (the engine pays OUR_FEE on the USDC leg, our tier pays OUR_FEE).
Paired difference NEW - BASE per slice: sum, mean, standard error of the sum (sqrt(n) x sd of the hourly differences).
Stage-2 adoption line (docs/research5/experiments.md, UH-1): sum(NEW) >= sum(BASE) - 1 standard error, and the
behaviour audit passes (scripts/research5/behaviour_audit.py).
Usage: python scripts/research5/compare_runs.py BASE [NEW]
"""
import json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS = os.path.join(ROOT, "data", "research5", "runs")


def load(tag):
    return {r["feed"]: r for r in json.load(open(os.path.join(RUNS, tag + ".json"), encoding="utf-8")) if "net" in r}


def paired(base, new):
    """(sum_base, sum_new, sum_diff, se_of_sum_diff, n) over the slices present in both."""
    keys = sorted(set(base) & set(new))
    d = [new[k]["net_corr"] - base[k]["net_corr"] for k in keys]
    n = len(d)
    m = sum(d) / n if n else 0.0
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    return sum(base[k]["net_corr"] for k in keys), sum(new[k]["net_corr"] for k in keys), sum(d), sd * math.sqrt(n), n


def adopt(sum_base, sum_new, se):
    return sum_new >= sum_base - se


def summary(rows):
    net = sum(r["net_corr"] for r in rows.values())
    usdc = sum(r["usdc_usd"] for r in rows.values())
    vol = sum(r["vol"] for r in rows.values())
    pos = sum(1 for r in rows.values() if r["net_corr"] > 0)
    neg = sum(1 for r in rows.values() if r["net_corr"] < 0)
    return dict(hours=len(rows), net=round(net, 2), usdc_fill_usd=round(usdc), volume_usd=round(vol), bp_per_usd=round(net / vol * 1e4, 3) if vol else 0.0,
                hours_pos=pos, hours_neg=neg, orders=sum(r.get("orders") or 0 for r in rows.values()), blocked=sum(r.get("blocked") or 0 for r in rows.values()))


def main():
    base = load(sys.argv[1])
    print(sys.argv[1], summary(base))
    if len(sys.argv) < 3:
        for k in sorted(base):
            r = base[k]
            print(f"  {k:22s} net {r['net_corr']:8.2f}  usdc$ {r['usdc_usd']:9.0f}  fills {r['usdc_fills']:4d}  orders {r['orders']:6d}")
        return
    new = load(sys.argv[2])
    print(sys.argv[2], summary(new))
    sb, sn, sd, se, n = paired(base, new)
    for k in sorted(set(base) & set(new)):
        print(f"  {k:22s} base {base[k]['net_corr']:8.2f}  new {new[k]['net_corr']:8.2f}  diff {new[k]['net_corr'] - base[k]['net_corr']:+8.2f}  usdc$ {base[k]['usdc_usd']:8.0f} -> {new[k]['usdc_usd']:8.0f}")
    print(f"paired over {n} slices: base {sb:.2f}  new {sn:.2f}  diff {sd:+.2f}  se {se:.2f}  ->  {'ADOPT' if adopt(sb, sn, se) else 'REJECT'} (P&L line only; behaviour audit separately)")


if __name__ == "__main__":
    main()
