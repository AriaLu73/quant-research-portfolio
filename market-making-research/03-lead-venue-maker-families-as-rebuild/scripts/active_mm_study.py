#!/usr/bin/env python3
"""research5 AM-1: the taking part of active market making on mid-cap USDT perpetuals.

Take a KuCoin quote that is stale against the Binance-implied fair value, then exit with a resting order at fair value.
Strategy file: docs/research5/strategy_active_mm.md; pre-registration: docs/research5/experiments.md, card AM-1.
The rules (entry_signal, ioc_fill, exit_price, passive_fill_usd, simulate_exit, replay) are those of stale_take_replay.py
(tests/research5/test_stale_take.py); this file adds the loaders for the two-venue recordings, the data checks and the
event study. Matching: queue front. Latency: Binance price 2 ms (conservative 5 ms), order 2 ms.

Inputs (own public recordings, read-only):
  data/research5/xvenue_ku/<day>/<HH>_<SYM>_{l2,snap,trades}.jsonl.gz     KuCoin L2 increments, REST snapshots, prints
  data/research5/xvenue_bn/<day>/<HH>.csv.gz                              Binance best bid / ask (price changes only)
AM-2 (--jump): only quotes that are stale because Binance has just moved: fair value = KuCoin mid W ms ago moved by what
Binance did since, and KuCoin's best prices must not have changed in those W ms.
Usage: Python314/python.exe scripts/research5/active_mm_study.py 20261002 [--check] [--jump] [--syms A,B] [--l2-shift-ms N]
"""
import argparse, glob, gzip, io, json, os, sys, zlib
from dataclasses import replace

import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research4"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stale_take_replay as S  # noqa: E402
import kucoin_trades as KT     # noqa: E402
import l3_parse as LP          # noqa: E402  (research4, read-only: Book)

D5 = os.path.join(ROOT, "data", "research5")
KU, BN, CACHE = os.path.join(D5, "xvenue_ku"), os.path.join(D5, "xvenue_bn"), os.path.join(D5, "amm_cache")
THETAS = (2.0, 3.0, 5.0, 8.0, 12.0)
HORIZONS_MS = (100, 1_000, 5_000, 30_000, 300_000)
BASE = S.Cfg(theta_bp=5.0, ref_lag_ms=2, order_lat_ms=2, clip_usd=1000.0, inv_cap_usd=3000.0, t_max_s=300, binance_max_age_ms=60_000,
             taker_bp=1.8, rebate_bp=OUR_FEE, queue_front=True)
LAG_CONSERVATIVE_MS = 5
JUMP_W_MS = (10, 20, 50)                      # AM-2 grid
JUMP_THETAS = (1.0, 2.0, 3.0, 5.0)


# ------------------------------------------------------------------ parsing
def binance_symbol(ku_sym):
    base = ku_sym[:-5]
    return {"PEPE": "1000PEPE", "XBT": "BTC"}.get(base, base) + "USDT"


def parse_l2_line(line):
    """One recorder line of a KuCoin level2 increment -> (sequence, timestamp ms, price, side +1 bid / -1 ask, size); None otherwise."""
    i = line.find('"change":"')
    if i < 0:
        return None
    j = line.find('"', i + 10)
    k = line.find('"timestamp":', j)
    q = line.find('"sequence":')
    if j < 0 or k < 0 or q < 0:
        return None
    try:
        p, side, s = line[i + 10:j].split(",")
        return int(line[q + 11: line.index(",", q)]), int(line[k + 12: line.index("}", k)]), float(p), 1 if side == "buy" else -1, float(s)
    except ValueError:                                              # a line cut off by a kill
        return None


def gz_lines(path):
    """Lines of a gzip file; a file that is still being written, or whose tail is damaged (killed writer, two writers),
    simply ends early."""
    with gzip.open(path, "rt", errors="replace") as fh:
        try:
            for line in fh:
                yield line
        except (EOFError, OSError, zlib.error):
            return


def json_lines(path):
    """Parsed JSON payloads of a recorder file (same tolerance as gz_lines)."""
    for line in gz_lines(path):
        i = line.find("\t")
        if i > 0:
            try:
                yield json.loads(line[i + 1:])
            except ValueError:
                continue


def l2_events(files, shift_ms=0):
    for f in files:
        for line in gz_lines(f):
            r = parse_l2_line(line)
            if r:
                yield (r[0], r[1] - shift_ms, r[2], r[3], r[4])


def hour_files(day, sym, kind, root=None):
    return sorted(glob.glob(os.path.join(root or KU, day, f"*_{sym}_{kind}.jsonl.gz")))


