#!/usr/bin/env python3
"""research5 D-1: what a quote resting DEEP in the book (delta bp from fair value) earns on mid-cap KuCoin USDT perps.

Pre-registered in docs/research5/experiments.md (card D-1) before the first run. Offline, no queue model beyond "front of
the queue at our own price", no engine. One taker order = all prints with the same timestamp and side; real orders only
(self-trades and inside-the-spread prints removed with research3/flow_anatomy.py's classification).

  fair F      book mid 1.8 ms before the taker order arrived (our quote was placed on information that old)
  quote P     F (1 +- delta), rounded away from F to the tick; we sell at P to a taker buy, buy at P from a taker sell
  fill        the order printed at P or worse  ->  filled min(clip, $ it traded at P or worse)
  net_h       side-adjusted (P - mid at +h s) / P in bp + maker rebate;  h = 5, 30, 300 s
  tk300       same but closed with a taker order at +300 s at the opposite touch, paying the taker fee
  cash        both sides always quoted at delta, inventory cap +-3 clips, marked at the day's last mid, incl. rebate
  scale 1/k   mean positive reach (farthest print vs F, bp) of real taker orders on the training days, per contract;
              delta = m x (1/k) for m in M_GRID, plus an absolute grid in bp for description

Validity rules added 2026-10-02 after the first run (v1) turned out to be a data artefact: on some contract-days the
purchased book stops updating for hours while trades keep printing 100-400 bp away from the frozen mid; v1 counted those
prints as deep fills (XMR, HYPE, TAO, DOGE on 09-21: "level swept in the book" 0-10 %). A fill now needs
  alive     a book event within ALIVE_US before the fair-value time, and within ALIVE_US before each mark time
  swept     the book itself shows our level consumed: within SWEEP_US after the order the best quote on the taker side
            was at or beyond our price at least once
  requote   after a fill our quote on that side is gone for REQUOTE_US (the 100 ms re-quote gap of the strategy + latency)
1/k uses only orders that pass alive and whose own farthest print is confirmed by the book in the same way.

Inputs : data/research2/events/{book,trades}_<sym>_<day>.parquet (L1 events of the purchased days; prices in ticks)
Outputs: data/research5/deep_quote_curve.parquet (one row per contract, day, hour, grid point), printed tables
Usage  : python scripts/research5/deep_quote_curve.py          (Python314)
"""
import json, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research3"))
EV = os.path.join(ROOT, "data", "research2", "events")
TRAIN, TEST = ("20260910", "20260918"), ("20260921", "20260924")
M_GRID = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0)
BP_GRID = (2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 15.0, 20.0, 30.0)
HS = (5, 30, 300)
LAG_US = 1800          # feed 0.3 ms + order 1.5 ms
CLIP = 1000.0
CAP_CLIPS = 3
REBATE, TAKER = 0.7, 1.8
ALIVE_US = 60_000_000      # the L1 book of these contracts changes many times a second; a minute without any event = feed frozen
SWEEP_US = 50_000
REQUOTE_US = 100_000 + LAG_US


def quote_ticks(fair_t, sgn, delta_bp):
    """Our resting price in ticks against a taker of direction sgn (+1 buy -> we sell above fair), rounded away from fair."""
    raw = fair_t * (1.0 + sgn * delta_bp / 1e4)
    return np.where(sgn > 0, np.ceil(raw - 1e-9), np.floor(raw + 1e-9))


def fill_usd(order_id, sgn_p, px_p, usd_p, quote_p, n_orders, clip):
    """Per order: $ filled on our quote = min(clip, $ of its prints at our price or worse). *_p are per-print arrays,
    quote_p our price (ticks) for the print's order."""
    hit = sgn_p * (px_p - quote_p) >= 0
    return np.minimum(clip, np.bincount(order_id[hit], weights=usd_p[hit], minlength=n_orders))


def net_bp(sgn, quote_t, ref_t, extra_bp):
    """Maker result in bp of a fill at quote_t closed / marked at ref_t (ticks): + when ref is on the right side of our price."""
    return sgn * (quote_t - ref_t) / quote_t * 1e4 + extra_bp


