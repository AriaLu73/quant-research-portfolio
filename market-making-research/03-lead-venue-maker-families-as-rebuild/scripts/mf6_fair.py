#!/usr/bin/env python3
"""research5 MF-6: a multi-venue fair value for BTC (user 2026-10-03: the price is formed by several exchanges together).

Model (local level, asynchronous observations; Buccheri-Corsi-Peluso 2021, de Jong-Schotman 2010):
    efficient price  m_t   random walk, variance s2 per millisecond
    a trade on venue v at price y is an observation  y - basis_v = m + e_v,  e_v ~ N(0, R_v)
    scalar Kalman filter over all venues' trades merged by the time WE see them (venue timestamp + delay_v):
        P <- P + s2 * dt;  K = P / (P + R_v);  m <- m + K * (y - basis_v - m);  P <- (1 - K) * P
    -> the weight of a venue is its Kalman gain: large when its noise R_v is small and when the estimate is old.
basis     each venue other than the Binance perp has its own slowly moving basis b_v (random walk, variance qb_v per ms),
          estimated inside the same filter: a trade of venue v observes m + b_v + noise.
R_v, s2, qb_v   from one day, used on the OTHER day: R_v = Roll (minus the first autocovariance of trade-to-trade changes);
          s2 = realised variance of the Binance perp at 1 s; qb_v = variance of 60 s changes of (venue - Binance perp), less noise.
Delays (ms, to a server in OUR_DATACENTER; Binance measured 1.4, the others ASSUMED and to be measured):
          binance_perp 2, binance_spot 3, okx 45, okx_spot 45, bybit 70.   "zero" variants use 2 ms for every venue (upper bound).
Output    data/research5/maker_families/fairmv_<variant>_<day>.npz  (t ns = when the estimate is available, m = Binance-perp-equivalent price)
Usage     .venv/Scripts/python.exe scripts/research5/mf6_fair.py
"""
import json, os
import numpy as np

OUT = os.path.join("data", "research5", "maker_families")
MS = 10**6
DAYS = ("20261001", "20261002")
OTHER = {"20261001": "20261002", "20261002": "20261001"}
VENUES = ("binance_perp", "binance_spot", "okx", "okx_spot", "bybit")
DELAY = dict(binance_perp=2.0, binance_spot=3.0, okx=45.0, okx_spot=45.0, bybit=70.0)
VARIANTS = {
    "bn":      (("binance_perp",), DELAY),
    "bn2":     (("binance_perp", "binance_spot"), DELAY),
    "all":     (VENUES, DELAY),
    "all0":    (VENUES, {v: 2.0 for v in VENUES}),                 # every venue seen after 2 ms: what the information is worth without transit time
}


def load(v, day):
    if v == "binance_perp":
        z = np.load(os.path.join(OUT, f"binance_BTCUSDT_{day}.npz"))
        return z["t"], z["p"]
    z = np.load(os.path.join(OUT, f"venue_{v}_{day}.npz"))
    return z["t"], z["p"]


def at(t, p, x):
    i = np.searchsorted(t, x, side="right") - 1
    out = p[np.clip(i, 0, len(p) - 1)].astype(float)
    out[i < 0] = np.nan
    return out