def build_bbo(day, sym, shift_ms=0, root=None):
    """KuCoin best bid / ask change series (t ms, bb, bq, ba, aq), re-synchronised at every REST snapshot. Cached per number of hour files."""
    files = hour_files(day, sym, "l2", root)
    tag = "" if root is None else os.path.basename(root) + "_"         # the same contract may be recorded in two folders
    cache = os.path.join(CACHE, f"bbo_{tag}{sym}_{day}_{len(files)}h_s{shift_ms}.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    snaps = []
    for f in hour_files(day, sym, "snap", root):
        for m in json_lines(f):
            d = m.get("data")
            if d and d.get("bids") and d.get("asks"):
                snaps.append((int(d["sequence"]), d["bids"], d["asks"]))
    out = S.bbo_from_events(sorted(snaps, key=lambda x: x[0]), l2_events(files, shift_ms), LP.Book())
    os.makedirs(CACHE, exist_ok=True)
    out.to_parquet(cache)
    return out


def load_orders(day, sym, mult, root=None):
    """Real KuCoin taker orders of one contract: t ms, sgn, px_last, usd; paired prints removed."""
    rows = [r for f in hour_files(day, sym, "trades", root) for r in map(KT.parse_line, gz_lines(f)) if r]
    if not rows:
        return pd.DataFrame(columns=["t", "sgn", "px_last", "usd"]), None
    prints = pd.DataFrame(rows, columns=["sym", "ts", "sgn", "px", "size", "tid", "age_ms", "liq"])
    o = KT.to_orders(prints, {sym: mult})
    real = o[~o.pair]
    return pd.DataFrame({"t": real.ts.to_numpy(np.int64) // 1_000_000, "sgn": real.sgn.to_numpy(), "px_last": real.px_last.to_numpy(float),
                         "usd": real.usd.to_numpy(float)}).sort_values("t"), prints


def load_binance(day):
    """{Binance symbol: (T ms ascending, mid, bid, ask)} from the best bid / ask recording (one row per price change)."""
    parts = []
    for f in sorted(glob.glob(os.path.join(BN, day, "*.csv.gz"))):
        text = "".join(gz_lines(f))
        last = text.rfind("\n")
        if last > 0:
            parts.append(pd.read_csv(io.StringIO(text[: last + 1]), header=None, names=["recv", "sym", "T", "E", "bid", "bq", "ask", "aq"],
                                     usecols=["sym", "T", "bid", "ask"]))
    d = pd.concat(parts, ignore_index=True).dropna(subset=["T"])
    d = d[(d.bid > 0) & (d.ask >= d.bid)]
    out = {}
    for sym, g in d.groupby("sym"):
        g = g.sort_values("T", kind="stable").drop_duplicates("T", keep="last")
        out[sym] = (g["T"].to_numpy(np.int64), ((g.bid + g.ask) / 2).to_numpy(float), g.bid.to_numpy(float), g.ask.to_numpy(float))
    return out


# ------------------------------------------------------------------ AM-2: jump fair value
class JumpMarket(S.Market):
    """Market whose fair value is where KuCoin's mid stood w_ms ago, moved by Binance's change over the same w_ms as far
    as we can see it (ref_lag). Entries additionally need KuCoin's best bid and ask prices unchanged over those w_ms:
    fair_grid, which the replay uses for entries only, is NaN elsewhere; fair() itself (used for the exit quote) is not masked."""

    def __init__(self, bbo, bT, bP, cfg, tick, mult, w_ms):
        self.w_ms = w_ms
        super().__init__(bbo, bT, bP, cfg, tick, mult)
        self.fair_grid = np.where(self.unchanged(self.grid), self.fair_grid, np.nan)

    def binance_ratio(self, t):
        """Binance mid visible at t divided by the one visible w_ms earlier; NaN without a price or with a stale feed."""
        tb = np.asarray(t, dtype=np.int64) - self.cfg.ref_lag_ms
        i1 = np.searchsorted(self.bT, tb, side="right") - 1
        i0 = np.searchsorted(self.bT, tb - self.w_ms, side="right") - 1
        j1 = np.clip(i1, 0, len(self.bT) - 1)
        ok = (i0 >= 0) & (tb - self.bT[j1] <= self.cfg.binance_max_age_ms)
        return np.where(ok, self.bP[j1] / self.bP[np.clip(i0, 0, len(self.bT) - 1)], np.nan)

    def fair(self, t):
        t = np.asarray(t, dtype=np.int64)
        bb, _, ba, _ = self.book_at(t - self.w_ms)
        inside = t - self.w_ms >= self.bt[0]
        return np.where(inside, (bb + ba) / 2 * self.binance_ratio(t), np.nan)

    def unchanged(self, t):
        """KuCoin's best bid and best ask prices at t are the ones displayed w_ms earlier."""
        t = np.asarray(t, dtype=np.int64)
        bb0, _, ba0, _ = self.book_at(t - self.w_ms)
        bb1, _, ba1, _ = self.book_at(t)
        return (bb0 == bb1) & (ba0 == ba1) & (t - self.w_ms >= self.bt[0])


class QuoteJumpMarket(JumpMarket):
    """AM-2b: an entry needs Binance's whole quote beyond the KuCoin price: buys are judged against the Binance bid, sells
    against the Binance ask (both relative to the Binance mid w_ms earlier). The exit quote keeps the mid-based fair value."""

    def __init__(self, bbo, bT, bP, bBid, bAsk, cfg, tick, mult, w_ms):
        super().__init__(bbo, bT, bP, cfg, tick, mult, w_ms)
        self.fair_grid = np.where(self.unchanged(self.grid), self.entry_fair(self.grid, bBid, bAsk), np.nan)

    def entry_fair(self, t, bBid, bAsk):
        """Bid-based fair value where it is above the KuCoin ask (a buy candidate), ask-based where it is below the KuCoin bid
        (a sell candidate), NaN otherwise. At most one of the two can hold because the Binance bid is below its ask."""
        t = np.asarray(t, dtype=np.int64)
        tb = t - self.cfg.ref_lag_ms
        i1 = np.searchsorted(self.bT, tb, side="right") - 1
        i0 = np.searchsorted(self.bT, tb - self.w_ms, side="right") - 1
        j1, j0 = np.clip(i1, 0, len(self.bT) - 1), np.clip(i0, 0, len(self.bT) - 1)
        ok = (i0 >= 0) & (tb - self.bT[j1] <= self.cfg.binance_max_age_ms) & (t - self.w_ms >= self.bt[0])
        bb0, _, ba0, _ = self.book_at(t - self.w_ms)
        m0 = (bb0 + ba0) / 2
        f_buy, f_sell = m0 * bBid[j1] / self.bP[j0], m0 * bAsk[j1] / self.bP[j0]
        bb, _, ba, _ = self.book_at(t)
        return np.where(ok & (f_buy > ba), f_buy, np.where(ok & (f_sell < bb), f_sell, np.nan))


# ------------------------------------------------------------------ B-1: quote protection measured on real taker flow
PROTECT_X = (0.0, 1.0, 2.0, 3.0, 5.0)
PROTECT_H_MS = (1_000, 5_000, 300_000)


def quote_margin_bp(sgn, quote_px, fair):
    """How far our resting quote is on the safe side of fair value, bp. sgn = direction of the taker order that would hit it
    (+1: a buy hitting our ask). Negative = the quote is stale (ask below fair / bid above fair)."""
    return sgn * (quote_px - fair) / fair * 1e4


def maker_markout_bp(sgn, quote_px, mid_later):
    """Pnl of the maker filled at quote_px by a taker of direction sgn, marked at a later mid, bp of the fill (before the rebate)."""
    return -sgn * (mid_later - quote_px) / quote_px * 1e4


def touch_fill_usd(sgn, quote_px, taker_px_worst, taker_usd, clip_usd, tick):
    """Fill of a queue-front quote at quote_px against real taker orders: the taker must have traded at or through our price."""
    eps = tick * 1e-6
    reached = np.where(np.asarray(sgn) > 0, taker_px_worst >= quote_px - eps, taker_px_worst <= quote_px + eps)
    return np.where(reached, np.minimum(clip_usd, taker_usd), 0.0)


def protection_rows(markets, real, clip_usd, order_lat_ms, quote_lead_ms=None):
    """One row per real taker order that would have filled a quote resting at the touch order_lat_ms before it arrived:
    fill size, net mark-outs (incl. the rebate) and the quote margin under every fair-value definition in `markets` (name -> Market).
    quote_lead_ms (latency diagnostics only): take the quote from the book this long before the taker instead, so that the set
    of fills is the same for every latency and only the time of the decision (order_lat_ms before the taker) changes.
    It must be >= 1: the book of the taker's own millisecond already contains its trade."""
    mk = next(iter(markets.values()))
    t = real.t.to_numpy(np.int64)
    keep = (t - order_lat_ms > mk.grid[0]) & (t + PROTECT_H_MS[-1] <= mk.bt[-1])
    t, sgn = t[keep], real.sgn.to_numpy(float)[keep]
    td = t - order_lat_ms                                          # the last moment a cancel could still be sent
    bb, _, ba, _ = mk.book_at(td if quote_lead_ms is None else t - quote_lead_ms)
    quote = np.where(sgn > 0, ba, bb)
    fill = touch_fill_usd(sgn, quote, real.px_last.to_numpy(float)[keep], real.usd.to_numpy(float)[keep], clip_usd, mk.tick)
    out = dict(t=t, sgn=sgn, usd=fill, quote=quote, half_spread=(ba - bb) / (ba + bb) * 1e4)
    for h in PROTECT_H_MS:
        b1, _, a1, _ = mk.book_at(t + h)
        out[f"net_{h}"] = maker_markout_bp(sgn, quote, (b1 + a1) / 2) + mk.cfg.rebate_bp
    for name, m in markets.items():
        out[f"g_{name}"] = quote_margin_bp(sgn, quote, m.fair(td))
    d = pd.DataFrame(out)
    return d[d.usd > 0].reset_index(drop=True)


def protect_ci(d, col, n=1000, seed=7):
    g = d.assign(h=d.t // 3_600_000, s=d[col] * d.usd).groupby(["sym", "h"])[["s", "usd"]].sum().to_numpy()
    if len(g) < 5:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n, len(g)))
    return tuple(np.percentile(g[:, 0][idx].sum(1) / g[:, 1][idx].sum(1), [2.5, 97.5]))


