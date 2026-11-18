#!/usr/bin/env python3
"""research5 A-2 (XV-INV): cross-venue inventory arbitrage KuCoin <-> Binance with the entry bound of
Hautsch, Scheuch, Voigt (Review of Finance 2024). Strategy file: docs/research5/strategy_xv_inventory_arb.md;
pre-registration: docs/research5/experiments.md, card A-2.

Paper -> here
  arbitrage bound (eq. 12 / 29)  delta = 1/2 sigma sqrt(g m1 + sqrt(g^2 m1^2 + 2 g (g+1)(g+2) m2)),  m1 = E[tau], m2 = V[tau] + E[tau]^2
  tau (settlement latency)       time until the cross-venue deviation is back at its slow basis (the pair can be closed)   [our transposition]
  sigma                          volatility of that deviation, bp per sqrt(s), one-sided exponential kernel (paper: one-sided Gaussian kernel)
  latency model (eq. 26-28)      Gamma duration regression, log link, covariates 1, ln|x|, ln sigma; fitted on the training days only
  entry (eq. 16)                 executable difference - costs of the four taker legs and of crossing the spreads at exit >= delta
Everything else (Binance quotes rebuilt from trades, slow basis, timing, validity of contract-days) is as in cross_venue_arb.py.
A-3 (--a3): the paper's bound read literally (tau = the 1.8 ms between our two fills) on top of the full round-trip cost,
and entries only when the last Binance print was on the side we have to trade (its price is then a real quote, not an inferred one).
Usage: python scripts/research5/xv_inventory_arb.py [--a3]   (Python314; needs scipy)
"""
import argparse, os, sys
import numpy as np, pandas as pd
from scipy.optimize import brentq
from scipy.special import digamma

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cross_venue_arb as X
import deep_quote_curve as D

GAMMA = 2.0                       # the paper's value (p. 1367)
SIG_TAU_S = 600.0
T_MAX_S = 1800
X_MIN_BP = 5.0                    # the duration model is fitted on deviations of at least this size
SAMPLE_STEP_S = 5
MAX_OPEN = 3
FEES_RT = 2 * X.K_TAKER + 2 * X.B_TAKER          # four taker legs
RULES = (("bound", 2.0), ("bound", 0.5), ("bound", 8.0), ("fixed", 15.0), ("fixed", 20.0), ("fixed", 30.0))
EXEC_M1_S = (X.K_INFO_US + X.ORDER_US) / 1e6      # KuCoin fill report + order to Binance: the time between our two fills
EXEC_SD_S = 0.0018                                # jitter: (p95 - p50) / 1.645 of the slowest symbol in the colo probe of 10-02
RULES_A3 = (("exec", 0.0), ("exec", 5.0), ("exec", 10.0), ("fixed", 15.0), ("fixed", 20.0), ("fixed", 30.0))


# ------------------------------------------------------------------ paper formulas
def arbitrage_bound(sigma, m1, m2, gamma):
    """Minimum price difference that compensates a CRRA(gamma) arbitrageur for holding the position for a random time with
    mean m1 and second moment m2 while the price moves with volatility sigma per sqrt(time unit) (paper eq. 12 / 29)."""
    g = gamma
    return 0.5 * sigma * np.sqrt(g * m1 + np.sqrt(g * g * m1 * m1 + 2 * g * (g + 1) * (g + 2) * m2))


def gamma_fit(Xm, y, iters=50):
    """Gamma regression with log link: mean mu = exp(X phi), variance mu^2 / alpha (paper eq. 26-28 with phi's intercept
    absorbing ln alpha). Returns (phi, alpha). IRLS for phi; alpha by maximum likelihood given the fitted means."""
    phi = np.zeros(Xm.shape[1])
    phi[0] = np.log(y.mean())
    for _ in range(iters):
        mu = np.exp(Xm @ phi)
        z = Xm @ phi + (y - mu) / mu
        new = np.linalg.lstsq(Xm, z, rcond=None)[0]
        if np.max(np.abs(new - phi)) < 1e-10:
            phi = new
            break
        phi = new
    mu = np.exp(Xm @ phi)
    c = float(np.mean(y / mu - np.log(y / mu) - 1.0))                    # ln(alpha) - digamma(alpha) = c at the ML shape
    alpha = brentq(lambda a: np.log(a) - digamma(a) - c, 1e-4, 1e6) if c > 1e-9 else 1e6
    return phi, float(alpha)


