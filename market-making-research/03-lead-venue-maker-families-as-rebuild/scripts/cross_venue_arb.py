#!/usr/bin/env python3
"""research5 A-1: is cross-venue arbitrage KuCoin <-> Binance possible on mid-cap USDT perps?  (offline feasibility)

Pre-registered in docs/research5/experiments.md (card A-1). Two structures on the same data:
  S2 maker on KuCoin / taker hedge on Binance: quote P = F (1 +- delta) with F = Binance mid x e^basis; when a real KuCoin
     taker order reaches P we are filled and buy / sell the same amount on Binance HEDGE_US later.
  S1 taker on both: after a Binance trade, if KuCoin's touch is off the Binance price by >= theta, take it and hedge.
Binance book: historical bookTicker is not published for 2026, so quotes are rebuilt from aggregated trades:
  mid = last trade price -/+ hs (a buyer-initiated trade printed at the ask), hs = typical half-spread of that contract-day.
Timing (measured 2026-10-02 on the colo host): Binance data reaches us after 1.5 ms, an order reaches either exchange
1.5 ms after we send it, KuCoin data reaches us after 0.3 ms. All times are exchange timestamps (the two exchange clocks
were within 0.4 ms of each other).
KuCoin fills use the validity rules of deep_quote_curve.py (live book, level swept, one fill per re-quote gap).

Added 2026-10-02 after the first run (v1), whose totals were dominated by broken contract-days (ONE: 96 % of the S1 fill $,
"locked" +50 bp against a basis that never came back):
  hedge price, two variants   "cons" (pre-registered): worse of the last Binance trade before the hedge time and the first
                              one within 1 s after it;  "last": only the last trade before it (optimistic). The truth lies
                              between them and cannot be pinned down without Binance book data.
  contract-day validity       excluded when under 90 % of KuCoin's real taker orders had a live book, or when the rolling
                              basis moved over a range (1st-99th percentile) of more than BASIS_RANGE_BP within the day -
                              two venues whose price ratio wanders that much are not the same instrument for our purpose
                              (wrong symbol match, or broken data).
Usage: python scripts/research5/cross_venue_arb.py          (Python314)
"""
import os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deep_quote_curve as D

sys.path.insert(0, os.path.join(D.ROOT, "scripts", "research3"))
BH = os.path.join(D.ROOT, "data", "research5", "binance_hist")
B_INFO_US = 1500          # Binance trade -> known to us
ORDER_US = 1500           # our order -> effective at an exchange
K_INFO_US = 300           # KuCoin data -> known to us
QUOTE_LAG_US = B_INFO_US + ORDER_US               # our resting KuCoin quote reflects Binance prices this old
HEDGE_US = K_INFO_US + ORDER_US + 700             # fill seen + order sent + exchange processing margin = 2.5 ms
BASIS_WIN_S, BASIS_MIN_S = 600, 60
D_GRID = (2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0, 20.0)
T_GRID = (7.0, 10.0, 15.0, 20.0, 30.0)
BASIS_RANGE_BP = 50.0
MIN_ALIVE = 0.9
K_REBATE, K_TAKER = 0.7, 1.8
B_TAKER = 5.0             # Binance USD-M futures OUR_FEE_TIER; 4.5 with the BNB discount


def binance_symbol(ku_sym):
    base = ku_sym[:-5]
    return {"PEPE": "1000PEPE"}.get(base, base) + "USDT"


def typical_half_spread(t_us, px, side, window_us=100_000):
    """Median half distance between consecutive trades of opposite direction no more than window_us apart (price units)."""
    opp = (side[1:] != side[:-1]) & (np.diff(t_us) <= window_us)
    d = np.abs(np.diff(px))[opp]
    d = d[d > 0]
    return float(np.median(d) / 2) if len(d) else 0.0


def trade_mid(px, side, hs):
    """Mid implied by a trade: a buyer-initiated trade (side +1) printed at the ask, a seller-initiated one at the bid."""
    return px - side * hs


def rolling_basis(log_ratio, win, min_n):
    """Median of the previous `win` per-second samples (excluding the current one); NaN until min_n samples exist."""
    return pd.Series(log_ratio).rolling(win, min_periods=min_n).median().shift(1).to_numpy()