def run_protect(day, syms, spec, bn, shift_ms, root=None, clip_usd=None):
    parts, hours = [], 0.0
    clip_usd = clip_usd or BASE.clip_usd
    for sym in syms:
        b = bn.get(binance_symbol(sym))
        bbo = build_bbo(day, sym, shift_ms, root=root)
        if b is None or len(bbo) < 1000:
            continue
        real, _ = load_orders(day, sym, float(spec[sym]["multiplier"]), root=root)
        tick, mult = float(spec[sym]["tickSize"]), float(spec[sym]["multiplier"])
        markets = {"J20": JumpMarket(bbo, b[0], b[1], BASE, tick, mult, 20), "J50": JumpMarket(bbo, b[0], b[1], BASE, tick, mult, 50),
                   "S600": S.Market(bbo, b[0], b[1], BASE, tick, mult), "S10": S.Market(bbo, b[0], b[1], replace(BASE, basis_window_s=10, basis_min_n=5), tick, mult)}
        hours = max(hours, (markets["J20"].grid[-1] - markets["J20"].grid[0]) / 3.6e6)
        d = protection_rows(markets, real, clip_usd, BASE.order_lat_ms)
        if len(d):
            parts.append(d.assign(sym=sym))
        print("  done", sym, len(d), flush=True)
    d = pd.concat(parts, ignore_index=True)
    os.makedirs(CACHE, exist_ok=True)
    d.to_parquet(os.path.join(CACHE, f"protect_{day}_s{shift_ms}" + (f"_{os.path.basename(root)}_{'_'.join(syms)}_clip{clip_usd:g}" if root else "") + ".parquet"))
    w = lambda x, c: float((x[c] * x.usd).sum() / x.usd.sum()) if len(x) else np.nan
    day_usd = lambda x: x.usd.sum() / hours * 24
    print(f"\nB-1 {day}: {len(d)} real taker orders that would fill a touch quote, {hours:.1f} h; net = mark-out to the KuCoin mid + OUR_FEE rebate, usd-weighted bp")
    print(f"  baseline (no protection): ${day_usd(d):,.0f}/day | net 1 s {w(d, 'net_1000'):+.2f} | 5 s {w(d, 'net_5000'):+.2f} | 300 s {w(d, 'net_300000'):+.2f} | half-spread {w(d, 'half_spread'):.2f}")
    edges = [-1e9, -5, -2, -1, 0, 1, 2, 3, 5, 1e9]
    for name in ("J20", "J50", "S600", "S10"):
        g = d[f"g_{name}"]
        print(f"\n  fair value {name}: undefined for {g.isna().mean():.1%} of fills; net by quote margin g (bp)")
        for lo, hi in zip(edges[:-1], edges[1:]):
            x = d[(g >= lo) & (g < hi)]
            if len(x):
                print(f"    g in [{lo:g}, {hi:g}): {x.usd.sum() / d.usd.sum():6.1%} of fills | net 1 s {w(x, 'net_1000'):+6.2f} | 5 s {w(x, 'net_5000'):+6.2f} | 300 s {w(x, 'net_300000'):+6.2f}")
        for xthr in PROTECT_X:
            k = d[g >= xthr]
            if not len(k):
                continue
            lo5, _ = protect_ci(k, "net_5000")
            lo300, hi300 = protect_ci(k, "net_300000")
            per = k.assign(p=k.net_300000 * k.usd).groupby("sym").agg(n=("p", "size"), p=("p", "sum"))
            big = per[per.n >= 20]
            cut = d[~(g >= xthr)]
            print(f"    keep g >= {xthr:g}: ${day_usd(k):>10,.0f}/day ({k.usd.sum() / d.usd.sum():5.1%}) | net 5 s {w(k, 'net_5000'):+.2f} (lower {lo5:+.2f}) | 300 s {w(k, 'net_300000'):+.2f} [{lo300:+.2f}, {hi300:+.2f}]"
                  f" | $/day at 300 s {(k.net_300000 * k.usd).sum() / 1e4 / hours * 24:+,.0f} | contracts>0 {int((big.p > 0).sum())}/{len(big)} | what was pulled: net 300 s {w(cut, 'net_300000'):+.2f}")