def gamma_moments(phi, alpha, Xm):
    """(E[tau], V[tau]) predicted for covariate rows Xm."""
    mu = np.exp(Xm @ phi)
    return mu, mu * mu / alpha


# ------------------------------------------------------------------ series helpers
def ew_sigma(absdx, tau_s):
    """One-sided exponentially weighted sqrt(pi/2) E|dx| per second; the value at index i uses changes up to i-1. NaN changes
    are skipped (the estimate is carried)."""
    a = 1.0 - np.exp(-1.0 / tau_s)
    out = np.full(len(absdx), np.nan)
    v = np.nan
    for i, d in enumerate(absdx):
        out[i] = v
        if d == d:
            v = d if v != v else v + a * (d - v)
    return out * np.sqrt(np.pi / 2)


def next_reversion(x):
    """For every index i: smallest j > i with x[j] <= 0 (down[i]) and smallest j > i with x[j] >= 0 (up[i]); len(x) if none.
    NaN never counts as a reversion."""
    n = len(x)
    down, up = np.full(n, n), np.full(n, n)
    nd = nu = n
    for i in range(n - 1, -1, -1):
        down[i], up[i] = nd, nu
        if x[i] <= 0:
            nd = i
        if x[i] >= 0:
            nu = i
    return down, up


def per_second(P):
    """Deviation x (bp) of the KuCoin / Binance mid ratio from the slow basis, and its volatility, on the 1 s grid."""
    x = (np.log(P["mk"] / P["mb"]) - P["basis"]) * 1e4
    sig = ew_sigma(np.abs(np.diff(x, prepend=np.nan)), SIG_TAU_S)
    return x, sig


def duration_sample(x, sig):
    """Training rows for the duration model: every SAMPLE_STEP_S seconds with |x| >= X_MIN_BP; tau = seconds until x is back
    at zero from that side, censored at T_MAX_S. Returns (ln|x|, ln sigma, tau)."""
    down, up = next_reversion(x)
    idx = np.arange(0, len(x) - T_MAX_S, SAMPLE_STEP_S)
    idx = idx[np.isfinite(x[idx]) & (np.abs(x[idx]) >= X_MIN_BP) & np.isfinite(sig[idx]) & (sig[idx] > 0)]
    nxt = np.where(x[idx] > 0, down[idx], up[idx])
    tau = np.minimum(nxt - idx, T_MAX_S).astype(float)
    return np.log(np.abs(x[idx])), np.log(sig[idx]), tau


# ------------------------------------------------------------------ simulation
def exec_bound(sigma, gamma=GAMMA):
    """The paper's bound with tau = the delay between our two fills (mean EXEC_M1_S, standard deviation EXEC_SD_S)."""
    return arbitrage_bound(sigma, EXEC_M1_S, EXEC_SD_S ** 2 + EXEC_M1_S ** 2, gamma)