def cash_settle(sgn, usd, px, mid0, mid_end, clip, cap_clips, rebate_bp):
    """Both sides always quoted: take fills in time order while inventory is inside +-cap_clips x clip; mark at mid_end.
    Returns (net $, volume $)."""
    pos = cash = vol = 0.0
    for sg, f, p, m0 in zip(sgn, usd, px, mid0):
        d = -sg
        pu = pos * m0
        if (d > 0 and pu >= cap_clips * clip - 1e-9) or (d < 0 and pu <= -cap_clips * clip + 1e-9):
            continue
        pos += d * f / p
        cash -= d * f
        vol += f
    return cash + pos * mid_end + vol * rebate_bp / 1e4, vol


def window_extremes(ts_book, hi_series, lo_series, t0, t1):
    """Per query window [t0, t1] (inclusive): max of hi_series and min of lo_series over the book events inside it;
    -inf / +inf when the window holds no event."""
    a = np.searchsorted(ts_book, t0, side="left")
    b = np.searchsorted(ts_book, t1, side="right")
    hi = np.full(len(t0), -np.inf)
    lo = np.full(len(t0), np.inf)
    k = np.where(b > a)[0]
    if len(k):
        idx = np.column_stack([a[k], b[k]]).ravel()
        pad_hi = np.append(hi_series, -np.inf)                    # index len(series) is a legal reduceat boundary
        pad_lo = np.append(lo_series, np.inf)
        hi[k] = np.maximum.reduceat(pad_hi, idx)[::2]
        lo[k] = np.minimum.reduceat(pad_lo, idx)[::2]
    return hi, lo


def thin_requote(ts, sgn, gap):
    """Keep mask over time-sorted fills: after a kept fill, later fills on the same side within `gap` are dropped."""
    keep = np.zeros(len(ts), bool)
    last = {1.0: -np.inf, -1.0: -np.inf}
    for i in range(len(ts)):
        s_ = float(sgn[i])
        if ts[i] - last[s_] >= gap:
            keep[i] = True
            last[s_] = ts[i]
    return keep


def alive_at(ts_book, t, window):
    """A book event exists in (t - window, t]."""
    j = np.searchsorted(ts_book, t, side="right") - 1
    return (j >= 0) & (t - ts_book[np.clip(j, 0, None)] < window)


def swept(sgn, quote_t, post_hi, post_lo):
    """The book shows the level at quote_t consumed: after a taker buy the best ask was at or above it, after a taker sell
    the best bid at or below it."""
    return np.where(sgn > 0, post_hi >= quote_t, post_lo <= quote_t)


def at_or_before(ts_book, t):
    return np.clip(np.searchsorted(ts_book, t, side="right") - 1, 0, len(ts_book) - 1)


def load_orders(sym, day):
    """Real taker orders of one contract-day with their prints and the book around them."""
    import flow_anatomy as FA
    b = pd.read_parquet(os.path.join(EV, f"book_{sym}_{day}.parquet"), columns=["ts", "bb", "ba"])
    t = pd.read_parquet(os.path.join(EV, f"trades_{sym}_{day}.parquet"), columns=["ts", "sgn", "px", "qty"])
    tick = float(FA.SPECS[sym]["tick"])
    X = FA.anatomy(sym, day)
    real = X[~X.pair & (X.cat != "in")][["ts", "sg"]].drop_duplicates().rename(columns={"sg": "sgn"})
    real["oid"] = np.arange(len(real))
    p = t.merge(real, on=["ts", "sgn"], how="inner")
    qts = b.ts.to_numpy().astype(np.int64)
    bb, ba = b.bb.to_numpy().astype(float), b.ba.to_numpy().astype(float)
    mid = (bb + ba) / 2.0
    ots, osg = real.ts.to_numpy().astype(np.int64), real.sgn.to_numpy().astype(float)
    i_f = np.searchsorted(qts, ots - LAG_US, side="right") - 1
    ok = i_f >= 0
    fair = mid[np.clip(i_f, 0, None)]
    ok = ok & alive_at(qts, ots - LAG_US, ALIVE_US)
    o = dict(ts=ots, sgn=osg, fair=fair, ok=ok, mid_end=mid[-1], tick=tick, last_ts=qts[-1])
    o["post_hi"], o["post_lo"] = window_extremes(qts, ba, bb, ots, ots + SWEEP_US)
    for h in HS:
        j = at_or_before(qts, ots + h * 1_000_000)
        o[f"mid{h}"] = mid[j]
        o[f"valid{h}"] = (ots + h * 1_000_000 <= qts[-1]) & alive_at(qts, ots + h * 1_000_000, ALIVE_US)
    j = at_or_before(qts, ots + 300 * 1_000_000)
    o["exit300"] = np.where(osg > 0, ba[j], bb[j])            # we sold to a taker buy -> buy back at the ask
    oid = p.oid.to_numpy()
    px = p.px.to_numpy().astype(float)
    pr = dict(oid=oid, sgn=p.sgn.to_numpy().astype(float), px=px, usd=px * tick * p.qty.to_numpy().astype(float))
    far = np.full(len(real), -np.inf)
    np.maximum.at(far, oid, pr["sgn"] * (px - fair[oid]) / fair[oid] * 1e4)
    o["reach"] = far
    far_t = fair * (1.0 + osg * far / 1e4)                         # the order's own farthest price, ticks
    o["reach_ok"] = ok & swept(osg, far_t - osg * 1e-6, o["post_hi"], o["post_lo"])
    return o, pr


