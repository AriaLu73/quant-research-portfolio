#!/usr/bin/env python3
"""research5 SP-1: quote a KuCoin spot pair around the same coin's KuCoin USDT perpetual, hedge every fill on the perpetual.

Strategy file: docs/research5/strategy_spot_perp.md; pre-registration: docs/research5/experiments.md, card SP-1.
  fair value   F(t) = perp mid (1 ms old) x exp(slow basis); slow basis = median of ln(spot mid / perp mid) over the last 600 s
  our quotes   ask = F (1 + delta) rounded up to the spot tick, bid = F (1 - delta) rounded down; never crossing the spot book
  fill         a real (not self-traded) spot taker order whose prints reach our price; queue front; at most $1,000 per order;
               the quote is the one implied by F two ms before the taker arrived (our order latency)
  hedge        taker order on the perpetual two ms after the fill, at the perpetual's opposite best price
  net (bp)     locked basis edge + spot maker rebate - perp taker fee          (spot fee PROVISIONAL: OUR_FEE_TIER maker OUR_FEE)
Inputs: data/research5/spot_perp/<day>/<HH>_<sym>_{l2,trades,snap,bbo}.jsonl.gz (spot_perp_recorder.py).
Usage: Python314/python.exe scripts/research5/spot_perp_study.py 20261003 [--check] [--syms SUI-USDT,...]
"""
import argparse, glob, json, os, sys
from dataclasses import replace

import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research4"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import active_mm_study as A   # noqa: E402  gz_lines, protect_ci
import stale_take_replay as S  # noqa: E402  bbo_from_events, Market, Cfg
import l3_parse as LP          # noqa: E402  Book (research4, read-only)

D5 = os.path.join(ROOT, "data", "research5")
DIR, CACHE = os.path.join(D5, "spot_perp"), os.path.join(D5, "sp_cache")
DELTAS_BP = (1.0, 2.0, 3.0, 5.0, 8.0, 12.0)
HORIZONS_MS = (1_000, 5_000, 60_000, 300_000)
SPOT_MAKER_BP = -1.2            # PROVISIONAL: the spot market-maker plan OUR_FEE_TIER (user's screenshot of 2026-09-15); negative = rebate
PERP_TAKER_BP = 1.8
CLIP_USD = 1000.0
LEAD_LAG_MS, ORDER_LAT_MS = 1, 2
PAIR_AGE_MS = 20
CFG = S.Cfg(ref_lag_ms=LEAD_LAG_MS, order_lat_ms=ORDER_LAT_MS, binance_max_age_ms=60_000, basis_window_s=600, basis_min_n=60)


# ------------------------------------------------------------------ parsing
def files(day, sym, kind):
    return sorted(glob.glob(os.path.join(DIR, day, f"*_{sym}_{kind}.jsonl.gz")))


def spot_l2_events(line):
    """One recorder line of a spot level2 message -> list of (sequence, time ms, price, side +1 bid / -1 ask, size)."""
    i = line.find("\t")
    if i < 0 or '"changes"' not in line:
        return []
    try:
        d = json.loads(line[i + 1:])["data"]
    except (ValueError, KeyError):
        return []
    t = int(d["time"])
    out = []
    for side, key in ((1, "bids"), (-1, "asks")):
        for p, s, q in d["changes"].get(key, ()):
            if float(p) > 0:                                        # price 0 only carries a sequence number
                out.append((int(q), t, float(p), side, float(s)))
    return sorted(out)


def maker_created_ms(order_id):
    """Creation time (ms since epoch) encoded in a 24-hex order id (first 8 hex digits = seconds); None for other ids."""
    if len(order_id) == 24:
        try:
            return int(order_id[:8], 16) * 1000
        except ValueError:
            return None
    return None


def is_self_trade(taker_id, maker_id, trade_ms):
    """A print whose maker order was created no more than PAIR_AGE_MS before the taker order (same rule as on futures).
    Numeric (snowflake) ids: the difference of the ids' time bits. Hex maker ids only resolve to a second: the maker order
    must have been created in the second of the trade or later."""
    if taker_id.isdigit() and maker_id.isdigit():
        return 0 <= (int(taker_id) - int(maker_id)) >> 22 <= PAIR_AGE_MS
    m = maker_created_ms(maker_id)
    return m is not None and trade_ms - m < 1000


