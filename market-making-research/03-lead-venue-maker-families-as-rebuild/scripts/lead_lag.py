#!/usr/bin/env python3
"""research5 L-3: are KuCoin's real takers picking off quotes that are stale relative to Binance, and by how long?

Inputs:
  data/research5/ku_orders_<day>.parquet     one row per KuCoin taker order (kucoin_trades.py)
  data/research5/binance_agg/<SYM>_*.csv.gz  Binance aggTrades: T_ms,price,qty,buyer_is_maker (fetch_binance_aggtrades.py)
Definitions (docs/research5/experiments.md, L-3):
  P_B(t)    last Binance trade price at or before t
  b_t       median of ln(KuCoin print / P_B) over the previous 600 s of KuCoin taker orders (strictly earlier, >= 20 obs)
  fair_L(t) P_B(t - L) * exp(b_t)
  gap_L     taker_sign * (fair_L - px) / px in bp   (> 0: the taker traded through the Binance-implied fair value)
  m_h       taker_sign * (px - fair_0(t + h)) / px in bp, basis frozen at b_t  (maker gross vs the Binance-implied fair)
  k_h       taker_sign * (px - KuCoin mid at the first 5 s BBO sample at or after t + h) / px in bp  (maker gross vs KuCoin's
            own later mid; added after the first run because m_h shares the basis estimate with gap_L, which correlates the two
            mechanically - k_h does not use the basis and is the outcome to trust)
Output: data/research5/lead_lag_rows.parquet (one row per real KuCoin taker order) and printed tables.
Usage: python scripts/research5/lead_lag.py 20261001
"""
import glob, gzip, json, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D5 =os.path.join(ROOT, "data", "research5")
REBATE = OUR_FEE
LAGS_MS = (0, 5, 20, 100, 500, 2000, 10000)
HORIZONS_S = (5, 60, 300)
BASIS_WINDOW_MS, BASIS_MIN_N = 600_000, 20
GAP_BINS = [-np.inf, -2.0, 0.0, 2.0, 5.0, np.inf]


def last_price_at(T, P, t):
    """Price of the last trade with time <= t (NaN before the first trade). T ascending; t scalar or array."""
    i = np.searchsorted(T, t, side="right") - 1
    return np.where(i >= 0, P[np.clip(i, 0, len(P) - 1)], np.nan)


def rolling_basis(t_obs, x_obs, t_query, window_ms=BASIS_WINDOW_MS, min_n=BASIS_MIN_N):
    """Median of x_obs over observations with t in [t_query - window, t_query); NaN when fewer than min_n."""
    out = np.full(len(t_query), np.nan)
    lo = np.searchsorted(t_obs, t_query - window_ms, side="left")
    hi = np.searchsorted(t_obs, t_query, side="left")
    for k in range(len(t_query)):
        if hi[k] - lo[k] >= min_n:
            out[k] = np.median(x_obs[lo[k]:hi[k]])
    return out


def next_value_at(T, V, t, tol_ms=10_000):
    """Value of the first sample with time >= t, NaN if none arrives within tol_ms. T ascending."""
    i = np.searchsorted(T, t, side="left")
    j = np.clip(i, 0, len(T) - 1)
    ok = (i < len(T)) & (T[j] - t <= tol_ms)
    return np.where(ok, V[j], np.nan)


def load_kucoin_mid(day):
    """Our 5 s REST best-bid/ask recorder -> {sym: (recv_ms ascending, mid)}; crossed or empty books dropped."""
    rows = []
    try:  # the recorder keeps today's file open, so the gzip stream has no end marker yet: read until it runs out
        with gzip.open(os.path.join(ROOT, "data", "research4", "bbo", f"{day}.csv.gz"), "rt") as fh:
            for line in fh:
                p = line.split(",")
                if len(p) >= 6:
                    rows.append((p[0], p[1], p[3], p[5]))
    except EOFError:
        pass
    b = pd.DataFrame(rows, columns=["recv_ms", "sym", "bid", "ask"])
    for c in ("recv_ms", "bid", "ask"):
        b[c] = pd.to_numeric(b[c], errors="coerce")
    b = b.dropna()
    b = b[(b.bid > 0) & (b.ask > b.bid)]
    b["mid"] = (b.bid + b.ask) / 2
    return {s: (x.recv_ms.to_numpy(np.int64), x.mid.to_numpy(float)) for s, x in b.sort_values("recv_ms").groupby("sym")}