def grid_rows(sym, day, o, pr, deltas, kind, labels):
    """One row per (hour, grid point): fills, $ filled, $-weighted sums of the markouts; plus the cash-settled result."""
    rows, n = [], len(o["ts"])
    hour = (o["ts"] // 3_600_000_000) % 24
    for d_bp, lab in zip(deltas, labels):
        q = quote_ticks(o["fair"], o["sgn"], d_bp)
        f = fill_usd(pr["oid"], pr["sgn"], pr["px"], pr["usd"], q[pr["oid"]], n, CLIP)
        m = (f > 0) & o["ok"] & swept(o["sgn"], q, o["post_hi"], o["post_lo"])
        if not m.any():
            continue
        idx = np.where(m)[0]
        m[idx[~thin_requote(o["ts"][idx], o["sgn"][idx], REQUOTE_US)]] = False
        nets = {h: net_bp(o["sgn"], q, o[f"mid{h}"], REBATE) for h in HS}
        tk = net_bp(o["sgn"], q, o["exit300"], REBATE - TAKER)
        cnet, cvol = cash_settle(o["sgn"][m], f[m], q[m] * o["tick"], o["fair"][m] * o["tick"], o["mid_end"] * o["tick"], CLIP, CAP_CLIPS, REBATE)
        for hh in np.unique(hour[m]):
            k = m & (hour == hh)
            r = dict(sym=sym, day=day, hour=int(hh), kind=kind, grid=lab, delta_bp=float(d_bp), n=int(k.sum()), usd=float(f[k].sum()))
            for h in HS:
                v = k & o[f"valid{h}"]
                r[f"s{h}"] = float((f[v] * nets[h][v]).sum())
                r[f"u{h}"] = float(f[v].sum())
            v = k & o["valid300"]
            r["stk"] = float((f[v] * tk[v]).sum())
            rows.append(r)
        rows.append(dict(sym=sym, day=day, hour=-1, kind=kind, grid=lab, delta_bp=float(d_bp), n=0, usd=0.0, cash_net=cnet, cash_vol=cvol))
    return rows


def pooled(df, h=300):
    """$-weighted mean markout (bp) of a set of rows."""
    u = df[f"u{h}"].sum()
    return df[f"s{h}"].sum() / u if u > 0 else np.nan


def block_ci(df, n=2000, seed=7):
    """95 % interval of the pooled 300 s markout, resampling (contract, day, hour) blocks."""
    g = df.groupby(["sym", "day", "hour"])[["s300", "u300"]].sum().to_numpy()
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        i = rng.integers(0, len(g), len(g))
        out.append(g[i, 0].sum() / g[i, 1].sum())
    return np.percentile(out, [2.5, 97.5])


def table(df, days, label):
    d = df[df.day.isin(days)]
    hrs = d[d.hour >= 0]
    cash = d[d.hour < 0]
    print(f"\n{label}  (days {', '.join(days)})")
    print("    grid  delta bp(median)   fills    fill $/day    net5   net30  net300   taker-exit300   cash bp   contracts net300>0")
    for lab, g in hrs.groupby("grid", sort=False):
        c = cash[cash.grid == lab]
        per = g.groupby("sym").apply(lambda x: x.s300.sum() / x.u300.sum() if x.u300.sum() > 0 else np.nan, include_groups=False)
        print(f"  {lab:>6}  {g.delta_bp.median():12.2f}   {g.n.sum():7d}  {g.usd.sum() / len(days):12,.0f}  {pooled(g, 5):6.2f}  {pooled(g, 30):6.2f}  {pooled(g, 300):6.2f}"
              f"   {g.stk.sum() / g.u300.sum():12.2f}   {c.cash_net.sum() / c.cash_vol.sum() * 1e4:7.2f}   {int((per > 0).sum())}/{per.notna().sum()}")


def main():
    uni = pd.read_csv(os.path.join(ROOT, "data", "research5", "alt_usdt_universe.csv")).head(22).sym.tolist()
    cache = {}
    invk = {}
    for s in uni:
        r = []
        for day in TRAIN:
            cache[(s, day)] = load_orders(s, day)
            o = cache[(s, day)][0]
            r.append(o["reach"][o["reach_ok"] & (o["reach"] > 0)])
        invk[s] = float(np.concatenate(r).mean())
    print("1/k per contract (bp, training days):", {s[:-5]: round(v, 2) for s, v in invk.items()})
    rows, alive = [], {}
    for s in uni:
        for day in TRAIN + TEST:
            o, pr = cache.pop((s, day)) if (s, day) in cache else load_orders(s, day)
            alive[(s[:-5], day[-4:])] = round(float(o["ok"].mean()), 2)
            rows += grid_rows(s, day, o, pr, [m * invk[s] for m in M_GRID], "m", [f"{m:g}x" for m in M_GRID])
            rows += grid_rows(s, day, o, pr, list(BP_GRID), "bp", [f"{d:g}bp" for d in BP_GRID])
        print(s, "done", flush=True)
    df = pd.DataFrame(rows).fillna({"s5": 0, "u5": 0, "s30": 0, "u30": 0, "s300": 0, "u300": 0, "stk": 0})
    df.to_parquet(os.path.join(ROOT, "data", "research5", "deep_quote_curve_v2.parquet"))
    json.dump(invk, open(os.path.join(ROOT, "data", "research5", "deep_quote_invk_v2.json"), "w"), indent=1)
    print("contract-days where under 90 % of the real taker orders had a live book:", {k: v for k, v in alive.items() if v < 0.9})
    M = df[df.kind == "m"]
    table(M, TRAIN, "TRAIN, delta = m x (1/k)")
    tr = M[M.day.isin(TRAIN) & (M.hour >= 0)]
    profit = tr.groupby("grid", sort=False).s300.sum() / 1e4
    m_star = profit.idxmax()
    print("\ntraining profit $ by m (sum of fill $ x net300):", profit.round(1).to_dict(), "-> m* =", m_star)
    table(M, TEST, "TEST, delta = m x (1/k)")
    te = M[M.day.isin(TEST) & (M.hour >= 0) & (M.grid == m_star)]
    lo, hi = block_ci(te)
    per = te.groupby("sym").apply(lambda x: x.s300.sum() / x.u300.sum() if x.u300.sum() > 0 else np.nan, include_groups=False)
    c = M[M.day.isin(TEST) & (M.hour < 0) & (M.grid == m_star)]
    cash_bp = c.cash_net.sum() / c.cash_vol.sum() * 1e4
    share = (per > 0).sum() / per.notna().sum()
    byday = te.groupby("day").apply(lambda x: x.s300.sum() / x.u300.sum(), include_groups=False).round(2).to_dict()
    top = (te.groupby("sym").s300.sum() / 1e4).sort_values(ascending=False)
    print("test net300 by day:", byday, "| test profit $ by contract:", {k[:-5]: round(v) for k, v in top.items()})
    print(f"\nPRIMARY (test days, m* = {m_star}): net300 {pooled(te):+.2f} bp [{lo:+.2f}, {hi:+.2f}]; cash-settled {cash_bp:+.2f} bp; contracts positive {int((per > 0).sum())}/{per.notna().sum()};"
          f" fill $ per day {te.usd.sum() / len(TEST):,.0f}; test profit per day ${te.s300.sum() / 1e4 / len(TEST):,.1f}")
    print("pass lines: (1) net300 > 0 and CI lower > 0:", bool(pooled(te) > 0 and lo > 0), "| (2) cash > 0:", bool(cash_bp > 0), "| (3) >= 60 % contracts positive:", bool(share >= 0.6))
    table(df[df.kind == "bp"], TRAIN, "TRAIN, absolute delta (description only)")
    table(df[df.kind == "bp"], TEST, "TEST, absolute delta (description only)")


if __name__ == "__main__":
    main()