def exec_price(t_b, mid_b, hs, t, take_side, horizon_us=1_000_000):
    """Price we get on Binance for a taker order arriving at t: mid +- hs from the last trade at or before t, or from the
    first trade within horizon_us after t if that is worse for us. take_side +1 = we buy, -1 = we sell."""
    j = np.searchsorted(t_b, t, side="right") - 1
    last = mid_b[np.clip(j, 0, None)] + take_side * hs
    jn = np.clip(j + 1, 0, len(t_b) - 1)
    nxt = mid_b[jn] + take_side * hs
    use_next = (t_b[jn] > t) & (t_b[jn] <= t + horizon_us) & (horizon_us > 0)
    worse = np.where(take_side > 0, np.maximum(last, nxt), np.minimum(last, nxt))
    out = np.where(use_next, worse, last)
    return np.where(j >= 0, out, np.nan)


def lock_bp(sgn, k_px, b_px_in_k):
    """Edge locked by a KuCoin fill at k_px hedged at the Binance price (already converted to KuCoin units), bp, before fees.
    sgn +1: we sold on KuCoin (a taker bought from us) and buy on Binance."""
    return sgn * (k_px - b_px_in_k) / k_px * 1e4


def load_binance(sym, day):
    f = os.path.join(BH, f"{binance_symbol(sym)}-aggTrades-{day[:4]}-{day[4:6]}-{day[6:]}.zip")
    t = pd.read_csv(f, usecols=["price", "transact_time", "is_buyer_maker"])
    side = np.where(t.is_buyer_maker.to_numpy(), -1.0, 1.0)
    t_us = t.transact_time.to_numpy().astype(np.int64) * 1000
    px = t.price.to_numpy().astype(float)
    hs = typical_half_spread(t_us, px, side)
    return t_us, trade_mid(px, side, hs), hs, side