def candidates(P, x, sig, model, confirmed=False):
    """All decision instants (one per Binance trade and side) with the quantities every rule needs.
    confirmed: only Binance prints whose aggressor side is the side we would trade there (we sell KuCoin, side +1, and buy on
    Binance -> the print was a buy at the ask), so the Binance price we compare with is a traded quote."""
    tick, T = P["tick"], P["t_b"]
    eb = np.exp(X.basis_at(P, T))
    sec = np.clip((T - P["g0"]) // 1_000_000, 0, len(x) - 1)
    sig_t = sig[sec]
    jd = D.at_or_before(P["qts"], T + X.B_INFO_US - X.K_INFO_US)
    alive = D.alive_at(P["qts"], T + X.B_INFO_US - X.K_INFO_US, D.ALIVE_US) & P["good"][jd] & np.isfinite(eb) & np.isfinite(sig_t) & (sig_t > 0)
    je = D.at_or_before(P["qts"], T + X.B_INFO_US + X.ORDER_US)
    hs_k = (P["ba"][jd] - P["bb"][jd]) / 2 / P["mid"][jd] * 1e4
    hs_b = P["hs"] / P["mid_b"] * 1e4
    x_mid = (P["mid"][jd] * tick / (P["mid_b"] * eb) - 1.0) * 1e4
    out = []
    for side in (1.0, -1.0):
        ref = (P["mid_b"] + side * P["hs"]) * eb / tick
        k_dec = P["bb"][jd] if side > 0 else P["ba"][jd]
        d = side * (k_dec - ref) / ref * 1e4
        k_exec = P["bb"][je] if side > 0 else P["ba"][je]
        still = (k_exec >= k_dec) if side > 0 else (k_exec <= k_dec)
        size = (P["bq"][je] if side > 0 else P["aq"][je]) * k_exec * tick
        m = alive & (d >= 10.0)                                    # nothing below 10 bp can clear OUR_FEE of fees: prefilter
        if confirmed:
            m &= P["side_b"] == side
        i = np.where(m)[0]
        if not len(i):
            continue
        Xm = np.column_stack([np.ones(len(i)), np.log(np.maximum(np.abs(x_mid[i]), X_MIN_BP)), np.log(sig_t[i])])
        m1, v = gamma_moments(model[0], model[1], Xm)
        t_h = T[i] + X.B_INFO_US + X.ORDER_US + X.K_INFO_US + X.ORDER_US
        h_in = X.exec_price(P["t_b"], P["mid_b"], P["hs"], t_h, np.full(len(i), side))
        out.append(pd.DataFrame(dict(T=T[i], side=side, d=d[i], sig=sig_t[i], m1=m1, m2=v + m1 * m1, c_out=FEES_RT / 2 + hs_k[i] + hs_b[i],
                                     still=still[i], size=size[i], k_in=k_dec[i] * tick, h_in=h_in, sec=sec[i], eb=eb[i])))
    return pd.concat(out).sort_values("T").reset_index(drop=True) if out else pd.DataFrame()


def threshold(c, kind, value):
    """Entry threshold in bp for each candidate: all four taker legs, the exit spreads, plus the paper's bound or a constant."""
    if kind == "fixed":
        return np.full(len(c), value)
    if kind == "exec":                                             # full round-trip cost + bound at our execution delay + margin
        return FEES_RT / 2 + c.c_out.to_numpy() + exec_bound(c.sig.to_numpy()) + value
    return FEES_RT / 2 + c.c_out.to_numpy() + arbitrage_bound(c.sig.to_numpy(), c.m1.to_numpy(), c.m2.to_numpy(), value)


def simulate(P, x, c, theta):
    """Run one rule over the candidates of a contract-day. Returns one row per filled entry."""
    if not len(c):
        return []
    tick = P["tick"]
    down, up = next_reversion(x)
    n_sec = len(x)
    rows, last, open_until = [], {1.0: -10**18, -1.0: -10**18}, {1.0: [], -1.0: []}
    for r, th in zip(c.itertuples(), theta):
        if r.d < th or r.T - last[r.side] < 100_000:
            continue
        last[r.side] = r.T
        if r.sec + T_MAX_S + 2 >= n_sec:                           # cannot be evaluated before the data ends
            continue
        op = [t for t in open_until[r.side] if t > r.T]
        open_until[r.side] = op
        if len(op) >= MAX_OPEN or not r.still or not np.isfinite(r.h_in):
            continue
        usd = min(D.CLIP, r.size)
        if usd <= 0:
            continue
        s0 = int(r.sec) + 1
        # we sold KuCoin when it was rich (side +1): the mid deviation is positive and has to come back down to zero
        s1 = int(down[s0] if r.side > 0 else up[s0])
        timeout = s1 - s0 > T_MAX_S or s1 >= n_sec
        s1 = min(s1, s0 + T_MAX_S)
        t_exit = P["g0"] + s1 * 1_000_000 + X.B_INFO_US + X.ORDER_US
        je = D.at_or_before(P["qts"], np.array([t_exit]))[0]
        k_out = (P["ba"][je] if r.side > 0 else P["bb"][je]) * tick
        h_out = X.exec_price(P["t_b"], P["mid_b"], P["hs"], np.array([t_exit]), np.array([-r.side]))[0]
        if not (np.isfinite(k_out) and np.isfinite(h_out) and P["good"][je]):
            continue
        k_leg = r.side * (r.k_in - k_out) / r.k_in * 1e4
        b_leg = r.side * (h_out - r.h_in) / r.h_in * 1e4
        # attribution (all relative to the slow basis at entry): premium actually locked at entry, premium paid to close
        lock_in = r.side * (r.k_in / (r.h_in * r.eb) - 1.0) * 1e4
        exit_cost = r.side * (k_out / (h_out * r.eb) - 1.0) * 1e4
        sp_out = (P["ba"][je] - P["bb"][je]) / 2 / P["mid"][je] * 1e4 + P["hs"] / h_out * 1e4
        open_until[r.side].append(t_exit)
        rows.append(dict(sym=P["sym"], day=P["day"], hour=int((r.T // 3_600_000_000) % 24), T=r.T, side=r.side, usd=usd, d=r.d, theta=th, sig=r.sig, m1=r.m1,
                         hold_s=s1 - s0, timeout=bool(timeout), k_leg=k_leg, b_leg=b_leg, pnl=k_leg + b_leg - FEES_RT,
                         lock_in=lock_in, slip_in=r.d - lock_in, exit_cost=exit_cost, x_exit=r.side * x[s1], sp_out=sp_out))
    return rows


# ------------------------------------------------------------------ reporting
def boot(df, n=2000, seed=5):
    g = df.assign(w=df.usd * df.pnl).groupby(["sym", "day", "hour"])[["w", "usd"]].sum().to_numpy()
    if len(g) < 2:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    out = [g[i, 0].sum() / g[i, 1].sum() for i in (rng.integers(0, len(g), len(g)) for _ in range(n))]
    return np.percentile(out, [2.5, 97.5])


def report(tr, label, days):
    d = tr[tr.day.isin(days)]
    if not len(d):
        print(f"  {label:12s} no entries")
        return None
    w = (d.usd * d.pnl).sum() / d.usd.sum()
    lo, hi = boot(d)
    per = d.assign(w=d.usd * d.pnl).groupby("sym")[["w", "usd"]].sum()
    per = per.w / per.usd
    byday = d.assign(w=d.usd * d.pnl).groupby("day")[["w", "usd"]].sum()
    byday = (byday.w / byday.usd).round(2).to_dict()
    print(f"  {label:12s} entries {len(d):5d}  $/day {d.usd.sum() / len(days):9,.0f}  pnl {w:+7.2f} bp [{lo:+.2f}, {hi:+.2f}]  $/day {(d.usd * d.pnl).sum() / 1e4 / len(days):7.1f}"
          f"  contracts>0 {int((per > 0).sum())}/{len(per)}  by day {byday}  hold p50 {d.hold_s.median():.0f}s  timeout {d.timeout.mean():.0%}  avg $ {d.usd.mean():.0f}")
    a = lambda col: float((d[col] * d.usd).sum() / d.usd.sum())
    print(f"  {'':12s} attribution bp: seen at decision {a('d'):+.1f} - lost before the hedge filled {a('slip_in'):.1f} = locked {a('lock_in'):+.1f};"
          f" paid to close {a('exit_cost'):+.1f} (deviation left {a('x_exit'):+.1f}, two half-spreads {a('sp_out'):.1f}, rest {a('exit_cost') - a('x_exit') - a('sp_out'):+.1f});"
          f" fees {FEES_RT:.1f}")
    return dict(pnl=w, lo=lo, share=(per > 0).mean(), byday=byday)


def main_a3():
    """A-3: confirmed entries, cost + execution-delay bound. No duration model is needed."""
    I = pd.read_csv(os.path.join(D.ROOT, "data", "research5", "cross_venue_contract_days.csv"), dtype={"day": str})
    I = I[I.valid]
    model = (np.zeros(3), 1.0)
    trades = {f"{k}{v:g}": [] for k, v in RULES_A3}
    n_all = n_conf = 0
    for r in I.itertuples():
        P = X.load_pair(r.sym, r.day, orders=False)
        x, sig = per_second(P)
        n_all += len(candidates(P, x, sig, model))
        c = candidates(P, x, sig, model, confirmed=True)
        n_conf += len(c)
        if len(c):
            for kind, val in RULES_A3:
                trades[f"{kind}{val:g}"] += simulate(P, x, c, threshold(c, kind, val))
        del P
    print(f"A-3  decision instants with d >= 10 bp: {n_all} in A-2, {n_conf} with the Binance print on our side ({n_conf / max(n_all, 1):.0%})")
    print(f"     bound at the execution delay: {exec_bound(1.0):.4f} x sigma")
    res = {}
    for name, days in (("TRAIN", D.TRAIN), ("DEVELOPMENT TEST", D.TEST)):
        print(f"\nA-3  {name}: pnl per $ after four taker legs and exit spreads; confirmed entries")
        for key, rows in trades.items():
            tr = pd.DataFrame(rows)
            if len(tr):
                tr.to_parquet(os.path.join(D.ROOT, "data", "research5", f"xv_inv_a3_trades_{key}.parquet"))
                res[(name, key)] = report(tr, key, days)
                report(tr[tr.sym != "AKEUSDTM"], "  without AKE", days)
            else:
                print(f"  {key:12s} no entries")
    a, b = res.get(("TRAIN", "exec0")), res.get(("DEVELOPMENT TEST", "exec0"))
    if a and b:
        print(f"\nPRIMARY (cost + execution-delay bound): train pnl > 0: {bool(a['pnl'] > 0)} | test pnl > 0 and CI lower > 0: {bool(b['pnl'] > 0 and b['lo'] > 0)}"
              f" | >= 60 % contracts positive: {bool(b['share'] >= 0.6)} | both test days positive: {all(v > 0 for v in b['byday'].values()) and len(b['byday']) == 2}")
    else:
        print("\nPRIMARY (cost + execution-delay bound): no entries on train or on test -> not passed")


def main():
    I = pd.read_csv(os.path.join(D.ROOT, "data", "research5", "cross_venue_contract_days.csv"), dtype={"day": str})
    I = I[I.valid]
    hourly, samp = [], {"train": [], "test": []}
    for r in I.itertuples():                                           # pass 1: per-second series only (the books are not kept in memory)
        P = X.load_pair(r.sym, r.day, orders=False)
        x, sig = per_second(P)
        lx, ls, tau = duration_sample(x, sig)
        samp["train" if r.day in D.TRAIN else "test"].append((lx, ls, tau))
        h = pd.DataFrame(dict(hour=(P["g0"] // 1_000_000 + np.arange(len(x))) // 3600 % 24, ax=np.abs(x), sig=sig,
                              sb=np.abs(np.diff(np.log(P["mb"]), prepend=np.nan)) * 1e4))
        g = h.groupby("hour").agg(ax=("ax", "mean"), sig=("sig", "mean"), sb=("sb", "mean"), n=("ax", "count")).reset_index()
        hourly.append(g[g.n > 1800].assign(sym=r.sym, day=r.day))
        del P
    # ---- A-2a: are deviations larger in volatile hours? (paper Table 5 direction)
    H = pd.concat(hourly, ignore_index=True)
    H["sb"] *= np.sqrt(np.pi / 2)
    Z = H[["ax", "sig", "sb"]].apply(np.log)
    Zd = Z - Z.groupby(H.sym).transform("mean")                          # contract fixed effects
    def ols(cols):
        A = Zd[cols].to_numpy()
        return np.linalg.lstsq(A, Zd.ax.to_numpy(), rcond=None)[0]
    keys = list(H.groupby(["sym", "day"]).groups.values())
    rng = np.random.default_rng(3)
    print("\nA-2a  ln(hourly mean |deviation|) on ln(volatility), contract fixed effects;", len(H), "contract-hours")
    for cols in (["sig"], ["sb"], ["sig", "sb"]):
        b = ols(cols)
        bs = []
        for _ in range(500):
            pick = np.concatenate([keys[i] for i in rng.integers(0, len(keys), len(keys))])
            A = Zd.loc[pick, cols].to_numpy()
            bs.append(np.linalg.lstsq(A, Zd.loc[pick, "ax"].to_numpy(), rcond=None)[0])
        se = np.std(bs, axis=0)
        print("   regressors", cols, "coef", np.round(b, 3), "t", np.round(b / se, 1))
    # ---- A-2b: duration model
    def stack(part):
        lx = np.concatenate([a for a, _, _ in samp[part]]); ls = np.concatenate([b for _, b, _ in samp[part]]); tau = np.concatenate([c for _, _, c in samp[part]])
        return np.column_stack([np.ones(len(lx)), lx, ls]), np.maximum(tau, 1.0)
    Xtr, ytr = stack("train")
    Xte, yte = stack("test")
    phi, alpha = gamma_fit(Xtr, ytr)
    phi0, alpha0 = gamma_fit(Xtr[:, :1], ytr)
    rm = lambda Xm, y, p: float(np.sqrt(np.mean((y - np.exp(Xm[:, :len(p)] @ p)) ** 2)))
    print(f"\nA-2b  duration model on {len(ytr)} training rows (tau: mean {ytr.mean():.0f} s, median {np.median(ytr):.0f} s, censored at {T_MAX_S} s: {np.mean(ytr >= T_MAX_S):.0%})")
    print(f"   with covariates: intercept {phi[0]:+.3f}, ln|x| {phi[1]:+.3f}, ln sigma {phi[2]:+.3f}, shape alpha {alpha:.3f}   | without: intercept {phi0[0]:+.3f}, alpha {alpha0:.3f}")
    print(f"   RMSE s  in-sample: with {rm(Xtr, ytr, phi):.1f} / without {rm(Xtr, ytr, phi0):.1f}   test days ({len(yte)} rows): with {rm(Xte, yte, phi):.1f} / without {rm(Xte, yte, phi0):.1f}")
    ex = np.array([[1, np.log(10), np.log(0.5)], [1, np.log(20), np.log(0.5)], [1, np.log(20), np.log(1.5)], [1, np.log(40), np.log(1.5)]])
    m1, v = gamma_moments(phi, alpha, ex)
    for (_, lx, ls), a, b in zip(ex, m1, v):
        sg = np.exp(ls)
        print(f"   |x| {np.exp(lx):4.0f} bp, sigma {sg:.1f} bp/sqrt(s): E[tau] {a:6.0f} s, sd {np.sqrt(b):6.0f} s -> bound(gamma 2) {arbitrage_bound(sg, a, b + a * a, 2.0):5.1f} bp; if tau were certain {arbitrage_bound(sg, a, a * a, 2.0):5.1f} bp")
    # ---- A-2c: strategy
    trades = {f"{k}{v:g}": [] for k, v in RULES}
    for r in I.itertuples():                                           # pass 2: one contract-day at a time
        P = X.load_pair(r.sym, r.day, orders=False)
        x, sig = per_second(P)
        c = candidates(P, x, sig, (phi, alpha))
        if len(c):
            for kind, val in RULES:
                trades[f"{kind}{val:g}"] += simulate(P, x, c, threshold(c, kind, val))
        del P
        print(r.sym, r.day, "simulated", flush=True)
    res = {}
    for name, days in (("TRAIN (model fitted here)", D.TRAIN), ("DEVELOPMENT TEST", D.TEST)):
        print(f"\nA-2c  {name}: pnl per $ after four taker legs and exit spreads")
        for key, rows in trades.items():
            tr = pd.DataFrame(rows)
            if len(tr):
                tr.to_parquet(os.path.join(D.ROOT, "data", "research5", f"xv_inv_trades_{key}.parquet"))
                res[(name, key)] = report(tr, key, days)
                if key.startswith("fixed"):
                    report(tr[tr.sym != "AKEUSDTM"], "  without AKE", days)
    r = res.get(("DEVELOPMENT TEST", "bound2"))
    if r:
        print(f"\nPRIMARY (bound, gamma 2, development test): pnl > 0 and CI lower > 0: {bool(r['pnl'] > 0 and r['lo'] > 0)} | >= 60 % contracts positive: {bool(r['share'] >= 0.6)}"
              f" | both days positive: {all(v > 0 for v in r['byday'].values()) and len(r['byday']) == 2}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--a3", action="store_true")
    main_a3() if ap.parse_args().a3 else main()