# ------------------------------------------------------------------ AM-U1: KuCoin USDT contract leads, USDC contract follows
PAIRS_DIR = os.path.join(D5, "usdc_pairs")
PAIRS = {"XBTUSDCM": "XBTUSDTM", "ETHUSDCM": "ETHUSDTM", "SOLUSDCM": "SOLUSDTM", "XRPUSDCM": "XRPUSDTM", "SUIUSDCM": "SUIUSDTM"}
PAIR_BASE = replace(BASE, ref_lag_ms=1, rebate_bp=OUR_FEE)                 # same venue: the leader is 0.3 ms old (1 ms at this resolution)
PAIR_LAG_CONSERVATIVE_MS = 2
PAIR_THETAS = (1.0, 2.0, 3.0, 5.0, 8.0)
PAIR_W_MS = (20, 100, 1000)
HEDGE_COST_BP = 2 * 1.8                                                # taker in and out on the USDT contract


def leader_arrays(bbo):
    """(t ms, mid, bid, ask) of a leader contract from its best bid / ask series."""
    return bbo.t.to_numpy(np.int64), ((bbo.bb + bbo.ba) / 2).to_numpy(float), bbo.bb.to_numpy(float), bbo.ba.to_numpy(float)


def hedged_net_bp(lots, lead_t, lead_mid):
    """Approximate pnl of each lot if the entry is hedged on the leader with taker orders and the hedge is closed at the
    lot's (size-weighted mean) exit time: net minus the leader's move in our direction over the hold minus the hedge fees."""
    t0 = lots.t.to_numpy(np.int64)
    t1 = t0 + np.round(lots.hold_s.to_numpy(float) * 1000).astype(np.int64)
    m0 = S.LL.last_price_at(lead_t, lead_mid, t0)
    m1 = S.LL.last_price_at(lead_t, lead_mid, t1)
    return lots.pnl_bp.to_numpy(float) - lots.side.to_numpy(float) * (m1 / m0 - 1.0) * 1e4 - HEDGE_COST_BP