def gap_bp(sgn, fair, px):
    """Taker's edge against the reference: + means it bought below / sold above `fair`."""
    return sgn * (fair - px) / px * 1e4


def maker_markout_bp(sgn, px, fair_later):
    """Gross markout of the maker who was hit at px by a taker of sign sgn, against a later fair value."""
    return sgn * (px - fair_later) / px * 1e4


def load_binance(sym):
    fs = [f for f in sorted(glob.glob(os.path.join(D5, "binance_agg", f"{sym}_*.csv.gz"))) if os.path.exists(f + ".done")]  # finished downloads only
    if not fs:
        return None
    b = pd.concat([pd.read_csv(f, header=None, names=["T", "p", "q", "m"]) for f in fs]).drop_duplicates().sort_values("T")
    return b["T"].to_numpy(np.int64), b["p"].to_numpy(float)


def rows_for(ku, T, P, kmid=None):
    """All KuCoin taker orders of one contract (pairs included, sorted by time) -> rows for the real ones.
    kmid = (ts_ms, mid) samples of KuCoin's own book for the k_h outcomes (NaN columns when absent)."""
    t = (ku.ts.to_numpy(np.int64) // 1_000_000)
    px = ku.px_first.to_numpy(float)
    pb = last_price_at(T, P, t)
    ok = np.isfinite(pb)
    basis = rolling_basis(t[ok], np.log(px[ok] / pb[ok]), t)
    real = (~ku.pair.to_numpy(bool)) & np.isfinite(basis) & (t >= T[0]) & (t + HORIZONS_S[-1] * 1000 <= T[-1])
    r = pd.DataFrame({"sym": ku.sym.to_numpy()[real], "t": t[real], "sgn": ku.sgn.to_numpy()[real], "px": px[real],
                      "usd": ku.usd.to_numpy()[real], "basis": basis[real]})
    mult = np.exp(r.basis.to_numpy())
    for L in LAGS_MS:
        r[f"gap_{L}"] = gap_bp(r.sgn, last_price_at(T, P, r.t.to_numpy() - L) * mult, r.px)
    for h in HORIZONS_S:
        r[f"m_{h}"] = maker_markout_bp(r.sgn, r.px, last_price_at(T, P, r.t.to_numpy() + h * 1000) * mult)
    for h in HORIZONS_S:
        r[f"k_{h}"] = maker_markout_bp(r.sgn, r.px, next_value_at(*kmid, r.t.to_numpy() + h * 1000)) if kmid is not None else np.nan
    r["f"] = np.minimum(1000.0, r.usd)
    return r


def wmean(x, col):
    w = x["f"].to_numpy()
    return float((x[col].to_numpy() * w).sum() / w.sum()) if w.sum() > 0 else np.nan


def block_ci(x, col, n=2000, seed=5):
    """95% CI of the f-weighted mean of col, resampling symbols."""
    g = x.groupby("sym").apply(lambda b: pd.Series({"s": (b[col] * b["f"]).sum(), "w": b["f"].sum()}), include_groups=False)
    if len(g) < 5:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n, len(g)))
    m = g["s"].to_numpy()[idx].sum(1) / g["w"].to_numpy()[idx].sum(1)
    return tuple(np.percentile(m, [2.5, 97.5]).round(2))


def finite(x, col):
    return x[np.isfinite(x[col])]


def gap_table(r, lag=20, out="k"):
    """Maker net by bucket of the taker's edge; out = 'k' (vs KuCoin's later mid) or 'm' (vs the Binance-implied fair)."""
    r = finite(r, f"{out}_300").copy()
    r["bucket"] = pd.cut(r[f"gap_{lag}"], GAP_BINS)
    tot = r.f.sum()
    rows = []
    for b, x in r.groupby("bucket", observed=True):
        lo, hi = block_ci(x, f"{out}_300")
        rows.append(dict(bucket=str(b), n=len(x), syms=x.sym.nunique(), share=x.f.sum() / tot, net5=wmean(finite(x, f"{out}_5"), f"{out}_5") + REBATE,
                         net60=wmean(finite(x, f"{out}_60"), f"{out}_60") + REBATE, net300=wmean(x, f"{out}_300") + REBATE, lo300=lo + REBATE, hi300=hi + REBATE))
    return pd.DataFrame(rows)


