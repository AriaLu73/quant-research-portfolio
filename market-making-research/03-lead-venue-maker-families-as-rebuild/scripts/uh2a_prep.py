#!/usr/bin/env python3
"""research5 UH-2a: empirical-Bayes prior for the fill rate of our passive hedge order at the USDT touch (training hours only).

rate_d = (passive hedge orders that received a fill) / (seconds such orders were resting), per training day d (this is the
exponential-waiting-time MLE with censoring: cancelled orders count their resting time and no event).
Gamma(alpha0, beta0) prior by moments across days: mean m = pooled rate, variance v = between-day variance of rate_d;
alpha0 = m^2 / v, beta0 = m / v (seconds)  -> posterior rate = (alpha0 + n) / (beta0 + exposure), as microstructure.ExpDepthIntensity.rate.
Also: hedge episodes per day (USDC fills per day), used for the "at most one timeout per day" tail probability.
Usage: python scripts/research5/uh2a_prep.py UH1_train32   -> data/research5/uh2a_prep.json     (Python314)
"""
import json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hedge_study as HS


def gamma_prior(n_by_day, expo_by_day):
    """Method-of-moments Gamma prior (alpha0, beta0 seconds) for a Poisson rate from per-day (events, exposure seconds)."""
    n, t = np.asarray(n_by_day, float), np.asarray(expo_by_day, float)
    m = n.sum() / t.sum()
    v = np.var(n / t, ddof=1)
    return float(m * m / v), float(m / v)


def main():
    tag = sys.argv[1]
    rows = [r for r in json.load(open(os.path.join(ROOT, "data", "research5", "runs", tag + ".json"), encoding="utf-8")) if "net" in r]
    day_n, day_t, day_fills, hours = {}, {}, {}, {}
    for r in rows:
        day = r["feed"].split("/")[1][:8]
        fq, hedge = HS.read_wal(os.path.join(r["out_dir"], "broker_sim_wal.jsonl"), r["sym"].split("-")[0] + "-USDT")
        hours[day] = hours.get(day, 0) + 1
        day_fills[day] = day_fills.get(day, 0) + len(fq)
        for h in hedge.values():
            if h["type"] != "limit":
                continue
            end = h["fill_ts"] if h["fill_ts"] is not None else h["end"]
            if end is None:
                continue
            day_t[day] = day_t.get(day, 0.0) + max(end - h["ts"], 0) / 1e9
            day_n[day] = day_n.get(day, 0) + (1 if h["usd"] > 0 else 0)
    days = sorted(d for d in day_t if day_t[d] > 0)
    for d in days:
        print(d, "passive fills", day_n[d], "resting s", round(day_t[d], 1), "rate", round(day_n[d] / day_t[d], 3), "USDC fills", day_fills[d])
    a0, b0 = gamma_prior([day_n[d] for d in days], [day_t[d] for d in days])
    per_day = sum(day_fills.values()) / sum(hours.values()) * 24
    out = dict(source=tag, hedge_lam_alpha0=a0, hedge_lam_beta0=b0, prior_rate=a0 / b0, usdc_fills_per_day=per_day, hedge_tail_p=1.0 / per_day)
    json.dump(out, open(os.path.join(ROOT, "data", "research5", "uh2a_prep.json"), "w"), indent=1)
    print(out)


if __name__ == "__main__":
    main()
