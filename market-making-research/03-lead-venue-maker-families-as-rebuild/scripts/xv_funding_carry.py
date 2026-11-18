#!/usr/bin/env python3
"""research5 F-1 (XV-FUND): funding-rate differential between KuCoin and the same perpetual on Binance / Bybit / OKX.

Strategy file: docs/research5/strategy_xv_funding.md; pre-registration: docs/research5/experiments.md, card F-1.
  D(t)   = sum over (t-8h, t] of (KuCoin funding - other venue's funding), evaluated at 00 / 08 / 16 UTC
  phi    = pooled no-intercept slope of D(t+8h) on D(t), data before t only (expanding, at least 30 days)
  entry  = |D| phi / (1 - phi) >= round-trip cost (four taker legs + both spreads); side = sign(D): short the venue that pays more
  exit   = first decision time at which the differential has changed sign; fills one hour after the decision at the bar open
Data: scripts/research5/funding_download.py -> data/research5/funding.
Usage: Python314/python.exe scripts/research5/xv_funding_carry.py
"""
import glob, json, os
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(ROOT, "data", "research5", "funding")
HOUR_MS = 3_600_000
BLOCK_H = 8
K_TAKER, K_MAKER = 1.8, -0.7
TAKER = {"binance": 5.0, "bybit": 5.5, "okx": 5.0}             # ordinary tier, bp
WARM_DAYS = 30
TEST_START = pd.Timestamp("2026-07-01", tz="UTC")
TEST_END = pd.Timestamp("2026-10-01", tz="UTC")
FIXED = (5.0, 10.0, 20.0)
ADV_SHARE = 0.01
EXEC_DELAY_H = 1


