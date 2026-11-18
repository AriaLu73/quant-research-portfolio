#!/usr/bin/env python3
"""research5 MF-4b: evaluate the ladder replay (mf4_replay.py) with the hedge on Binance as a parameter.

Per configuration: fills, notional, entry edge against the hedge price (Binance last trade L ms after the fill + basis at
the fill), KuCoin-only markout at 10 s, by ladder level; share of hours with a positive edge; break-even hedge fee
(= edge + OUR_FEE rebate); position range; messages per hour. Notional-weighted throughout.
Usage: .venv/Scripts/python.exe scripts/research5/mf4_eval.py [A G E F B ...]
"""
import glob, json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import maker_families as M
import mf4_replay as R

MS = 10**6
LAGS = (20, 100, 1000)
REBATE = OUR_FEE


def load(name):
    rows, stats = [], []
    for p in sorted(glob.glob(os.path.join(R.OUT, f"fills_{name}_*.npz"))):
        day, hh = os.path.basename(p)[:-4].split("_")[2:4]
        z = np.load(p)
        A, ts = z["fills"], z["ts"]
        stats.append(json.load(open(os.path.join(R.OUT, f"stats_{name}_{day}_{hh}.json"))))
        if not len(A):
            continue
        fz = np.load(os.path.join(M.OUT, f"fair_{day}.npz"))
        mz = np.load(os.path.join(M.MID, f"mid_{day}.npz"))
        bn = lambda t: fz["p"][np.clip(np.searchsorted(fz["t"], t, side="right") - 1, 0, len(fz["p"]) - 1)]
        basis = fz["basis"][np.clip(np.searchsorted(fz["g"], ts, side="right") - 1, 0, len(fz["g"]) - 1)]
        mid = lambda t: mz["m"][np.clip(np.searchsorted(mz["t"], t, side="right") - 1, 0, len(mz["m"]) - 1)]
        px = A[:, 3] / 10.0
        sg = np.where(A[:, 1] == 0, 1.0, -1.0)
        d = dict(ts=ts, hour=np.full(len(A), int(day[-2:] + hh)), side=A[:, 1], level=A[:, 2], px=px, size=A[:, 4], age=A[:, 6],
                 notional=A[:, 4] * M.MULT * px, q=sg * A[:, 4] * M.MULT,
                 m10=sg * (mid(ts + 10 * 10**9) - px) / px * 1e4,
                 pre=sg * (bn(ts + 20 * MS) - bn(ts - 20 * MS)) / px * 1e4)          # Binance move around the fill, + = in our favour
        for l in LAGS:
            d["e%d" % l] = sg * (bn(ts + l * MS) + basis - px) / px * 1e4
        rows.append(d)
    if not rows:
        return None, stats
    return {k: np.concatenate([r[k] for r in rows]) for k in rows[0]}, stats


def w(D, c, m):
    m = m & np.isfinite(D[c])
    return np.average(D[c][m], weights=D["notional"][m]) if m.any() else np.nan


def report(name):
    D, stats = load(name)
    cfg = R.CONFIGS[name]
    hours = len(stats)
    placed = sum(s["placed"] for s in stats)
    print(f"\n=== {name}: deltas {cfg['deltas']} bp, order / cancel {cfg['tau_o']:g} / {cfg['tau_c']:g} ms, Binance data {cfg['d_bn']:g} ms late; {hours} hours; orders {placed / hours:,.0f}/h")
    if D is None:
        print("   no fills")
        return
    allm = np.isfinite(D["e20"])
    print(f"   {'':10s} {'fills':>6s} {'$M':>7s} {'$M/day':>7s} {'e20':>7s} {'e100':>7s} {'e1000':>7s} {'m10 KuCoin':>11s} {'hours>0':>8s} {'fills>0':>8s} {'break-even fee':>15s} {'Binance against':>16s}")
    for lab, m in [("all", allm)] + [(f"level {k} ({cfg['deltas'][k]:g} bp)", allm & (D["level"] == k)) for k in range(len(cfg["deltas"]))]:
        if m.sum() < 5:
            print(f"   {lab:10s} {m.sum():6d}")
            continue
        hv = np.array([w(D, "e20", m & (D["hour"] == h)) for h in np.unique(D["hour"][m])])
        print(f"   {lab:10s} {m.sum():6d} {D['notional'][m].sum() / 1e6:7.2f} {D['notional'][m].sum() / 1e6 / hours * 24:7.2f} {w(D, 'e20', m):7.2f} {w(D, 'e100', m):7.2f} {w(D, 'e1000', m):7.2f} "
              f"{w(D, 'm10', m):11.2f} {np.mean(hv > 0):8.0%} {np.average(D['e20'][m] > 0, weights=D['notional'][m]):8.0%} {w(D, 'e20', m) + REBATE:15.2f} "
              f"{np.average(D['pre'][m] <= -0.5, weights=D['notional'][m]):16.0%}")
    o = np.argsort(D["ts"])
    inv = np.cumsum(D["q"][o])
    e = w(D, "e20", allm)
    usd = lambda fee: ((D["e20"][allm] + REBATE - fee) * D["notional"][allm]).sum() / 1e4 / hours * 24
    print(f"   position min {inv.min():+.1f} / max {inv.max():+.1f} BTC; $ per day at hedge fee 0 / 1 / OUR_FEE: {usd(0):,.0f} / {usd(1):,.0f} / {usd(1.8):,.0f}")


if __name__ == "__main__":
    for n in (sys.argv[1:] or ["A", "G", "E", "F", "B"]):
        report(n)