def parse_trade(line):
    """One recorder line of a spot match -> (time ns, taker direction, price, size, taker id, self-trade flag); None otherwise."""
    i = line.find("\t")
    if i < 0 or '"trade.l3match"' not in line:
        return None
    try:
        d = json.loads(line[i + 1:])["data"]
        t = int(d["time"])
        return t, 1 if d["side"] == "buy" else -1, float(d["price"]), float(d["size"]), d["takerOrderId"], is_self_trade(d["takerOrderId"], d["makerOrderId"], t // 1_000_000)
    except (ValueError, KeyError):
        return None


def parse_bbo(line):
    """One recorder line of a perp tickerV2 message -> (time ms, bid, ask); None otherwise."""
    p = line.find('"bestBidPrice":"')
    q = line.find('"bestAskPrice":"')
    k = line.find('"ts":')
    if p < 0 or q < 0 or k < 0:
        return None
    try:
        return int(line[k + 5: line.index("}", k)]) // 1_000_000, float(line[p + 16: line.index('"', p + 16)]), float(line[q + 16: line.index('"', q + 16)])
    except ValueError:
        return None


def build_spot_bbo(day, sym):
    """Spot best bid / ask change series (t ms, bb, bq, ba, aq), re-synchronised at every top-100 snapshot. Cached."""
    fl = files(day, sym, "l2")
    cache = os.path.join(CACHE, f"bbo_{sym}_{day}_{len(fl)}h.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    snaps = []
    for f in files(day, sym, "snap"):
        for m in A.json_lines(f):
            d = m.get("data") if isinstance(m, dict) else None
            if d and d.get("bids") and d.get("asks"):
                snaps.append((int(d["sequence"]), d["bids"], d["asks"]))
    incs = (e for f in fl for line in A.gz_lines(f) for e in spot_l2_events(line))
    out = S.bbo_from_events(sorted(snaps, key=lambda x: x[0]), incs, LP.Book())
    os.makedirs(CACHE, exist_ok=True)
    out.to_parquet(cache)
    return out


def load_perp(day, sym):
    rows = [r for f in files(day, sym, "bbo") for r in map(parse_bbo, A.gz_lines(f)) if r]
    d = pd.DataFrame(rows, columns=["t", "bid", "ask"])
    d = d[(d.bid > 0) & (d.ask > d.bid)].sort_values("t", kind="stable").drop_duplicates("t", keep="last")
    return d.t.to_numpy(np.int64), ((d.bid + d.ask) / 2).to_numpy(float), d.bid.to_numpy(float), d.ask.to_numpy(float)


def load_prints(day, sym):
    """Spot prints of one pair: order key (taker order), t ms, sgn, px, usd, self."""
    rows = [r for f in files(day, sym, "trades") for r in map(parse_trade, A.gz_lines(f)) if r]
    d = pd.DataFrame(rows, columns=["ts", "sgn", "px", "size", "tid", "paired"])
    if not len(d):
        return d
    d["usd"] = d.px * d["size"]
    d = d.sort_values("ts", kind="stable")
    d["t"] = d.groupby("tid").ts.transform("min") // 1_000_000        # an order's prints share the time of its first print
    return d


# ------------------------------------------------------------------ rules
def our_quote(sgn, fair, delta_bp, bb, ba, tick):
    """Price of our resting quote that a taker of direction sgn would hit (+1: our ask), delta_bp outside fair value, on the
    tick grid, never crossing the spot book (post-only: an ask stays above the best bid, a bid below the best ask)."""
    sgn = np.asarray(sgn, dtype=float)
    ask = np.maximum(np.ceil(fair * (1 + delta_bp * 1e-4) / tick - 1e-9) * tick, bb + tick)
    bid = np.minimum(np.floor(fair * (1 - delta_bp * 1e-4) / tick + 1e-9) * tick, ba - tick)
    return np.where(sgn > 0, ask, bid)


def fill_usd(order_idx, n_orders, sgn_print, px_print, usd_print, quote_of_order, tick, clip_usd=CLIP_USD):
    """Per taker order: $ of its prints that traded at or through our quote (those would have hit us first), capped at clip_usd."""
    q = quote_of_order[order_idx]
    eps = tick * 1e-6
    with np.errstate(invalid="ignore"):
        reached = np.where(sgn_print > 0, px_print >= q - eps, px_print <= q + eps) & np.isfinite(q)
    return np.minimum(clip_usd, np.bincount(order_idx, weights=np.where(reached, usd_print, 0.0), minlength=n_orders))


def locked_edge_bp(sgn, quote_px, hedge_px, basis):
    """Basis edge locked by a spot fill at quote_px hedged on the perpetual at hedge_px (bp of the fill).
    sgn +1: a taker bought from us (we sold spot, bought the perp); the perp price is converted with exp(basis)."""
    return sgn * (quote_px - hedge_px * np.exp(basis)) / quote_px * 1e4


def spot_markout_bp(sgn, quote_px, spot_mid_later):
    """Pnl of the unhedged spot fill marked at a later spot mid (bp of the fill, before the rebate). sgn +1: we sold."""
    return sgn * (quote_px - spot_mid_later) / quote_px * 1e4


def pair_markout_bp(sgn, quote_px, hedge_px, spot_mid_later, perp_mid_later):
    """Mark-to-mid pnl of the hedged pair at a later time (bp of the fill): spot leg + perp leg, before fees."""
    return sgn * ((quote_px - spot_mid_later) / quote_px + (perp_mid_later - hedge_px) / hedge_px) * 1e4


# ------------------------------------------------------------------ one pair
def pair_rows(sym, perp_sym, day, tick):
    """One row per (real spot taker order, delta) that would fill our quote."""
    bbo = build_spot_bbo(day, sym)
    pt, pm, pb, pa = load_perp(day, perp_sym)
    pr = load_prints(day, sym)
    if len(bbo) < 200 or len(pt) < 200 or not len(pr):
        return None, None
    mk = S.Market(bbo, pt, pm, CFG, tick, 1.0)
    orders = pr.groupby("tid", sort=False).agg(t=("t", "first"), sgn=("sgn", "first"), usd=("usd", "sum"), paired=("paired", "all")).reset_index()
    orders = orders.sort_values("t", kind="stable").reset_index(drop=True)
    hours = (mk.grid[-1] - mk.grid[0]) / 3.6e6
    sp_mid = (mk.bb + mk.ba) / 2
    w = np.diff(mk.bt).astype(float)
    facts = dict(sym=sym, hours=hours, real_usd_day=orders.usd[~orders.paired].sum() / hours * 24, self_share=orders.usd[orders.paired].sum() / max(orders.usd.sum(), 1e-9),
                 orders_day=(~orders.paired).sum() / hours * 24, spot_half_bp=float(np.sum(((mk.ba - mk.bb) / sp_mid / 2 * 1e4)[:-1] * w) / w.sum()),
                 perp_half_bp=float(np.median((pa - pb) / pm / 2 * 1e4)), tick_bp=tick / float(np.median(sp_mid)) * 1e4)
    real = orders[~orders.paired & (orders.t - ORDER_LAT_MS > mk.grid[0]) & (orders.t + HORIZONS_MS[-1] <= min(mk.bt[-1], pt[-1]))].reset_index(drop=True)
    if not len(real):
        return facts, None
    idx = pd.Series(np.arange(len(real)), index=real.tid)
    p = pr[pr.tid.isin(idx.index)]
    oi = idx.loc[p.tid].to_numpy()
    t = real.t.to_numpy(np.int64)
    sgn = real.sgn.to_numpy(float)
    td = t - ORDER_LAT_MS
    fair = mk.fair(td)
    k = np.clip(td // 1000 - mk.sec[0], 0, len(mk.basis) - 1)
    basis = mk.basis[k]
    bb, _, ba, _ = mk.book_at(td)
    th = t + ORDER_LAT_MS                                              # the hedge reaches the perpetual
    j = np.clip(np.searchsorted(pt, th, side="right") - 1, 0, len(pt) - 1)
    hedge = np.where(sgn > 0, pa[j], pb[j])
    out = []
    anchors = {"perp": fair, "spot": np.where(np.isfinite(fair), (bb + ba) / 2, np.nan)}      # SP-2: the spot pair's own mid as the centre
    for anchor, centre in anchors.items():
        for delta in DELTAS_BP:
            q = our_quote(sgn, centre, delta, bb, ba, tick)
            usd = fill_usd(oi, len(real), p.sgn.to_numpy(float), p.px.to_numpy(float), p.usd.to_numpy(float), q, tick)
            m = (usd > 0) & np.isfinite(centre)
            if not m.any():
                continue
            d = dict(sym=sym, anchor=anchor, delta=delta, t=t[m], sgn=sgn[m], usd=usd[m], quote=q[m], edge=locked_edge_bp(sgn[m], q[m], hedge[m], basis[m]),
                     inside=np.where(sgn[m] > 0, q[m] < ba[m] - tick * 1e-6, q[m] > bb[m] + tick * 1e-6))
            for h in HORIZONS_MS:
                b1, _, a1, _ = mk.book_at(t[m] + h)
                jh = np.clip(np.searchsorted(pt, t[m] + h, side="right") - 1, 0, len(pt) - 1)
                d[f"pair_{h}"] = pair_markout_bp(sgn[m], q[m], hedge[m], (b1 + a1) / 2, pm[jh])
                d[f"spot_{h}"] = spot_markout_bp(sgn[m], q[m], (b1 + a1) / 2)
            out.append(pd.DataFrame(d))
    return facts, (pd.concat(out, ignore_index=True) if out else None)


# ------------------------------------------------------------------ report
def report(day, facts, rows, fee_bp=SPOT_MAKER_BP):
    pd.set_option("display.width", 260)
    f = pd.DataFrame(facts).sort_values("real_usd_day", ascending=False)
    print(f"\nSP-1 {day}: {len(f)} pairs; real spot taker flow ${f.real_usd_day.sum():,.0f}/day (self-traded share of reported volume, median {f.self_share.median():.0%})")
    print(f.round(2).to_string(index=False))
    if rows is None or not len(rows):
        print("no fills")
        return
    hours = f.hours.max()
    cost = -fee_bp - PERP_TAKER_BP                                    # + rebate - perp taker fee
    w = lambda x, c: float((x[c] * x.usd).sum() / x.usd.sum())
    print(f"\nper $ of spot fill, bp; net = locked basis edge + {-fee_bp:.1f} (spot rebate, PROVISIONAL) - {PERP_TAKER_BP:.1f} (perp taker); pair = mark-to-mid of the hedged pair later, same fees")
    print("\nSP-2 (no immediate hedge): our quote delta outside the centre, marked at the later SPOT mid, + rebate; per $ of fill, bp")
    print("centre | delta | fills | $/day | inside spread | net 1 s | 5 s [95 %] | 60 s | 300 s [95 %] | $/day at 300 s | pairs>0 at 300 s | break-even maker fee at 5 s / 300 s")
    for (anchor, delta), x in rows.groupby(["anchor", "delta"]):
        x = x.assign(n5=x.spot_5000 - fee_bp, n300=x.spot_300000 - fee_bp)
        lo5, hi5 = A.protect_ci(x, "n5")
        lo3, hi3 = A.protect_ci(x, "n300")
        per = x.assign(p=x.n300 * x.usd).groupby("sym").agg(n=("p", "size"), p=("p", "sum"))
        big = per[per.n >= 20]
        print(f"{anchor:5s} | {delta:5g} | {len(x):6d} | {x.usd.sum() / hours * 24:11,.0f} | {w(x, 'inside'):5.0%} | {w(x, 'spot_1000') - fee_bp:+6.2f} | {w(x, 'n5'):+6.2f} [{lo5:+.2f}, {hi5:+.2f}]"
              f" | {w(x, 'spot_60000') - fee_bp:+6.2f} | {w(x, 'n300'):+6.2f} [{lo3:+.2f}, {hi3:+.2f}] | {(x.n300 * x.usd).sum() / 1e4 / hours * 24:+9,.0f} | {int((big.p > 0).sum())}/{len(big)}"
              f" | {w(x, 'spot_5000'):+.2f} / {w(x, 'spot_300000'):+.2f}")
    rows = rows[rows.anchor == "perp"]
    print("\nSP-1 (perp centre, taker hedge on the perp)")
    print("delta | fills | pairs | $/day | buy share | inside spread | edge | net [95 %] | pair net 1 s | 5 s | 60 s | 300 s [95 %] | $/day net | pairs>0 | break-even spot maker fee bp")
    for delta, x in rows.groupby("delta"):
        x = x.assign(net=x.edge + cost, pn300=x.pair_300000 + cost)
        lo, hi = A.protect_ci(x, "net")
        lo3, hi3 = A.protect_ci(x, "pn300")
        per = x.assign(p=x.net * x.usd).groupby("sym").agg(n=("p", "size"), p=("p", "sum"))
        big = per[per.n >= 20]
        print(f"{delta:5g} | {len(x):6d} | {x.sym.nunique():3d} | {x.usd.sum() / hours * 24:11,.0f} | {x.usd[x.sgn < 0].sum() / x.usd.sum():5.0%} | {w(x, 'inside'):5.0%} | {w(x, 'edge'):+6.2f} | {w(x, 'net'):+6.2f} [{lo:+.2f}, {hi:+.2f}]"
              f" | {w(x, 'pair_1000') + cost:+6.2f} | {w(x, 'pair_5000') + cost:+6.2f} | {w(x, 'pair_60000') + cost:+6.2f} | {w(x, 'pn300'):+6.2f} [{lo3:+.2f}, {hi3:+.2f}]"
              f" | {(x.net * x.usd).sum() / 1e4 / hours * 24:+9,.0f} | {int((big.p > 0).sum())}/{len(big)} | {w(x, 'edge') - PERP_TAKER_BP:+.2f}")
    return rows


def by_pair(rows, delta, anchor="spot", fee_bp=SPOT_MAKER_BP):
    """Per pair: the unhedged spot quote (SP-2) at one delta, and the hedged edge of SP-1 for the same fills."""
    x = rows[(rows.delta == delta) & (rows.anchor == anchor)]
    cost = -fee_bp - PERP_TAKER_BP
    wm = lambda b, c: (b[c] * b.usd).sum() / b.usd.sum()
    g = x.groupby("sym").apply(lambda b: pd.Series({"fills": len(b), "usd": b.usd.sum(), "spot5": wm(b, "spot_5000") - fee_bp, "spot60": wm(b, "spot_60000") - fee_bp,
                                                    "spot300": wm(b, "spot_300000") - fee_bp, "hedged_net": wm(b, "edge") + cost,
                                                    "usd_300": ((b.spot_300000 - fee_bp) * b.usd).sum() / 1e4}), include_groups=False)
    return g.sort_values("usd", ascending=False).round(2)


def check(day, uni, ticks):
    """Data checks before any pnl: book sanity and the timing of the spot book against the spot prints."""
    print(f"data checks {day}")
    for u in uni:
        sym = u["spot"]
        bbo = build_spot_bbo(day, sym)
        pr = load_prints(day, sym)
        pt, pm, pb, pa = load_perp(day, u["perp"])
        if len(bbo) < 50 or not len(pr):
            print(f"  {sym:14s} book rows {len(bbo)}, prints {len(pr)}: too little data")
            continue
        tb = bbo.t.to_numpy(np.int64)
        tp = pr.t.to_numpy(np.int64)
        i = np.clip(np.searchsorted(tb, tp - 1, side="right") - 1, 0, len(tb) - 1)      # the book one ms before the print
        bb, ba = bbo.bb.to_numpy(float)[i], bbo.ba.to_numpy(float)[i]
        px, sg = pr.px.to_numpy(float), pr.sgn.to_numpy(float)
        tick = ticks[sym]
        ok = (tp > tb[0]) & ~pr.paired.to_numpy(bool)
        at_touch = np.where(sg > 0, np.abs(px - ba) <= tick * 1.5, np.abs(px - bb) <= tick * 1.5)
        inside = (px > bb + tick * 0.5) & (px < ba - tick * 0.5)
        lead = np.clip(np.searchsorted(pt, tb, side="right") - 1, 0, len(pt) - 1)
        basis_bp = np.log(((bbo.bb + bbo.ba) / 2).to_numpy(float) / pm[lead]) * 1e4
        print(f"  {sym:14s} book rows {len(bbo):7d} | prints {len(pr):6d} (self-traded {pr.paired.mean():4.0%}) | real prints at the displayed touch {np.mean(at_touch[ok]):4.0%}, inside the spread {np.mean(inside[ok]):4.0%}"
              f" | perp quotes {len(pt):7d} | spot - perp basis bp: median {np.median(basis_bp):+7.1f}, p5..p95 {np.percentile(basis_bp, 5):+.1f}..{np.percentile(basis_bp, 95):+.1f}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--syms", default="")
    ap.add_argument("--show", type=float, default=0.0, help="print the per-pair table of this delta")
    ns = ap.parse_args()
    uni = json.load(open(os.path.join(D5, "spot_perp_universe_20261002.json"), encoding="utf-8"))
    if ns.syms:
        uni = [u for u in uni if u["spot"] in ns.syms.split(",")]
    spec = {x["symbol"]: x for x in json.load(open(os.path.join(D5, "kucoin_spot_symbols_20261002.json"), encoding="utf-8"))}
    ticks = {u["spot"]: float(spec[u["spot"]]["priceIncrement"]) for u in uni}
    if ns.check:
        check(ns.day, uni, ticks)
        return
    facts, parts = [], []
    for u in uni:
        f, r = pair_rows(u["spot"], u["perp"], ns.day, ticks[u["spot"]])
        if f:
            facts.append(f)
        if r is not None:
            parts.append(r)
        print("  done", u["spot"], 0 if r is None else len(r), flush=True)
    rows = pd.concat(parts, ignore_index=True) if parts else None
    if rows is not None:
        os.makedirs(CACHE, exist_ok=True)
        rows.to_parquet(os.path.join(CACHE, f"rows_{ns.day}.parquet"))
    report(ns.day, facts, rows)
    if ns.show and rows is not None:
        print(f"\nper pair, spot centre, delta {ns.show:g} (spot5 / spot60 / spot300 = unhedged net incl. rebate; usd_300 = $ at the 300 s mark)")
        print(by_pair(rows, ns.show).to_string())


if __name__ == "__main__":
    main()