def load_pair(sym, day, orders=True):
    """Everything of one contract-day: KuCoin book, real taker orders with prints, Binance mids, per-second basis."""
    import flow_anatomy as FA
    b = pd.read_parquet(os.path.join(D.EV, f"book_{sym}_{day}.parquet"), columns=["ts", "bb", "ba", "bq1", "aq1"])
    tick = float(FA.SPECS[sym]["tick"])
    qts = b.ts.to_numpy().astype(np.int64)
    bb, ba = b.bb.to_numpy().astype(float), b.ba.to_numpy().astype(float)
    good = ba > bb
    mid = (bb + ba) / 2.0
    t_b, mid_b, hs, side_b = load_binance(sym, day)
    g = np.arange(qts[0] // 1_000_000 * 1_000_000 + 1_000_000, qts[-1], 1_000_000, dtype=np.int64)
    jk = D.at_or_before(qts, g)
    mk = np.where(good[jk] & D.alive_at(qts, g, D.ALIVE_US), mid[jk] * tick, np.nan)
    jb = np.searchsorted(t_b, g, side="right") - 1
    mb = np.where((jb >= 0) & (g - t_b[np.clip(jb, 0, None)] < D.ALIVE_US), mid_b[np.clip(jb, 0, None)], np.nan)
    basis = rolling_basis(np.log(mk / mb), BASIS_WIN_S, BASIS_MIN_S)
    P = dict(sym=sym, day=day, tick=tick, qts=qts, bb=bb, ba=ba, bq=b.bq1.to_numpy().astype(float), aq=b.aq1.to_numpy().astype(float),
             mid=mid, good=good, t_b=t_b, mid_b=mid_b, hs=hs, g0=g[0], basis=basis, mk=mk, mb=mb, side_b=side_b)
    if orders:
        o, pr = D.load_orders(sym, day)
        P["o"], P["pr"] = o, pr
    return P


def basis_at(P, t):
    i = (t - P["g0"]) // 1_000_000
    ok = (i >= 0) & (i < len(P["basis"]))
    return np.where(ok, P["basis"][np.clip(i, 0, len(P["basis"]) - 1)], np.nan)


def binance_mid_at(P, t):
    j = np.searchsorted(P["t_b"], t, side="right") - 1
    fresh = (j >= 0) & (t - P["t_b"][np.clip(j, 0, None)] < D.ALIVE_US)
    return np.where(fresh, P["mid_b"][np.clip(j, 0, None)], np.nan)


def s2_rows(P):
    """Maker on KuCoin at delta from the Binance-implied fair value, taker hedge on Binance."""
    o, pr, tick = P["o"], P["pr"], P["tick"]
    ts, sgn = o["ts"], o["sgn"]
    eb = np.exp(basis_at(P, ts))
    fair_t = binance_mid_at(P, ts - QUOTE_LAG_US) * eb / tick                       # ticks, KuCoin units
    jq = D.at_or_before(P["qts"], ts - ORDER_US - K_INFO_US)                        # the KuCoin book our post-only order met
    hedge = exec_price(P["t_b"], P["mid_b"], P["hs"], ts + HEDGE_US, sgn) * eb / tick
    hedge_last = exec_price(P["t_b"], P["mid_b"], P["hs"], ts + HEDGE_US, sgn, horizon_us=0) * eb / tick
    j300 = D.at_or_before(P["qts"], ts + 300_000_000)
    mid_k300 = P["mid"][j300]
    mid_b300 = binance_mid_at(P, ts + 300_000_000) * eb / tick
    base_ok = o["ok"] & np.isfinite(fair_t) & np.isfinite(hedge)
    hour = (ts // 3_600_000_000) % 24
    rows = []
    for d_bp in D_GRID:
        q = D.quote_ticks(fair_t, sgn, d_bp)
        post_ok = np.where(sgn > 0, q > P["bb"][jq], q < P["ba"][jq])              # post-only: not at / through the opposite touch
        f = D.fill_usd(pr["oid"], pr["sgn"], pr["px"], pr["usd"], np.nan_to_num(q)[pr["oid"]], len(ts), D.CLIP)
        m = (f > 0) & base_ok & post_ok & D.swept(sgn, q, o["post_hi"], o["post_lo"])
        if not m.any():
            continue
        idx = np.where(m)[0]
        m[idx[~D.thin_requote(ts[idx], sgn[idx], D.REQUOTE_US)]] = False
        lock = lock_bp(sgn, q, hedge) + K_REBATE
        lock_last = lock_bp(sgn, q, hedge_last) + K_REBATE
        # both legs marked at their mids 300 s later: KuCoin leg (sold at q) plus Binance leg (bought at hedge)
        pair = sgn * (q - mid_k300) / q * 1e4 - sgn * (hedge - mid_b300) / hedge * 1e4 + K_REBATE
        v300 = o["valid300"] & np.isfinite(mid_b300)
        for hh in np.unique(hour[m]):
            k = m & (hour == hh)
            kv = k & v300
            rows.append(dict(sym=P["sym"], day=P["day"], hour=int(hh), kind="S2", grid=d_bp, n=int(k.sum()), usd=float(f[k].sum()),
                             s_lock=float((f[k] * lock[k]).sum()), s_last=float((f[k] * lock_last[k]).sum()),
                             s_pair=float((f[kv] * pair[kv]).sum()), u_pair=float(f[kv].sum())))
    return rows


def s1_rows(P):
    """Taker on KuCoin when its touch is off the Binance price, hedge on Binance."""
    tick = P["tick"]
    T = P["t_b"]
    eb = np.exp(basis_at(P, T))
    a_b = (P["mid_b"] + P["hs"]) * eb / tick            # what buying on Binance costs, KuCoin ticks
    b_b = (P["mid_b"] - P["hs"]) * eb / tick
    jd = D.at_or_before(P["qts"], T + B_INFO_US - K_INFO_US)
    alive = D.alive_at(P["qts"], T + B_INFO_US - K_INFO_US, D.ALIVE_US) & P["good"][jd] & np.isfinite(eb)
    je = D.at_or_before(P["qts"], T + B_INFO_US + ORDER_US)
    j300 = D.at_or_before(P["qts"], T + 300_000_000)
    v300 = (T + 300_000_000 <= P["qts"][-1]) & D.alive_at(P["qts"], T + 300_000_000, D.ALIVE_US)
    mid_b300 = binance_mid_at(P, T + 300_000_000) * eb / tick
    hour = (T // 3_600_000_000) % 24
    rows = []
    for side in (1.0, -1.0):                             # +1: sell KuCoin's bid, buy Binance;  -1: buy KuCoin's ask, sell Binance
        k_dec = P["bb"][jd] if side > 0 else P["ba"][jd]
        ref = a_b if side > 0 else b_b
        x = side * (k_dec - ref) / ref * 1e4
        k_exec = P["bb"][je] if side > 0 else P["ba"][je]
        size_usd = (P["bq"][je] if side > 0 else P["aq"][je]) * k_exec * tick
        still = (k_exec >= k_dec) if side > 0 else (k_exec <= k_dec)
        t_h = T + B_INFO_US + ORDER_US + K_INFO_US + ORDER_US
        hedge = exec_price(P["t_b"], P["mid_b"], P["hs"], t_h, np.full(len(T), side)) * eb / tick
        hedge_last = exec_price(P["t_b"], P["mid_b"], P["hs"], t_h, np.full(len(T), side), horizon_us=0) * eb / tick
        net = lock_bp(side, k_dec, hedge) - K_TAKER
        net_last = lock_bp(side, k_dec, hedge_last) - K_TAKER
        pair = side * (k_dec - P["mid"][j300]) / k_dec * 1e4 - side * (hedge - mid_b300) / hedge * 1e4 - K_TAKER
        for th in T_GRID:
            m = alive & (x >= th) & np.isfinite(hedge)
            idx = np.where(m)[0]
            if not len(idx):
                continue
            keep = D.thin_requote(T[idx], np.full(len(idx), side), 100_000)
            idx = idx[keep]
            hit = still[idx]
            f = np.minimum(D.CLIP, size_usd[idx]) * hit
            for hh in np.unique(hour[idx]):
                k = idx[hour[idx] == hh]
                fk = f[hour[idx] == hh]
                kv = v300[k] & np.isfinite(mid_b300[k])
                rows.append(dict(sym=P["sym"], day=P["day"], hour=int(hh), kind="S1", grid=th, n=int((fk > 0).sum()), tries=len(k), usd=float(fk.sum()),
                                 s_lock=float((fk * net[k]).sum()), s_last=float((fk * net_last[k]).sum()),
                                 s_pair=float((fk[kv] * pair[k][kv]).sum()), u_pair=float(fk[kv].sum())))
    return rows


def ci(df, col="s_lock", den="usd", n=2000, seed=11):
    g = df.groupby(["sym", "day", "hour"])[[col, den]].sum().to_numpy()
    if len(g) < 2 or g[:, 1].sum() <= 0:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        i = rng.integers(0, len(g), len(g))
        out.append(g[i, 0].sum() / max(g[i, 1].sum(), 1e-9))
    return np.percentile(out, [2.5, 97.5])


def table(df, kind, days, label, fee):
    d = df[(df.kind == kind) & df.day.isin(days)]
    exit_fee = (K_TAKER + fee) if kind == "S1" else 0.0
    print(f"\n{label} (days {', '.join(days)}; Binance taker fee {fee} bp)")
    print("    grid   fills   fill $/day   locked net bp (cons / last)   pair value 300 s" + (" (after exit takers)" if kind == "S1" else "") + "   profit $/day (cons)   contracts > 0")
    for gval, g in d.groupby("grid"):
        lk = g.s_lock.sum() / g.usd.sum() - fee if g.usd.sum() > 0 else np.nan
        ll = g.s_last.sum() / g.usd.sum() - fee if g.usd.sum() > 0 else np.nan
        pr = g.s_pair.sum() / g.u_pair.sum() - fee - exit_fee if g.u_pair.sum() > 0 else np.nan
        per = g.groupby("sym").apply(lambda x: x.s_lock.sum() / x.usd.sum() - fee if x.usd.sum() > 0 else np.nan, include_groups=False)
        print(f"  {gval:6.0f}  {g.n.sum():6d}  {g.usd.sum() / len(days):11,.0f}  {lk:12.2f} / {ll:6.2f}  {pr:17.2f}  {g.usd.sum() * lk / 1e4 / len(days):38.1f}   {int((per > 0).sum())}/{per.notna().sum()}")


def primary(df, kind, fee):
    d = df[df.kind == kind]
    tr = d[d.day.isin(D.TRAIN)]
    prof = tr.groupby("grid").apply(lambda x: (x.s_lock.sum() - fee * x.usd.sum()) / 1e4, include_groups=False)
    star = prof.idxmax()
    te = d[d.day.isin(D.TEST) & (d.grid == star)]
    lk = te.s_lock.sum() / te.usd.sum() - fee
    lo, hi = ci(te)
    exit_fee = (K_TAKER + fee) if kind == "S1" else 0.0
    pr = te.s_pair.sum() / te.u_pair.sum() - fee - exit_fee
    per = te.groupby("sym").apply(lambda x: x.s_lock.sum() / x.usd.sum() - fee if x.usd.sum() > 0 else np.nan, include_groups=False)
    byday = te.groupby("day").apply(lambda x: x.s_lock.sum() / x.usd.sum() - fee, include_groups=False).round(2).to_dict()
    print(f"\nPRIMARY {kind} (fee {fee}): training profit $ by grid {prof.round(1).to_dict()} -> {star:g} bp")
    print(f"   test: locked net {lk:+.2f} bp [{lo - fee:+.2f}, {hi - fee:+.2f}]; pair value 300 s {pr:+.2f} bp; contracts positive {int((per > 0).sum())}/{per.notna().sum()};"
          f" fill $/day {te.usd.sum() / len(D.TEST):,.0f}; profit $/day {te.usd.sum() * lk / 1e4 / len(D.TEST):,.1f}; by day {byday}")
    print(f"   pass lines: net > 0 and CI lower > 0: {bool(lk > 0 and lo - fee > 0)} | pair 300 s > 0: {bool(pr > 0)} | >= 60 % contracts positive: {bool((per > 0).sum() / max(per.notna().sum(), 1) >= 0.6)}")


def main():
    uni = pd.read_csv(os.path.join(D.ROOT, "data", "research5", "alt_usdt_universe.csv")).head(22).sym.tolist()
    rows, info = [], []
    for s in uni:
        for day in D.TRAIN + D.TEST:
            P = load_pair(s, day)
            fin = P["basis"][np.isfinite(P["basis"])]
            info.append(dict(sym=s, day=day, hs_bp=P["hs"] / np.nanmedian(P["mid_b"]) * 1e4, trades=len(P["t_b"]), alive=float(P["o"]["ok"].mean()),
                             basis_bp=float(np.median(fin) * 1e4) if len(fin) else np.nan,
                             basis_range=float((np.percentile(fin, 99) - np.percentile(fin, 1)) * 1e4) if len(fin) > 100 else np.nan))
            rows += s2_rows(P) + s1_rows(P)
            del P
        print(s, "done", flush=True)
    df = pd.DataFrame(rows)
    df.to_parquet(os.path.join(D.ROOT, "data", "research5", "cross_venue_arb.parquet"))
    I = pd.DataFrame(info)
    I["valid"] = (I.alive >= MIN_ALIVE) & (I.basis_range <= BASIS_RANGE_BP)
    I.to_csv(os.path.join(D.ROOT, "data", "research5", "cross_venue_contract_days.csv"), index=False)
    bad = I[~I.valid]
    print("\nBinance side: typical half-spread bp (median over contract-days)", round(I.hs_bp.median(), 2), "| trades per day median", int(I.trades.median()),
          "| basis range within a day, median bp", round(I.basis_range.median(), 1))
    print("excluded contract-days (live book < 90 % or basis range > 50 bp):", len(bad), "of", len(I), "->",
          [(r.sym[:-5], r.day[-4:], round(r.alive, 2), round(r.basis_range, 0)) for r in bad.itertuples()])
    df = df.merge(I[["sym", "day", "valid"]], on=["sym", "day"])
    df = df[df.valid]
    print("contracts left:", df.sym.nunique(), "| contract-days left:", int(I.valid.sum()))
    for kind, name in (("S2", "S2 maker KuCoin / taker Binance, by quote distance delta bp"), ("S1", "S1 taker both, by entry threshold theta bp")):
        table(df, kind, D.TRAIN, "TRAIN " + name, B_TAKER)
        table(df, kind, D.TEST, "TEST " + name, B_TAKER)
        primary(df, kind, B_TAKER)
        for fee in (4.5, 2.0):
            table(df, kind, D.TEST, "TEST " + name, fee)


if __name__ == "__main__":
    main()