def run_pairs(day, spec, shift_ms=0):
    state, hours = {}, 0.0
    for sym, lead in PAIRS.items():
        bbo = build_bbo(day, sym, shift_ms, root=PAIRS_DIR)
        lb = build_bbo(day, lead, shift_ms, root=PAIRS_DIR)
        if len(bbo) < 1000 or len(lb) < 1000:
            print("  skip", sym)
            continue
        b = leader_arrays(lb)
        tick, mult = float(spec[sym]["tickSize"]), float(spec[sym]["multiplier"])
        real, _ = load_orders(day, sym, mult, root=PAIRS_DIR)
        for lag in (PAIR_BASE.ref_lag_ms, PAIR_LAG_CONSERVATIVE_MS):
            cfg = replace(PAIR_BASE, ref_lag_ms=lag)
            markets = {"S600": S.Market(bbo, b[0], b[1], cfg, tick, mult)}
            markets.update({f"J{w}": JumpMarket(bbo, b[0], b[1], cfg, tick, mult, w) for w in PAIR_W_MS})
            for name, mk in markets.items():
                hours = max(hours, (mk.grid[-1] - mk.grid[0]) / 3.6e6)
                for th in PAIR_THETAS:
                    mk.cfg = replace(cfg, theta_bp=th)
                    lots, n_sig, n_miss = S.replay(mk, real)
                    st = state.setdefault((lag, name, th), dict(sig=0, miss=0, lots=[]))
                    st["sig"] += n_sig
                    st["miss"] += n_miss
                    if len(lots):
                        lots = pd.concat([lots, markouts(mk, lots)], axis=1).assign(sym=sym)
                        lots["hedged_bp"] = hedged_net_bp(lots, b[0], b[1])
                        st["lots"].append(lots)
        print("  done", sym, "real taker orders", len(real), flush=True)
    rows, all_lots = [], {}
    for (lag, name, th), st in state.items():
        lots = pd.concat(st["lots"], ignore_index=True) if st["lots"] else pd.DataFrame()
        all_lots[(lag, name, th)] = lots
        r = dict(lag_ms=lag, fair=name, theta=th, **S.summarize(lots, hours, (st["sig"], st["miss"])))
        if len(lots):
            per = lots.assign(p=lots.pnl_bp * lots.usd).groupby("sym").agg(n=("p", "size"), p=("p", "sum"))
            big = per[per.n >= 20]
            r["syms_pos"] = f"{int((big.p > 0).sum())}/{len(big)}"
            r["avg_usd"] = lots.usd.mean()
            r["hedged_bp"] = float((lots.hedged_bp * lots.usd).sum() / lots.usd.sum())
            lots.to_parquet(os.path.join(CACHE, f"lots_AMU1_{day}_lag{lag}_{name}_th{th:g}.parquet"))
        rows.append(r)
    pd.set_option("display.width", 280)
    print(f"\nAM-U1 {day} ({hours:.1f} h): take the USDC quote that is stale against the USDT contract, exit resting at fair; net_bp per $ incl. fees (taker 1.8, rebate 1.2)")
    cols = ["lag_ms", "fair", "theta", "entries", "syms", "signals", "ioc_fill", "entry_usd_day", "avg_usd", "edge", "net_bp", "lo", "hi", "usd_day", "hedged_bp", "passive", "hold_s", "win", "syms_pos"]
    d = pd.DataFrame(rows)
    print(d[[c for c in cols if c in d.columns]].sort_values(["lag_ms", "fair", "theta"]).round(2).to_string(index=False))
    print("\nmark-outs of filled entries at the main lag, usd-weighted bp (k = USDC mid vs our fill price)")
    for name in ["S600"] + [f"J{w}" for w in PAIR_W_MS]:
        for th in PAIR_THETAS:
            lots = all_lots.get((PAIR_BASE.ref_lag_ms, name, th))
            if lots is None or not len(lots):
                continue
            w = lots.usd.to_numpy()
            cells = []
            for h in HORIZONS_MS:
                k = lots[f"k_{h}"].to_numpy()
                m = np.isfinite(k)
                if m.any():
                    cells.append(f"{h / 1000:g}s {np.sum(k[m] * w[m]) / w[m].sum():+.2f}")
            print(f"  {name:5s} theta {th:g}: n {len(lots):5d} edge {np.sum(lots.edge * w) / w.sum():+.2f} | " + " | ".join(cells))
    return all_lots