def split_rows(r, lag, hours, thr=0.0):
    """Pre-registered P2 as a two-way split: gap_lag <= thr (keep) vs > thr (avoid); outcome k_300."""
    r = finite(r, "k_300")
    rows = []
    for name, x in ((f"keep gap<={thr:g}", r[r[f"gap_{lag}"] <= thr]), (f"avoid gap>{thr:g}", r[r[f"gap_{lag}"] > thr])):
        lo, hi = block_ci(x, "k_300")
        rows.append(dict(lag_ms=lag, part=name, n=len(x), share=x.f.sum() / r.f.sum(), usd_per_day=x.f.sum() / hours * 24,
                         net300=wmean(x, "k_300") + REBATE, lo300=lo + REBATE, hi300=hi + REBATE))
    return rows


def timing_table(r, thr=2.0):
    """Among orders that traded through the Binance-implied fair by > thr bp at L=0: share still > thr at each lag L."""
    a = r[r["gap_0"] > thr]
    return pd.DataFrame([dict(lag_ms=L, share_still_stale=float(a.f[a[f"gap_{L}"] > thr].sum() / a.f.sum()) if len(a) else np.nan) for L in LAGS_MS]), len(a), float(a.f.sum() / r.f.sum())


def main():
    day = sys.argv[1]
    spec = {x["sym"]: x for x in json.load(open(os.path.join(ROOT, "data", "research4", "tradfi_contracts_20261001.json"), encoding="utf-8"))}
    ku = pd.read_parquet(os.path.join(D5, f"ku_orders_{day}.parquet"))
    kmid = load_kucoin_mid(day)
    parts = []
    for sym, k in ku.groupby("sym"):
        b = load_binance(sym[:-1])
        if b is None or len(b[0]) < 100:
            continue
        parts.append(rows_for(k.sort_values("ts"), *b, kmid=kmid.get(sym)))
    r = pd.concat(parts, ignore_index=True)
    r["grp"] = r.sym.map(lambda s: "PREIPO" if spec[s]["stage"] == "PRE_MARKET" else ("METAL_COMMOD" if spec[s]["cls"] != "STOCK" else ("US" if spec[s]["sub"] == "US.STOCK" else "ASIA")))
    r.to_parquet(os.path.join(D5, "lead_lag_rows.parquet"))
    pd.set_option("display.width", 220)
    hours = (r.t.max() - r.t.min()) / 3.6e6
    rk = finite(r, "k_300")
    print(f"{day}: {len(r)} real taker orders, {r.sym.nunique()} contracts, {hours:.1f} h, f-weighted ${r.f.sum():,.0f}")
    print(f"all-flow maker net vs KuCoin later mid:      5s {wmean(finite(rk, 'k_5'), 'k_5') + REBATE:+.2f}  60s {wmean(finite(rk, 'k_60'), 'k_60') + REBATE:+.2f}"
          f"  300s {wmean(rk, 'k_300') + REBATE:+.2f} {block_ci(rk, 'k_300')}")
    print(f"all-flow maker net vs Binance-implied fair:  5s {wmean(r, 'm_5') + REBATE:+.2f}  60s {wmean(r, 'm_60') + REBATE:+.2f}  300s {wmean(r, 'm_300') + REBATE:+.2f} {block_ci(r, 'm_300')}")
    for lag in (0, 20, 100, 2000):
        print(f"\n== maker net vs KuCoin later mid (bp, incl. {REBATE} rebate) by the taker's edge against the Binance-implied fair, reference lag {lag} ms")
        print(gap_table(r, lag, "k").round(2).to_string(index=False))
    print("\n== same, outcome vs the Binance-implied fair (secondary: it shares the basis estimate with the sorting variable), lag 20 ms")
    print(gap_table(r, 20, "m").round(2).to_string(index=False))
    print("\n== P2: keep / avoid split by reference lag, outcome vs KuCoin later mid")
    print(pd.DataFrame([x for lag in LAGS_MS for x in split_rows(r, lag, hours)]).round(2).to_string(index=False))
    tt, n, sh = timing_table(r)
    print(f"\n== timing: orders with gap_0 > 2 bp (n={n}, {sh:.1%} of real flow): share whose gap is still > 2 bp when the Binance price is taken L ms earlier")
    print(tt.round(3).to_string(index=False))
    print("\n== by group, reference lag 20 ms")
    for g, x in r.groupby("grp"):
        print(f"-- {g}: {len(x)} orders, {x.sym.nunique()} contracts, all-flow net300 vs KuCoin mid {wmean(finite(x, 'k_300'), 'k_300') + REBATE:+.2f}")
        print(gap_table(x, 20, "k").round(2).to_string(index=False))


if __name__ == "__main__":
    main()
