#!/usr/bin/env python3
"""research5 L-4b: order-book-level replay of 'take KuCoin quotes that are stale against Binance, exit passively at fair'.

Rules are fixed in docs/research5/experiments.md (L-4b). One function per rule; tests in tests/research5/test_stale_take.py.

Inputs (all public recordings, read-only):
  data/research4/l3_raw/<day>/<HH>_<SYM>_l2.jsonl.gz, _snap.jsonl.gz   KuCoin L2 increments + REST snapshots (research4 recorder)
  data/research5/ku_orders_<day>.parquet                                KuCoin taker orders (kucoin_trades.py)
  data/research5/binance_agg/<SYM>_*.csv.gz                             Binance aggTrades (fetch_binance_aggtrades.py)
Outputs: data/research5/bbo_l2/<SYM>_<day>.parquet (cache of the best bid/ask series),
         data/research5/stale_take_lots_<day>_<tag>.parquet (one row per entry lot), printed summary.
Usage: python scripts/research5/stale_take_replay.py 20261001 [SYM1,SYM2] [--all-configs]
"""
import glob, json, math, os, sys
from dataclasses import dataclass, replace

import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research4"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lead_lag as LL  # noqa: E402

D5 = os.path.join(ROOT, "data", "research5")
RAW = os.path.join(ROOT, "data", "research4", "l3_raw")
TAKER_BP, REBATE_BP = OUR_FEE, 0.8


@dataclass(frozen=True)
class Cfg:
    theta_bp: float = 5.0          # entry threshold: quote must be this far through the Binance-implied fair value
    ref_lag_ms: int = 20           # age of the Binance price we are allowed to use
    order_lat_ms: int = 2          # our order reaches KuCoin this long after the decision
    clip_usd: float = 1000.0
    inv_cap_usd: float = 3000.0    # per contract, absolute net
    t_max_s: int = 300             # timeout: take out whatever is left
    exit_add_bp: float = 0.0       # rest the exit this far beyond fair
    binance_max_age_ms: int = 10_000
    basis_window_s: int = 600
    basis_min_n: int = 60
    taker_bp: float = TAKER_BP     # fees of the contract class (defaults: TradFi contracts)
    rebate_bp: float = REBATE_BP
    queue_front: bool = False      # True: an exit that joins the displayed best price is first in line (the project's matching convention)


# ---------------------------------------------------------------- KuCoin best bid/ask from L2 increments