# ------------------------------------------------------------------ data checks
def l2_stamp_delay(l2_ts, l2_px, l2_side, tr_ms, tr_px, tr_sgn, tick, window_ms=50):
    """For every print: time from the print to the first L2 change at the same price on the side that was hit, looking from
    window_ms before the print (ms; NaN if none within window_ms after it). ~0 means L2 increments are stamped at matching time."""
    t0 = min(l2_ts.min(), tr_ms.min()) - window_ms
    key = np.round(l2_px / tick).astype(np.int64) * 2 + (l2_side > 0)
    k0 = key.min()
    comp = (key - k0) * 10**9 + (l2_ts - t0)
    comp.sort()
    tkey = np.round(tr_px / tick).astype(np.int64) * 2 + (tr_sgn < 0)          # a taker buy hits the ask side (side -1 -> bit 0)
    q = (tkey - k0) * 10**9 + (tr_ms - window_ms - t0)
    i = np.searchsorted(comp, q, side="left")
    ok = i < len(comp)
    hit = comp[np.clip(i, 0, len(comp) - 1)]
    same = ok & (hit // 10**9 == (tkey - k0))
    d = np.where(same, hit % 10**9 + t0 - tr_ms, np.nan).astype(float)
    d[d > window_ms] = np.nan
    return d


def xcorr_lead_ms(t_k, mid_k, t_b, mid_b, t0, t1, step_ms=10, max_lag=10):
    """Correlation of step_ms log returns: corr(KuCoin return at t, Binance return at t - lag*step). Returns {lag_ms: corr};
    a peak at a positive lag means Binance moves first."""
    g = np.arange(t0, t1, step_ms, dtype=np.int64)
    rk = np.diff(np.log(mid_k[np.clip(np.searchsorted(t_k, g, side="right") - 1, 0, None)]))
    rb = np.diff(np.log(mid_b[np.clip(np.searchsorted(t_b, g, side="right") - 1, 0, None)]))
    out = {}
    for lag in range(-max_lag, max_lag + 1):
        a, b = (rk[lag:], rb[:len(rb) - lag]) if lag > 0 else (rk[:len(rk) + lag], rb[-lag:]) if lag < 0 else (rk, rb)
        den = np.sqrt(np.sum(a * a) * np.sum(b * b))
        out[lag * step_ms] = float(np.sum(a * b) / den) if den > 0 else np.nan
    return out


# ------------------------------------------------------------------ event study
def markouts(mk, lots, horizons_ms=HORIZONS_MS):
    """For each filled entry: move of the KuCoin mid relative to our fill price and move of the fair value since the decision,
    signed so that positive = in our favour, bp, at each horizon."""
    t = lots.t.to_numpy(np.int64)
    side, px = lots.side.to_numpy(float), lots.px.to_numpy(float)
    f0 = mk.fair(t - mk.cfg.order_lat_ms)
    out = {}
    for h in horizons_ms:
        bb, _, ba, _ = mk.book_at(t + h)
        inside = t + h <= mk.bt[-1]
        out[f"k_{h}"] = np.where(inside, side * ((bb + ba) / 2 - px) / px * 1e4, np.nan)
        out[f"f_{h}"] = np.where(inside, side * (mk.fair(t + h) - f0) / f0 * 1e4, np.nan)
    return pd.DataFrame(out, index=lots.index)


# ------------------------------------------------------------------ driver
def check(day, syms, spec, bn):
    print(f"data checks, {day}")
    for sym in syms:
        files = hour_files(day, sym, "l2")[1:3]                      # two full hours are enough for a timing check
        ev = np.array([(e[1], e[2], e[3]) for e in l2_events(files)], dtype=float)
        _, prints = load_orders(day, sym, float(spec[sym]["multiplier"]))
        if prints is None or not len(ev):
            continue
        tick = float(spec[sym]["tickSize"])
        tr_ms = prints.ts.to_numpy(np.int64) // 1_000_000
        m = (tr_ms >= ev[0, 0]) & (tr_ms <= ev[-1, 0])
        d = l2_stamp_delay(ev[:, 0].astype(np.int64), ev[:, 1], ev[:, 2], tr_ms[m], prints.px.to_numpy(float)[m], prints.sgn.to_numpy()[m], tick)
        d = d[np.isfinite(d)]
        bbo = build_bbo(day, sym)
        b = bn.get(binance_symbol(sym))
        line = f"  {sym:13s} (a) L2 stamp - print time, ms: n {len(d):6d} of {int(m.sum()):6d} prints"
        if len(d):
            line += f", p10 {np.percentile(d, 10):+.0f} p50 {np.percentile(d, 50):+.0f} p90 {np.percentile(d, 90):+.0f}"
        if b is not None and len(bbo) > 1000:
            t0, t1 = max(bbo.t.iloc[0], b[0][0]), min(bbo.t.iloc[-1], b[0][-1])
            c = xcorr_lead_ms(bbo.t.to_numpy(np.int64), ((bbo.bb + bbo.ba) / 2).to_numpy(float), b[0], b[1], t0, t1)
            best = max(c, key=lambda k: c[k])
            line += f" | (b) 10 ms returns: corr at 0 {c[0]:.3f}, peak {c[best]:.3f} at Binance leading {best:+d} ms, at +10 {c[10]:.3f}, +20 {c[20]:.3f}, -10 {c[-10]:.3f}"
        n_conn = sum(1 for f in hour_files(day, sym, "l2") for ln in gz_lines(f) if '"_marker"' in ln[:60])
        line += f" | (c) L2 connects {n_conn}, BBO rows {len(bbo)}"
        print(line, flush=True)


def report(day, state, hours, tag, key_names, thetas_shown, shift_ms):
    """Summary table over all configurations and the mark-outs at the main Binance lag. state: {key: dict(sig, miss, lots)}."""
    rows, all_lots = [], {}
    for key, st in state.items():
        lots = pd.concat(st["lots"], ignore_index=True) if st["lots"] else pd.DataFrame()
        all_lots[key] = lots
        r = dict(zip(key_names, key), hours=round(hours, 1), **S.summarize(lots, hours, (st["sig"], st["miss"])))
        if len(lots):
            per = lots.assign(p=lots.pnl_bp * lots.usd).groupby("sym").agg(n=("p", "size"), p=("p", "sum"))
            big = per[per.n >= 20]
            r["syms_pos"] = f"{int((big.p > 0).sum())}/{len(big)}"
            lots.to_parquet(os.path.join(CACHE, f"lots_{tag}_{day}_" + "_".join(f"{n}{v:g}" for n, v in zip(key_names, key)) + f"_s{shift_ms}.parquet"))
        rows.append(r)
    pd.set_option("display.width", 260)
    print(f"\n{tag} {day}: all configurations (net_bp per $ of entry notional incl. fees; lo / hi = contract-hour block bootstrap; usd_day at clip $1,000)")
    print(pd.DataFrame(rows).sort_values(list(key_names)).round(2).to_string(index=False))
    print("\nmark-outs of filled entries, usd-weighted bp (k = KuCoin mid vs our fill price, f = fair value since the decision)")
    for key in thetas_shown:
        lots = all_lots.get(key)
        if lots is None or not len(lots):
            continue
        w = lots.usd.to_numpy()
        cells = []
        for h in HORIZONS_MS:
            k, f = lots[f"k_{h}"].to_numpy(), lots[f"f_{h}"].to_numpy()
            m = np.isfinite(k) & np.isfinite(f)
            if m.any():
                cells.append(f"{h / 1000:g}s k {np.sum(k[m] * w[m]) / w[m].sum():+.2f} f {np.sum(f[m] * w[m]) / w[m].sum():+.2f}")
        print(f"  {dict(zip(key_names, key))}: edge at entry {np.sum(lots.edge * w) / w.sum():+.2f} | " + " | ".join(cells))
    return all_lots


def run_jump(day, syms, spec, bn, shift_ms, quote=False):
    """AM-2 (quote=False) / AM-2b (quote=True): grid over the look-back W and the threshold, at the main and the conservative Binance lag."""
    state, hours = {}, 0.0
    for sym in syms:
        b = bn.get(binance_symbol(sym))
        bbo = build_bbo(day, sym, shift_ms)
        if b is None or len(bbo) < 1000:
            print("  skip", sym, "(no Binance prices or no book)")
            continue
        real, _ = load_orders(day, sym, float(spec[sym]["multiplier"]))
        for lag in (BASE.ref_lag_ms, LAG_CONSERVATIVE_MS):
            for w in JUMP_W_MS:
                args = (replace(BASE, ref_lag_ms=lag), float(spec[sym]["tickSize"]), float(spec[sym]["multiplier"]), w)
                mk = QuoteJumpMarket(bbo, b[0], b[1], b[2], b[3], *args) if quote else JumpMarket(bbo, b[0], b[1], *args)
                hours = max(hours, (mk.grid[-1] - mk.grid[0]) / 3.6e6)
                for th in JUMP_THETAS:
                    mk.cfg = replace(BASE, ref_lag_ms=lag, theta_bp=th)
                    lots, n_sig, n_miss = S.replay(mk, real)
                    st = state.setdefault((lag, w, th), dict(sig=0, miss=0, lots=[]))
                    st["sig"] += n_sig
                    st["miss"] += n_miss
                    if len(lots):
                        st["lots"].append(pd.concat([lots, markouts(mk, lots)], axis=1).assign(sym=sym))
        print("  done", sym, flush=True)
    shown = [(BASE.ref_lag_ms, w, th) for w in JUMP_W_MS for th in JUMP_THETAS]
    return report(day, state, hours, "AM-2b" if quote else "AM-2", ("lag_ms", "w_ms", "theta"), shown, shift_ms)


def run(day, syms, spec, bn, shift_ms):
    rows, all_lots = [], {}
    hours = 0.0
    state = {}
    for sym in syms:
        b = bn.get(binance_symbol(sym))
        bbo = build_bbo(day, sym, shift_ms)
        if b is None or len(bbo) < 1000:
            print("  skip", sym, "(no Binance prices or no book)")
            continue
        real, _ = load_orders(day, sym, float(spec[sym]["multiplier"]))
        for lag in (BASE.ref_lag_ms, LAG_CONSERVATIVE_MS):
            mk = S.Market(bbo, b[0], b[1], replace(BASE, ref_lag_ms=lag), float(spec[sym]["tickSize"]), float(spec[sym]["multiplier"]))
            hours = max(hours, (mk.grid[-1] - mk.grid[0]) / 3.6e6)
            for th in THETAS:
                mk.cfg = replace(BASE, ref_lag_ms=lag, theta_bp=th)
                lots, n_sig, n_miss = S.replay(mk, real)
                st = state.setdefault((lag, th), dict(sig=0, miss=0, lots=[]))
                st["sig"] += n_sig
                st["miss"] += n_miss
                if len(lots):
                    st["lots"].append(pd.concat([lots, markouts(mk, lots)], axis=1).assign(sym=sym))
        print("  done", sym, flush=True)
    for (lag, th), st in state.items():
        lots = pd.concat(st["lots"], ignore_index=True) if st["lots"] else pd.DataFrame()
        all_lots[(lag, th)] = lots
        r = dict(lag_ms=lag, theta=th, hours=round(hours, 1), **S.summarize(lots, hours, (st["sig"], st["miss"])))
        if len(lots):
            per = lots.assign(p=lots.pnl_bp * lots.usd).groupby("sym").agg(n=("p", "size"), p=("p", "sum"))
            big = per[per.n >= 20]
            r["syms_pos"] = f"{int((big.p > 0).sum())}/{len(big)}"
            lots.to_parquet(os.path.join(CACHE, f"lots_{day}_lag{lag}_th{th:g}_s{shift_ms}.parquet"))
        rows.append(r)
    pd.set_option("display.width", 260)
    print(f"\nAM-1 {day}: all thresholds (net_bp per $ of entry notional incl. fees; lo / hi = contract-hour block bootstrap; usd_day at clip $1,000)")
    print(pd.DataFrame(rows).sort_values(["lag_ms", "theta"]).round(2).to_string(index=False))
    print("\nmark-outs of filled entries, usd-weighted bp (k = KuCoin mid vs our fill price, f = fair value since the decision), lag 2 ms")
    for th in THETAS:
        lots = all_lots.get((BASE.ref_lag_ms, th))
        if lots is None or not len(lots):
            continue
        w = lots.usd.to_numpy()
        cells = []
        for h in HORIZONS_MS:
            k, f = lots[f"k_{h}"].to_numpy(), lots[f"f_{h}"].to_numpy()
            m = np.isfinite(k) & np.isfinite(f)
            cells.append(f"{h / 1000:g}s k {np.sum(k[m] * w[m]) / w[m].sum():+.2f} f {np.sum(f[m] * w[m]) / w[m].sum():+.2f}")
        print(f"  theta {th:4.0f}: edge at entry {np.sum(lots.edge * w) / w.sum():+.2f} | " + " | ".join(cells))
    return all_lots


def by_symbol(lots):
    g = lots.groupby("sym").apply(lambda b: pd.Series({"entries": len(b), "usd": b.usd.sum(), "edge": (b.edge * b.usd).sum() / b.usd.sum(), "net_bp": (b.pnl_bp * b.usd).sum() / b.usd.sum(),
                                                        "pnl_usd": (b.pnl_bp * b.usd).sum() / 1e4, "passive": (b.passive * b.usd).sum() / b.usd.sum(), "hold_s": (b.hold_s * b.usd).sum() / b.usd.sum()}),
                                  include_groups=False)
    return g.sort_values("usd", ascending=False).round(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day")
    ap.add_argument("--check", action="store_true", help="data checks only")
    ap.add_argument("--jump", action="store_true", help="AM-2: jump fair value with the staleness condition")
    ap.add_argument("--quote-jump", action="store_true", help="AM-2b: as AM-2, entries judged against the Binance bid / ask")
    ap.add_argument("--protect", action="store_true", help="B-1: quote protection measured on real taker flow")
    ap.add_argument("--pairs", action="store_true", help="AM-U1: KuCoin USDT contract as the leader of the USDC contract")
    ap.add_argument("--root", default="", help="--protect only: folder under data/research5 with the KuCoin recordings (default xvenue_ku), e.g. usdc_pairs for XBTUSDTM")
    ap.add_argument("--clip", type=float, default=0.0, help="--protect only: quote size in $ (default 1000)")
    ap.add_argument("--syms", default="")
    ap.add_argument("--l2-shift-ms", type=int, default=0, help="stamp KuCoin L2 increments this much earlier (data check (a))")
    ap.add_argument("--show", type=float, default=0.0, help="print the per-contract table of this threshold")
    ns = ap.parse_args()
    spec = {x["symbol"]: x for x in json.load(open(os.path.join(ROOT, "data", "research4", "contracts_active_20261001.json"), encoding="utf-8"))["data"]}
    if ns.pairs:
        run_pairs(ns.day, spec, ns.l2_shift_ms)
        return
    have = sorted({os.path.basename(f).split("_")[1] for f in glob.glob(os.path.join(os.path.join(D5, ns.root) if ns.root else KU, ns.day, "*_l2.jsonl.gz"))})
    syms = [s for s in (ns.syms.split(",") if ns.syms else have) if s in spec]
    bn = load_binance(ns.day)
    if ns.check:
        check(ns.day, syms, spec, bn)
        return
    if ns.protect:
        run_protect(ns.day, syms, spec, bn, ns.l2_shift_ms, root=os.path.join(D5, ns.root) if ns.root else None, clip_usd=ns.clip or None)
        return
    if ns.jump or ns.quote_jump:
        run_jump(ns.day, syms, spec, bn, ns.l2_shift_ms, quote=ns.quote_jump)
        return
    lots = run(ns.day, syms, spec, bn, ns.l2_shift_ms)
    if ns.show and len(lots.get((BASE.ref_lag_ms, ns.show), ())):
        print(f"\nper contract, theta {ns.show:g}, lag {BASE.ref_lag_ms} ms")
        print(by_symbol(lots[(BASE.ref_lag_ms, ns.show)]).to_string())


if __name__ == "__main__":
    main()