def moments(v, day, ref):
    """-> noise variance R (USD^2, Roll: minus the first autocovariance of trade-to-trade changes), diffusion s2 (USD^2 per ms,
    realised variance of the venue's price at 1 s), basis diffusion qb (USD^2 per ms, variance of 60 s changes of
    venue price - Binance perp price, less the noise)."""
    t, p = load(v, day)
    d = np.diff(p)
    R = max(-np.mean(d[1:] * d[:-1]), 0.0025)
    g = np.arange(t[0] // 10**9 + 1, t[-1] // 10**9) * 10**9
    x = at(t, p, g)
    s2 = np.nanmean(np.diff(x) ** 2) / 1000.0
    diff = x - at(ref[0], ref[1], g)
    qb = max((np.nanmean((diff[60:] - diff[:-60]) ** 2) - 4 * R) / 60000.0, 1e-7) if v != "binance_perp" else 0.0
    return dict(R=float(R), s2=float(s2), qb=float(qb))


def run(day, venues, delay, par):
    """Kalman filter with state (m, b_1 .. b_k): m = efficient price in Binance-perp terms, b_v = slowly moving basis of
    venue v (random walk, variance qb_v per ms; Binance perp has none). A trade of venue v observes m + b_v + noise."""
    obs_t, obs_y, obs_v = [], [], []
    for k, v in enumerate(venues):
        t, p = load(v, day)
        obs_t.append(t + int(delay[v] * MS)); obs_y.append(p.astype(float)); obs_v.append(np.full(len(t), k))
    T, Y, V = np.concatenate(obs_t), np.concatenate(obs_y), np.concatenate(obs_v)
    o = np.argsort(T, kind="stable")
    T, Y, V = T[o], Y[o], V[o]
    n = len(venues)
    s2 = par["binance_perp"]["s2"]
    R = [par[v]["R"] + s2 * delay[v] for v in venues]            # an observation that is delay ms old is that much less exact
    qb = np.array([0.0] + [par[v]["qb"] for v in venues[1:]])
    x = np.zeros(n); x[0] = Y[0]
    P = np.diag([1e4] + [1e4] * (n - 1)).astype(float)
    if n > 1:                                                     # start each basis at the first observed difference
        for k in range(1, n):
            x[k] = Y[np.argmax(V == k)] - Y[0]
    out = np.empty(len(T))
    gain = np.zeros(n); cnt = np.zeros(n)
    last = T[0]
    Tl, Yl, Vl = T.tolist(), Y.tolist(), V.tolist()
    idx = np.arange(1, n)
    for i in range(len(Tl)):
        dt = (Tl[i] - last) / MS
        if dt > 0:
            P[0, 0] += s2 * dt
            P[idx, idx] += qb[1:] * dt
            last = Tl[i]
        j = Vl[i]
        if j == 0:
            Ph = P[:, 0].copy(); S = Ph[0] + R[0]; innov = Yl[i] - x[0]
        else:
            Ph = P[:, 0] + P[:, j]; S = Ph[0] + Ph[j] + R[j]; innov = Yl[i] - x[0] - x[j]
        K = Ph / S
        x += K * innov
        P -= np.outer(K, Ph)
        out[i] = x[0]
        gain[j] += K[0]; cnt[j] += 1
    return T, out, {v: float(gain[k] / max(cnt[k], 1)) for k, v in enumerate(venues)}


def main():
    par = {}
    for day in DAYS:
        ref = load("binance_perp", day)
        par[day] = {v: moments(v, day, ref) for v in VENUES}
        print(day, "noise sd (USD) / diffusion (USD per sqrt ms) / basis diffusion (USD per sqrt minute): " +
              ", ".join(f"{v} {par[day][v]['R'] ** .5:.2f} / {par[day][v]['s2'] ** .5:.3f} / {(par[day][v]['qb'] * 60000) ** .5:.2f}" for v in VENUES))
    json.dump(par, open(os.path.join(OUT, "mf6_params.json"), "w"), indent=1)
    for day in DAYS:
        for name, (venues, delay) in VARIANTS.items():
            T, m, g = run(day, venues, delay, par[OTHER[day]])
            keep = np.r_[True, m[1:] != m[:-1]]
            np.savez_compressed(os.path.join(OUT, f"fairmv_{name}_{day}.npz"), t=T[keep], m=m[keep])
            print(f"{day} {name:5s}: observations {len(T):,}; mean weight of one trade in the price estimate (Kalman gain): " + ", ".join(f"{v} {x:.2f}" for v, x in g.items()), flush=True)


if __name__ == "__main__":
    main()