# ------------------------------------------------------------------ pure rules
def hour_of(ts_ms):
    """Funding timestamps carry a few ms of jitter: round to the nearest hour (ms)."""
    return (np.asarray(ts_ms, dtype=np.int64) + HOUR_MS // 2) // HOUR_MS * HOUR_MS


def hourly_funding(ts_ms, rate, grid):
    """Funding paid at each hour of grid (0 where nothing settled), bp."""
    s = pd.Series(np.asarray(rate, dtype=float) * 1e4, index=hour_of(ts_ms)).groupby(level=0).sum()
    return s.reindex(grid).fillna(0.0).to_numpy()


def block_sum(x, n=BLOCK_H):
    """Trailing sum over (h - n, h] on the hourly grid; NaN for the first n - 1 hours."""
    c = np.cumsum(np.nan_to_num(x))
    out = c.copy()
    out[n:] = c[n:] - c[:-n]
    out[: n - 1] = np.nan
    return out


def price_scale(pk, px):
    """Power of ten that aligns the two venues' quoting units, and the remaining relative gap of the median price ratio."""
    r = np.nanmedian(pk / px)
    if not np.isfinite(r) or r <= 0:
        return np.nan, np.nan
    scale = 10.0 ** np.round(np.log10(r))
    return scale, abs(r / scale - 1.0)


def pooled_phi(d_now, d_next, lo, hi):
    """No-intercept slope of the next block's differential on the current one, both clipped to [lo, hi]."""
    a, b = np.clip(d_now, lo, hi), np.clip(d_next, lo, hi)
    den = float(np.sum(a * a))
    return float(np.sum(a * b) / den) if den > 0 else np.nan


def expected_carry(d, phi):
    """Cumulative differential expected after the decision if D follows a zero-mean AR(1): |d| phi / (1 - phi)."""
    phi = np.clip(phi, 0.0, 0.999)
    return np.abs(d) * phi / (1.0 - phi)


def round_trip_cost(venue, spread_k, spread_x, k_maker=False):
    """bp for opening and closing both legs. Taker everywhere: four fees and both full spreads.
    k_maker: the KuCoin leg rests (rebate, no KuCoin spread paid) - assumes the resting order fills."""
    if k_maker:
        return 2 * K_MAKER + 2 * TAKER[venue] + spread_x
    return 2 * K_TAKER + 2 * TAKER[venue] + spread_k + spread_x


def simulate_pair(dec_idx, D, enter, fk, fx, basis, ok, delay=EXEC_DELAY_H):
    """One coin, one venue pair. dec_idx: hourly indices of the decision times; D: differential at those times (bp);
    enter: boolean per decision; fk / fx: hourly funding (bp); basis: ln(p_K / p_X) at each hour's open; ok: both prices exist.
    Returns one dict per round trip: entry / exit hour index, side, funding collected, price pnl (bp), forced (data ended)."""
    out, pos = [], None
    n = len(basis)
    for j, h in enumerate(dec_idx):
        he = h + delay
        if pos is not None:
            flipped = pos["side"] * D[j] <= 0
            last = j == len(dec_idx) - 1 or he >= n - 1
            if (flipped or last) and he < n and ok[he]:
                fund = pos["side"] * float(np.sum(fk[pos["h"] + 1: he + 1] - fx[pos["h"] + 1: he + 1]))
                out.append(dict(h_in=pos["h"], h_out=he, side=pos["side"], d_in=pos["d"], fund=fund,
                                price=-pos["side"] * (basis[he] - basis[pos["h"]]) * 1e4, forced=bool(last and not flipped)))
                pos = None
        if pos is None and enter[j] and np.isfinite(D[j]) and D[j] != 0 and he < n - 1 and ok[he] and j < len(dec_idx) - 1:
            pos = dict(h=he, side=float(np.sign(D[j])), d=float(D[j]))
    if pos is not None:                                                # prices ended (delisting): close at the last common bar
        later = np.where(ok[pos["h"] + 1:])[0]
        if len(later):
            he = pos["h"] + 1 + int(later[-1])
            fund = pos["side"] * float(np.sum(fk[pos["h"] + 1: he + 1] - fx[pos["h"] + 1: he + 1]))
            out.append(dict(h_in=pos["h"], h_out=he, side=pos["side"], d_in=pos["d"], fund=fund,
                            price=-pos["side"] * (basis[he] - basis[pos["h"]]) * 1e4, forced=True))
    return out


def worst_leg_move(side, hi_k, lo_k, hi_x, lo_x, p_k, p_x):
    """Largest adverse move of a single leg during the hold, as a fraction of its entry price (side +1: short KuCoin, long X)."""
    if side > 0:
        return max(np.nanmax(hi_k) / p_k - 1.0, 1.0 - np.nanmin(lo_x) / p_x)
    return max(1.0 - np.nanmin(lo_k) / p_k, np.nanmax(hi_x) / p_x - 1.0)


# ------------------------------------------------------------------ data
def load_raw(venue, kind):
    out = {}
    for p in sorted(glob.glob(os.path.join(DIR, f"raw_{venue}_{kind}*.jsonl"))):
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:  # noqa: BLE001 - a cut line
                    continue
                if r["rows"] and len(r["rows"]) >= len(out.get(r["key"], ())):
                    out[r["key"]] = np.asarray(r["rows"], dtype=float)
    return out


def load_spreads():
    s = pd.read_json(os.path.join(DIR, "spreads.jsonl"), lines=True)
    s = s[(s.bid > 0) & (s.ask > s.bid)]
    s["bp"] = (s.ask - s.bid) / ((s.ask + s.bid) / 2) * 1e4
    return s.groupby(["venue", "key"]).bp.median()


def build_pair(key, venue, F, K, grid):
    """Hourly arrays of one coin on KuCoin and one other venue, or None if the pair is unusable."""
    if key not in F["kucoin"] or key not in F[venue] or key not in K["kucoin"] or key not in K[venue]:
        return None
    kk, kx = K["kucoin"][key], K[venue][key]
    def col(k, c):
        return pd.Series(k[:, c], index=k[:, 0].astype(np.int64)).reindex(grid).to_numpy()
    pk, px = col(kk, 1), col(kx, 1)
    scale, gap = price_scale(pk, px)
    if not np.isfinite(scale) or gap > 0.05:
        return dict(bad="scale", gap=gap)
    fk = hourly_funding(F["kucoin"][key][:, 0], F["kucoin"][key][:, 1], grid)
    fx = hourly_funding(F[venue][key][:, 0], F[venue][key][:, 1], grid)
    first = max(F["kucoin"][key][0, 0], F[venue][key][0, 0])
    last = min(F["kucoin"][key][-1, 0], F[venue][key][-1, 0])           # after either history ends the differential is unknown
    live = (grid >= hour_of(first)) & (grid <= hour_of(last) + BLOCK_H * HOUR_MS)
    ok = np.isfinite(pk) & np.isfinite(px) & live
    with np.errstate(invalid="ignore", divide="ignore"):
        basis = np.log(pk / (px * scale))
    tk = pd.Series(col(kk, 5)).rolling(168, min_periods=72).sum().shift(1).to_numpy() / 7.0
    tx = pd.Series(col(kx, 5)).rolling(168, min_periods=72).sum().shift(1).to_numpy() / 7.0
    return dict(fk=fk, fx=fx, basis=basis, ok=ok, live=live, adv=np.fmin(tk, tx), hi_k=col(kk, 2), lo_k=col(kk, 3), hi_x=col(kx, 2) * scale, lo_x=col(kx, 3) * scale,
                pk=pk, px=px * scale)


def boot_ci(tr, n=2000, seed=11):
    g = tr.assign(w=tr.usd * tr.net).groupby("key")[["w", "usd"]].sum().to_numpy()
    if len(g) < 3:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    v = [g[i, 0].sum() / g[i, 1].sum() for i in (rng.integers(0, len(g), len(g)) for _ in range(n))]
    return tuple(np.percentile(v, [2.5, 97.5]))


def report(tr, label, days):
    if not len(tr):
        print(f"  {label:10s} no trades")
        return None
    w = lambda c: float((tr[c] * tr.usd).sum() / tr.usd.sum())
    lo, hi = boot_ci(tr)
    by_m = tr.assign(w=tr.usd * tr.net).groupby("month")[["w", "usd"]].sum()
    by_m = (by_m.w / by_m.usd).round(1).to_dict()
    per = tr.assign(p=tr.usd * tr.net / 1e4).groupby("key").p.sum().sort_values(ascending=False)
    tot = per.sum()
    top5 = per.head(5).sum() / tot if tot > 0 else np.nan
    occupied = float((tr.usd * tr.hold_h).sum() / (days * 24))
    print(f"  {label:10s} trades {len(tr):5d} coins {tr.key.nunique():4d} | per $ net {w('net'):+7.1f} bp [{lo:+.1f}, {hi:+.1f}] = funding {w('fund'):+.1f} + price {w('price'):+.1f} - cost {w('cost'):.1f}"
          f" | hold mean {tr.hold_h.mean():.0f} h median {tr.hold_h.median():.0f} h | by month {by_m} | coins>0 {(per > 0).mean():.0%} | top-5 share {top5:.0%}"
          f" | $/day {tot / days:,.0f} on average open notional ${occupied:,.0f} | KuCoin-maker variant {w('net_km'):+.1f} bp"
          f" | worst single leg: median {tr.worst.median():.1%}, p95 {tr.worst.quantile(0.95):.1%}, >20% in {np.mean(tr.worst > 0.2):.1%} of trades")
    return dict(net=w("net"), lo=lo, by_m=by_m, share=float((per > 0).mean()), top5=top5)


def main():
    F = {v: load_raw(v, "funding") for v in ("kucoin", "binance", "bybit", "okx")}
    K = {v: load_raw(v, "klines") for v in ("kucoin", "binance", "bybit", "okx")}
    print("coins with data:", {v: (len(F[v]), len(K[v])) for v in F})
    spreads = load_spreads()
    t0 = min(k[0, 0] for k in K["kucoin"].values())
    t1 = max(k[-1, 0] for k in K["kucoin"].values())
    grid = np.arange(int(t0), int(t1) + HOUR_MS, HOUR_MS, dtype=np.int64)
    when = pd.to_datetime(grid, unit="ms", utc=True)
    dec_idx = np.where((when.hour % BLOCK_H == 0))[0]
    dec_idx = dec_idx[dec_idx >= BLOCK_H]
    days = (TEST_END - TEST_START).days
    passed = {}
    for venue in ("binance", "bybit", "okx"):
        pairs, bad = {}, 0
        for key in sorted(F["kucoin"]):
            P = build_pair(key, venue, F, K, grid)
            if P is None:
                continue
            if "bad" in P:
                bad += 1
                continue
            P["D"] = block_sum(P["fk"] - P["fx"])[dec_idx]
            P["D"][~(P["live"][dec_idx - BLOCK_H + 1] & P["live"][dec_idx])] = np.nan    # the whole block must lie inside both funding histories
            pairs[key] = P
        print(f"\n===== KuCoin vs {venue}: {len(pairs)} coins usable, {bad} dropped for a price-unit mismatch")
        if not pairs:
            continue
        keys = sorted(pairs)
        Dm = np.vstack([pairs[k]["D"] for k in keys])                   # coins x decisions
        # ---- data check (b): which alignment of KuCoin's funding timestamps matches the other venue best
        fk8 = np.vstack([block_sum(pairs[k]["fk"])[dec_idx] for k in keys])
        fx8 = np.vstack([block_sum(pairs[k]["fx"])[dec_idx] for k in keys])
        for lag in (-1, 0, 1):
            cs = []
            for a, b in zip(fk8, fx8):
                a2, b2 = (a[1:], b[:-1]) if lag == 1 else (a[:-1], b[1:]) if lag == -1 else (a, b)
                m = np.isfinite(a2) & np.isfinite(b2)
                if m.sum() > 100 and np.std(a2[m]) > 0 and np.std(b2[m]) > 0:
                    cs.append(np.corrcoef(a2[m], b2[m])[0, 1])
            print(f"  check (b) KuCoin block t{lag:+d} vs {venue} block t: median correlation {np.median(cs):.3f} over {len(cs)} coins")
        # ---- F-1a
        test_cols = (when[dec_idx] >= TEST_START) & (when[dec_idx] < TEST_END)
        d = Dm[:, test_cols]
        d = d[np.isfinite(d)]
        print(f"  F-1a |D| per 8 h, test period: median {np.median(np.abs(d)):.2f} bp, p90 {np.percentile(np.abs(d), 90):.2f}, p99 {np.percentile(np.abs(d), 99):.1f};"
              f" share >= 5 bp {np.mean(np.abs(d) >= 5):.2%}, >= 10 bp {np.mean(np.abs(d) >= 10):.2%}, >= 20 bp {np.mean(np.abs(d) >= 20):.2%}")
        a, b = Dm[:, :-1][:, test_cols[:-1]], Dm[:, 1:][:, test_cols[:-1]]
        m = np.isfinite(a) & np.isfinite(b)
        lo, hi = np.percentile(a[m], [1, 99])
        print(f"       persistence (pooled, clipped at 1-99 %): phi {pooled_phi(a[m], b[m], lo, hi):.3f}")
        for x, y in ((2, 5), (5, 10), (10, 20), (20, 1e9)):
            sel = m & (np.abs(a) >= x) & (np.abs(a) < y)
            if sel.sum():
                print(f"       |D| in [{x:g}, {y:g}) bp: n {int(sel.sum()):6d}, mean |D| {np.mean(np.abs(a[sel])):6.1f}, next block in the same direction {np.mean(b[sel] * np.sign(a[sel])):+6.2f} bp,"
                      f" same sign {np.mean(b[sel] * np.sign(a[sel]) > 0):.0%}")
        # ---- phi known at each decision: expanding window, data strictly before the decision
        phi_t = np.full(len(dec_idx), np.nan)
        warm = WARM_DAYS * 24 // BLOCK_H
        for j in range(warm, len(dec_idx)):
            a, b = Dm[:, : j - 1], Dm[:, 1:j]
            m = np.isfinite(a) & np.isfinite(b)
            if m.any(axis=0).sum() >= warm:                              # at least 30 days of blocks with data (OKX history starts later)
                lo, hi = np.percentile(a[m], [1, 99])
                phi_t[j] = pooled_phi(a[m], b[m], lo, hi)
        known = np.where(np.isfinite(phi_t))[0]
        if len(known):
            print(f"       phi used by the rule: from {when[dec_idx[known[0]]].date()}, first {phi_t[known[0]]:.3f}, last {phi_t[-1]:.3f}, min {np.nanmin(phi_t):.3f}, max {np.nanmax(phi_t):.3f}")
        # ---- F-1b
        rules = {"cost": None, **{f"fixed{v:g}": v for v in FIXED}}
        trades = {r: [] for r in rules}
        no_spread = 0
        for key in keys:
            P = pairs[key]
            sk, sx = spreads.get(("kucoin", key), np.nan), spreads.get((venue, key), np.nan)
            if not (np.isfinite(sk) and np.isfinite(sx)):
                no_spread += 1
                continue
            cost, cost_km = round_trip_cost(venue, sk, sx), round_trip_cost(venue, sk, sx, k_maker=True)
            in_test = (when[dec_idx] >= TEST_START) & (when[dec_idx] < TEST_END)
            for rule, val in rules.items():
                with np.errstate(invalid="ignore"):
                    enter = (expected_carry(P["D"], phi_t) >= cost) if val is None else (np.abs(P["D"]) >= val)
                enter = enter & np.isfinite(P["D"]) & in_test
                for t in simulate_pair(dec_idx, np.nan_to_num(P["D"]), enter, P["fk"], P["fx"], P["basis"], P["ok"]):
                    hi, ho = t["h_in"], t["h_out"]
                    usd = ADV_SHARE * P["adv"][hi]
                    if not (np.isfinite(usd) and usd > 0):
                        continue
                    worst = worst_leg_move(t["side"], P["hi_k"][hi:ho + 1], P["lo_k"][hi:ho + 1], P["hi_x"][hi:ho + 1], P["lo_x"][hi:ho + 1], P["pk"][hi], P["px"][hi])
                    trades[rule].append(dict(key=key, venue=venue, t_in=when[hi], month=when[hi].strftime("%m"), hold_h=ho - hi, side=t["side"], d_in=t["d_in"], usd=usd,
                                             fund=t["fund"], price=t["price"], cost=cost, net=t["fund"] + t["price"] - cost, net_km=t["fund"] + t["price"] - cost_km,
                                             worst=worst, forced=t["forced"]))
        print(f"  F-1b test period {TEST_START.date()} .. {TEST_END.date()} ({no_spread} coins without a spread snapshot skipped)")
        for rule in rules:
            tr = pd.DataFrame(trades[rule])
            if len(tr):
                tr.to_parquet(os.path.join(DIR, f"trades_{venue}_{rule}.parquet"))
            r = report(tr, rule, days)
            if rule == "cost":
                passed[venue] = r
                if r:
                    per = tr.assign(p=tr.usd * tr.net / 1e4).groupby("key").agg(p=("p", "sum"), n=("p", "size"), usd=("usd", "sum")).sort_values("p")
                    print("             best coins $:", {k: round(v) for k, v in per.p.tail(5).items()}, "| worst:", {k: round(v) for k, v in per.p.head(5).items()})
    r = passed.get("binance")
    if r:
        rep = [v for v in ("bybit", "okx") if passed.get(v) and passed[v]["net"] > 0]
        print(f"\nPRIMARY (cost rule, KuCoin vs Binance): (1) net > 0 and CI lower > 0: {bool(r['net'] > 0 and r['lo'] > 0)} | (2) every month positive: {all(v > 0 for v in r['by_m'].values()) and len(r['by_m']) == 3}"
              f" | (3) >= 60 % of coins positive: {bool(r['share'] >= 0.6)} | (4) top-5 share <= 50 %: {bool(r['top5'] <= 0.5)} | (5) replicated on: {rep or 'none'}")
    else:
        print("\nPRIMARY (cost rule, KuCoin vs Binance): no trades -> not passed")


if __name__ == "__main__":
    main()