def build_bbo(day, sym):
    """Best bid/ask change series (t ms, bb, bq, ba, aq) from the recorded L2 increments, re-synchronised at every REST
    snapshot. Cached under data/research5/bbo_l2."""
    cache = os.path.join(D5, "bbo_l2", f"{sym}_{day}.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    import l3_parse as LP  # research4: Book (L2 with lazy-deletion heaps) and a tolerant line reader
    snaps, incs = [], []
    for f in sorted(glob.glob(os.path.join(RAW, day, f"*_{sym}_snap.jsonl.gz"))):
        for m in LP.lines(f):
            d = m.get("data")
            if d and d.get("bids") and d.get("asks"):
                snaps.append((int(d["sequence"]), d["bids"], d["asks"]))
    for f in sorted(glob.glob(os.path.join(RAW, day, f"*_{sym}_l2.jsonl.gz"))):
        for m in LP.lines(f):
            d = m.get("data")
            if d and "change" in d:
                p, side, s = d["change"].split(",")
                incs.append((int(d["sequence"]), int(d["timestamp"]), float(p), 1 if side == "buy" else -1, float(s)))
    out = bbo_from_events(sorted(snaps, key=lambda x: x[0]), sorted(incs), LP.Book())
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    out.to_parquet(cache)
    return out


def bbo_from_events(snaps, incs, book):
    """snaps: [(seq, bids, asks)] ascending; incs: [(seq, ts_ms, price, side, size)] ascending. Returns the BBO series,
    one row per millisecond in which the best bid/ask (price or size) changed; crossed or one-sided states are dropped."""
    rows, k, last, cur_ts = [], 0, None, None

    def flush(ts):
        nonlocal last
        (bb, bq), (ba, aq) = book.best(1), book.best(-1)
        state = (bb, bq, ba, aq)
        if book.ok and bb == bb and ba == ba and ba > bb and state != last:
            rows.append((ts, bb, bq, ba, aq))
            last = state

    for seq, ts, p, side, s in incs:
        while k < len(snaps) and snaps[k][0] < seq:     # a snapshot already contains every increment up to its sequence
            if cur_ts is not None:
                flush(cur_ts)
                cur_ts = None                           # the re-synchronised state is stamped with the next increment's time
            book.reset(snaps[k][1], snaps[k][2])
            k += 1
        if not book.ok:                                 # increments before the first snapshot cannot be placed
            continue
        if cur_ts is not None and ts != cur_ts:
            flush(cur_ts)
        book.set(side, p, s)
        cur_ts = ts
    if cur_ts is not None:
        flush(cur_ts)
    return pd.DataFrame(rows, columns=["t", "bb", "bq", "ba", "aq"])


# ---------------------------------------------------------------- fair value

def basis_per_second(t0_s, t1_s, bbo_t, mid, bT, bP, window_s, min_n):
    """b[s] for each second s in [t0_s, t1_s): median of ln(KuCoin mid / Binance last) over the previous `window_s`
    one-second samples (strictly earlier seconds), NaN with fewer than `min_n` valid samples."""
    sec = np.arange(t0_s, t1_s, dtype=np.int64)
    m = LL.last_price_at(bbo_t, mid, sec * 1000)
    p = LL.last_price_at(bT, bP, sec * 1000)
    x = pd.Series(np.log(m / p))
    return sec, x.rolling(window_s, min_periods=min_n).median().shift(1).to_numpy()


def ceil_tick(x, tick):
    return math.ceil(x / tick - 1e-9) * tick


def floor_tick(x, tick):
    return math.floor(x / tick + 1e-9) * tick


# ---------------------------------------------------------------- market state on a common event grid

class Market:
    """Everything the replay looks up, on one sorted grid of event times (KuCoin BBO changes and delayed Binance trades)."""

    def __init__(self, bbo, bT, bP, cfg, tick, mult):
        self.cfg, self.tick, self.mult = cfg, tick, mult
        self.bt = bbo.t.to_numpy(np.int64)
        self.bb, self.bq = bbo.bb.to_numpy(float), bbo.bq.to_numpy(float)
        self.ba, self.aq = bbo.ba.to_numpy(float), bbo.aq.to_numpy(float)
        self.bT, self.bP = bT, bP
        t0, t1 = max(self.bt[0], bT[0]) // 1000 + 1, min(self.bt[-1], bT[-1]) // 1000
        self.sec, self.basis = basis_per_second(t0, t1, self.bt, (self.bb + self.ba) / 2, bT, bP, cfg.basis_window_s, cfg.basis_min_n)
        g = np.unique(np.concatenate([self.bt, bT + cfg.ref_lag_ms]))
        self.grid = g[(g >= t0 * 1000) & (g < t1 * 1000)]
        self.fair_grid = self.fair(self.grid)

    def book_at(self, t):
        """(bb, bq, ba, aq) displayed at time t (last change at or before t)."""
        i = np.clip(np.searchsorted(self.bt, t, side="right") - 1, 0, len(self.bt) - 1)
        return self.bb[i], self.bq[i], self.ba[i], self.aq[i]

    def fair(self, t):
        """Binance-implied fair value usable at time t: Binance last trade as of t - ref_lag, times exp(basis);
        NaN when Binance has not traded for binance_max_age or the basis is not yet defined."""
        t = np.asarray(t, dtype=np.int64)
        tb = t - self.cfg.ref_lag_ms
        i = np.searchsorted(self.bT, tb, side="right") - 1
        ok = i >= 0
        j = np.clip(i, 0, len(self.bT) - 1)
        fresh = ok & (tb - self.bT[j] <= self.cfg.binance_max_age_ms)
        k = np.clip(t // 1000 - self.sec[0], 0, len(self.basis) - 1)
        inside = (t // 1000 >= self.sec[0]) & (t // 1000 <= self.sec[-1])
        return np.where(fresh & inside, self.bP[j] * np.exp(self.basis[k]), np.nan)

    def usd(self, qty, px):
        return qty * self.mult * px


# ---------------------------------------------------------------- rules

def entry_signal(fair, bb, ba, theta_bp):
    """+1 = buy the ask (it is more than theta below fair), -1 = sell the bid, 0 = nothing."""
    if not (fair == fair) or not (ba > bb > 0):
        return 0
    if (fair - ba) / ba * 1e4 > theta_bp:
        return 1
    if (bb - fair) / bb * 1e4 > theta_bp:
        return -1
    return 0


def ioc_fill(side, px_seen, book_at_arrival, clip_usd, mult):
    """IOC at the price we saw: fills only if that price is still the best on arrival; size capped by what is displayed."""
    bb, bq, ba, aq = book_at_arrival
    best, qty = (ba, aq) if side == 1 else (bb, bq)
    if best != px_seen or qty <= 0:
        return 0.0
    return min(clip_usd, qty * mult * px_seen)


def exit_price(side, fair, bb, ba, tick, add_bp):
    """Passive exit quote of a position of sign `side`: at fair (plus add_bp), never crossing the book (post-only).
    Without a usable fair value, join the best quote on our side."""
    if side == 1:   # long -> sell
        if not (fair == fair):
            return ba
        return max(ceil_tick(fair * (1 + add_bp * 1e-4), tick), round(bb + tick, 12))
    if not (fair == fair):
        return bb
    return min(floor_tick(fair * (1 - add_bp * 1e-4), tick), round(ba - tick, 12))


def passive_fill_usd(side, our_px, best_px, best_usd, taker_px_worst, taker_usd, remaining_usd, tick, front=False):
    """How much of our resting exit a real taker order fills:
       alone at a better price than the displayed best -> first in line;
       level with the displayed best -> only what is left after the taker eats the displayed size (front=True: first in line);
       behind the best -> only if the taker traded strictly through our price."""
    eps = tick * 1e-6
    better = our_px < best_px - eps if side == 1 else our_px > best_px + eps
    level = abs(our_px - best_px) <= eps
    if better or (level and front):
        return min(remaining_usd, taker_usd)
    if level:
        return min(remaining_usd, max(0.0, taker_usd - best_usd))
    through = taker_px_worst > our_px + eps if side == 1 else taker_px_worst < our_px - eps
    return remaining_usd if through else 0.0


def lot_pnl_bp(side, entry_px, exits, taker_bp=TAKER_BP, rebate_bp=REBATE_BP):
    """exits: [(px, usd, passive: bool)] summing to the lot. Returns (pnl in bp of entry notional incl. fees, passive share)."""
    tot = sum(u for _, u, _ in exits)
    gross = sum(side * (px - entry_px) / entry_px * 1e4 * u for px, u, _ in exits) / tot
    passive = sum(u for _, u, p in exits if p) / tot
    return gross - taker_bp + rebate_bp * passive - taker_bp * (1 - passive), passive


def simulate_exit(mk, side, entry_px, usd, t_fill, takers):
    """Rest the exit at fair from t_fill; fill it against real taker orders on the opposite side; take out at the timeout.
    takers: (t_ms, px_worst, usd) arrays of real taker orders that trade against our exit (buys if we are long)."""
    cfg, rem, exits, hold = mk.cfg, usd, [], 0.0
    t_end = t_fill + cfg.t_max_s * 1000
    t_exit = t_end
    tt, tp, tu = takers
    for k in range(np.searchsorted(tt, t_fill, side="right"), np.searchsorted(tt, t_end, side="right")):
        t_quote = tt[k] - cfg.order_lat_ms                      # our quote must have been placed before the taker arrived
        if t_quote <= t_fill:
            continue
        bb, bq, ba, aq = mk.book_at(tt[k] - 1)
        our = exit_price(side, float(mk.fair(t_quote)), bb, ba, mk.tick, cfg.exit_add_bp)
        best_px, best_usd = (ba, mk.usd(aq, ba)) if side == 1 else (bb, mk.usd(bq, bb))
        f = passive_fill_usd(side, our, best_px, best_usd, tp[k], tu[k], rem, mk.tick, cfg.queue_front)
        if f > 0:
            exits.append((our, f, True))
            hold += f * (tt[k] - t_fill) / 1000
            rem -= f
            if rem <= 1e-9:
                t_exit = int(tt[k])
                break
    if rem > 1e-9:
        bb, bq, ba, aq = mk.book_at(t_end)
        exits.append((float(bb if side == 1 else ba), rem, False))
        hold += rem * cfg.t_max_s
    pnl, passive = lot_pnl_bp(side, entry_px, exits, cfg.taker_bp, cfg.rebate_bp)
    return pnl, passive, hold / usd, t_exit


def replay(mk, real):
    """real: DataFrame of real KuCoin taker orders for this contract (t ms, sgn, px_last, usd). Returns one row per entry lot."""
    cfg = mk.cfg
    takers = {s: (x.t.to_numpy(np.int64), x.px_last.to_numpy(float), x.usd.to_numpy(float)) for s, x in ((1, real[real.sgn == 1]), (-1, real[real.sgn == -1]))}
    bb, bq, ba, aq = mk.book_at(mk.grid)
    with np.errstate(invalid="ignore"):
        cand = np.flatnonzero(((mk.fair_grid - ba) / ba * 1e4 > cfg.theta_bp) | ((bb - mk.fair_grid) / bb * 1e4 > cfg.theta_bp))
    lots, open_lots, blocked, n_sig, n_miss = [], [], {1: None, -1: None}, 0, 0
    for i in cand:
        t = int(mk.grid[i])
        side = entry_signal(mk.fair_grid[i], bb[i], ba[i], cfg.theta_bp)
        if side == 0:
            continue
        px = ba[i] if side == 1 else bb[i]
        if blocked[side] == px:                                  # this quote was already taken (or missed) once
            continue
        blocked[side] = px
        open_lots = [(te, u) for te, u in open_lots if te > t]
        inv = sum(u for _, u in open_lots)
        if abs(inv + side * cfg.clip_usd) > cfg.inv_cap_usd + 1e-9:
            continue
        n_sig += 1
        t_arr = t + cfg.order_lat_ms
        usd = ioc_fill(side, px, mk.book_at(t_arr), cfg.clip_usd, mk.mult)
        if usd <= 0:
            n_miss += 1
            continue
        pnl, passive, hold_s, t_exit = simulate_exit(mk, side, px, usd, t_arr, takers[side])
        open_lots.append((t_exit, side * usd))
        lots.append(dict(t=t_arr, side=side, px=px, usd=usd, edge=side * (mk.fair_grid[i] - px) / px * 1e4, pnl_bp=pnl, passive=passive, hold_s=hold_s))
    return pd.DataFrame(lots), n_sig, n_miss


# ---------------------------------------------------------------- reporting

def block_ci(lots, n=2000, seed=3):
    """95% CI of the usd-weighted mean pnl_bp, resampling contract-hour blocks."""
    g = lots.assign(h=lots.t // 3_600_000).groupby(["sym", "h"]).apply(lambda b: pd.Series({"s": (b.pnl_bp * b.usd).sum(), "w": b.usd.sum()}), include_groups=False)
    if len(g) < 5:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n, len(g)))
    return tuple(np.percentile(g.s.to_numpy()[idx].sum(1) / g.w.to_numpy()[idx].sum(1), [2.5, 97.5]).round(2))


def summarize(lots, hours, stats):
    if lots.empty:
        return dict(entries=0)
    w = lots.usd
    net = float((lots.pnl_bp * w).sum() / w.sum())
    lo, hi = block_ci(lots)
    return dict(entries=len(lots), syms=lots.sym.nunique(), signals=stats[0], ioc_fill=1 - stats[1] / max(1, stats[0]), entry_usd_day=w.sum() / hours * 24,
                volume_usd_day=2 * w.sum() / hours * 24, edge=float((lots.edge * w).sum() / w.sum()), net_bp=net, lo=lo, hi=hi,
                usd_day=float((lots.pnl_bp * w).sum() / 1e4 / hours * 24), passive=float((lots.passive * w).sum() / w.sum()), hold_s=float((lots.hold_s * w).sum() / w.sum()),
                win=float((lots.pnl_bp > 0).mean()))


def run(day, syms, cfg, spec, ku):
    parts, sig, miss, hours = [], 0, 0, 0.0
    for sym in syms:
        b = LL.load_binance(sym[:-1])
        bbo = build_bbo(day, sym)
        if b is None or len(bbo) < 1000:
            continue
        mk = Market(bbo, b[0], b[1], cfg, float(spec[sym]["tickSize"]), float(spec[sym]["multiplier"]))
        k = ku[(ku.sym == sym) & ~ku.pair]
        real = pd.DataFrame({"t": k.ts.to_numpy(np.int64) // 1_000_000, "sgn": k.sgn.to_numpy(), "px_last": k.px_last.to_numpy(float), "usd": k.usd.to_numpy(float)}).sort_values("t")
        lots, s, m = replay(mk, real)
        sig, miss = sig + s, miss + m
        hours = max(hours, (mk.grid[-1] - mk.grid[0]) / 3.6e6)
        if len(lots):
            parts.append(lots.assign(sym=sym))
    lots = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return lots, hours, (sig, miss)


CONFIGS = {"main": Cfg(), "theta3": Cfg(theta_bp=3.0), "theta8": Cfg(theta_bp=8.0), "lag100": Cfg(ref_lag_ms=100), "lag1000": Cfg(ref_lag_ms=1000),
           "tmax60": Cfg(t_max_s=60), "tmax900": Cfg(t_max_s=900), "exit+2bp": Cfg(exit_add_bp=2.0)}


def main():
    day = sys.argv[1]
    spec = {x["symbol"]: x for x in json.load(open(os.path.join(ROOT, "data", "research4", "contracts_active_20261001.json"), encoding="utf-8"))["data"]}
    have = sorted({os.path.basename(f).split("_")[1] for f in glob.glob(os.path.join(RAW, day, "*_l2.jsonl.gz"))})
    syms = sys.argv[2].split(",") if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else have
    ku = pd.read_parquet(os.path.join(D5, f"ku_orders_{day}.parquet"))
    names = list(CONFIGS) if "--all-configs" in sys.argv else ["main"]
    pd.set_option("display.width", 250)
    rows = []
    for name in names:
        lots, hours, stats = run(day, syms, CONFIGS[name], spec, ku)
        if len(lots):
            lots.to_parquet(os.path.join(D5, f"stale_take_lots_{day}_{name}.parquet"))
        rows.append(dict(cfg=name, hours=round(hours, 1), **summarize(lots, hours, stats)))
        print(pd.DataFrame(rows[-1:]).round(2).to_string(index=False), flush=True)
        if name == "main" and len(lots):
            g = lots.groupby("sym").apply(lambda b: pd.Series({"entries": len(b), "usd": b.usd.sum(), "edge": (b.edge * b.usd).sum() / b.usd.sum(), "net_bp": (b.pnl_bp * b.usd).sum() / b.usd.sum(),
                                                                "pnl_usd": (b.pnl_bp * b.usd).sum() / 1e4, "passive": (b.passive * b.usd).sum() / b.usd.sum(), "hold_s": (b.hold_s * b.usd).sum() / b.usd.sum()}), include_groups=False)
            print(g.sort_values("usd", ascending=False).round(2).to_string(), flush=True)
    print("\n== all configs")
    print(pd.DataFrame(rows).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
