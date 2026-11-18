#!/usr/bin/env python3
"""research5 MF-2: do deep maker fills on KuCoin BTC-USDT revert, outside the two days of MF-1?

MF-1 (maker_families.py, order-by-order data of 10-01 / 10-02): maker fills at 4 bp or more from the mid just before the
fill earned +4.7 bp at 10 s (rebate included); fills at the touch lost. This script measures the same quantity on the
purchased September data (20 days, cleaned L2 + public trades), which needs no order-by-order data:
  every public trade is a maker fill at the trade price; trades of the same taker side within 50 ms form one sweep;
  distance = (trade price - mid before the sweep's first trade), signed so that + is in the maker's favour;
  markout  = mid h seconds after the trade against the trade price, maker's view; net = markout + OUR_FEE rebate.
Mid: 10 ms grid of the other session (data/research3/px/<SYM>-10ms, read-only); grid points with a crossed book are skipped.
This is a description of what makers at those prices earned, NOT a backtest: it says nothing about our queue position
(irrelevant when a sweep takes whole levels, relevant when it stops inside a level) or about our cancels.
Usage: Python314/python.exe scripts/research5/sweep_reversion.py [BTC-USDT]
"""
import glob, gzip, json, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REBATE = OUR_FEE
GAP_NS = 50_000_000
EDGES = [-99, 0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 999]
LABELS = ["<0", "0-0.25", "0.25-0.5", "0.5-1", "1-2", "2-4", "4-8", ">8"]


def hour_rows(sym, slot):
    g = os.path.join(ROOT, "data", "research3", "px", sym + "-10ms", "grid_%s.parquet" % slot)
    ft = glob.glob(os.path.join(ROOT, "data", "oos", "ku_buyc", slot, "kucoin", "swap", sym, "feed_raw", "ticks-*.jsonl.gz"))
    if not os.path.exists(g) or not ft:
        return None
    G = pd.read_parquet(g, columns=["t", "bb", "ba", "crossed"])
    t = G.t.to_numpy(np.int64)
    mid = np.where(G.crossed.to_numpy(), np.nan, (G.bb.to_numpy() + G.ba.to_numpy()) / 2)
    ts, px, sz, sd = [], [], [], []
    with gzip.open(ft[0], "rt") as fh:
        for line in fh:
            m = json.loads(line)
            ts.append(int(m["ts_ns"])); px.append(float(m["price"])); sz.append(float(m["size"])); sd.append(1 if m["side"] == "buy" else -1)
    if not ts:
        return None
    ts, px, sz, sd = np.array(ts, np.int64), np.array(px), np.array(sz), np.array(sd)
    o = np.argsort(ts, kind="stable")
    ts, px, sz, sd = ts[o], px[o], sz[o], sd[o]
    return rows(t, mid, ts, px, sz, sd)


def rows(t, mid, ts, px, sz, sd):
    """-> DataFrame per trade: ts, notional, dist (bp, maker's favour), m1 / m10 / m60 (bp, maker's view), sweep id."""
    new = np.r_[True, (np.diff(ts) > GAP_NS) | (sd[1:] != sd[:-1])]                 # a sweep: same taker side, gaps <= 50 ms
    sweep = np.cumsum(new) - 1
    first_ts = ts[new][sweep]

    def mid_at(x):
        i = np.searchsorted(t, x, side="right") - 1
        out = np.where(i >= 0, mid[np.clip(i, 0, len(mid) - 1)], np.nan)
        out[(x > t[-1])] = np.nan                                                # beyond the hour's grid: unknown
        return out

    m_pre = mid_at(first_ts - 1)                                                  # last grid point before the sweep began
    mk = -sd                                                                      # the maker sold (-1) when the taker bought
    dist = -mk * (px - m_pre) / m_pre * 1e4                                       # maker sold above the mid -> positive
    out = {"ts": ts, "notional": sz * px, "dist": dist, "sweep": sweep}
    for h in (1, 10, 60):
        out["m%d" % h] = mk * (mid_at(ts + h * 10**9) - px) / px * 1e4
    return pd.DataFrame(out)


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTC-USDT"
    slots = sorted(os.path.basename(p)[5:-8] for p in glob.glob(os.path.join(ROOT, "data", "research3", "px", sym + "-10ms", "grid_*.parquet")))
    parts = []
    for s in slots:
        d = hour_rows(sym, s)
        if d is not None:
            d["slot"] = s
            d["day"] = s[:8]
            parts.append(d)
    D = pd.concat(parts, ignore_index=True)
    D = D[np.isfinite(D.dist) & np.isfinite(D.m10)]
    days = sorted(D.day.unique())
    print(f"{sym}: {len(days)} days {days[0]}..{days[-1]}, {D.slot.nunique()} hours, trades {len(D):,}, notional ${D.notional.sum() / 1e6:,.0f}M")
    D["b"] = pd.cut(D.dist, EDGES, labels=LABELS, right=False)
    wavg = lambda g, c: np.average(g[c][np.isfinite(g[c])], weights=g.notional[np.isfinite(g[c])]) if np.isfinite(g[c]).any() else np.nan
    print(f"{'distance bp':12s} {'share':>6s} {'$M/day':>8s} {'trades/day':>10s} {'sweeps/day':>10s} {'m1':>7s} {'m10':>7s} {'m60':>7s} {'net10':>7s} {'net60':>7s} {'days>0':>7s} {'hours>0':>8s} {'median net10':>12s} {'top-5 sweeps':>12s}")
    for lab in LABELS:
        g = D[D.b == lab]
        if len(g) < 50:
            continue
        dd = g.groupby("day").apply(lambda x: wavg(x, "m10") + REBATE)
        hh = g.groupby("slot").apply(lambda x: wavg(x, "m10") + REBATE)
        prof = (g.m10 + REBATE) * g.notional / 1e4
        ps = prof.groupby([g.slot, g.sweep]).sum().sort_values()
        print(f"{lab:12s} {g.notional.sum() / D.notional.sum():6.1%} {g.notional.sum() / 1e6 / len(days):8.2f} {len(g) / len(days):10.0f} {g.groupby(['slot', 'sweep']).ngroups / len(days):10.1f} "
              f"{wavg(g, 'm1'):7.2f} {wavg(g, 'm10'):7.2f} {wavg(g, 'm60'):7.2f} {wavg(g, 'm10') + REBATE:7.2f} {wavg(g, 'm60') + REBATE:7.2f} "
              f"{(dd > 0).mean():7.0%} {(hh > 0).mean():8.0%} {np.median(g.m10 + REBATE):12.2f} {ps.iloc[-5:].sum() / ps.sum():12.0%}")
    deep = D[D.dist >= 4]
    print("\nfills at 4 bp or more from the pre-sweep mid, by day: $M, sweeps, net10 (bp), $ at 10 s")
    for day, g in deep.groupby("day"):
        print(f"   {day}  ${g.notional.sum() / 1e6:6.2f}M  sweeps {g.groupby(['slot', 'sweep']).ngroups:4d}  net10 {wavg(g, 'm10') + REBATE:+6.2f}  ${((g.m10 + REBATE) * g.notional).sum() / 1e4:8.0f}")
    tot = ((deep.m10 + REBATE) * deep.notional).sum() / 1e4
    print(f"   all days: ${deep.notional.sum() / 1e6:.1f}M, ${tot:,.0f} at 10 s for ALL makers at those prices ({tot / len(days):,.0f} per day)")
    out = os.path.join(ROOT, "data", "research5", "maker_families", f"sweeps_{sym}.parquet")
    D[D.dist >= 1].to_parquet(out, index=False)


if __name__ == "__main__":
    main()
