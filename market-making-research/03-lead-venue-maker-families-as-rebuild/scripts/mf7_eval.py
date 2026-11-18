#!/usr/bin/env python3
"""research5 MF-7: money result of the ladder replay with the hedge on Binance, and the capital it ties up.

For one configuration (mf4_replay.py chain): all fills in time order. Accounting in USD:
  KuCoin leg   cash -q * price per fill (q = signed BTC), rebate OUR_FEE of the notional;
  hedge leg    after each fill the net exposure x = KuCoin position + hedge position; when |x| exceeds the band B the
               excess is traded on Binance at the Binance price 20 ms after the fill, fee f bp of that notional
               (B = 0: every fill is hedged at once; Barzykin-Bergault-Gueant: no hedge inside a band);
  end          both legs marked: KuCoin at Binance price + basis, Binance at its price.
Capital (20x leverage, user 2026-10-03): margin of the largest KuCoin position and of the largest hedge position at 5 % each,
resting orders of one side at 5 %, plus a 3 % price-move buffer on each venue's largest position.
Usage: .venv/Scripts/python.exe scripts/research5/mf7_eval.py W1 W2 ...
"""
import glob, json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import maker_families as M
import mf4_replay as R

MS = 10**6
REBATE = OUR_FEE
DAY0 = {"20261001": 1790812800, "20261002": 1790899200}


def load(name):
    rows = []
    hours = 0
    for p in sorted(glob.glob(os.path.join(R.OUT, f"fills_{name}_*.npz"))):
        day, hh = os.path.basename(p)[:-4].split("_")[2:4]
        hours += 1
        z = np.load(p)
        A, ts = z["fills"], z["ts"]
        if not len(A):
            continue
        fz = np.load(os.path.join(M.OUT, f"fair_{day}.npz"))
        bn = lambda t: fz["p"][np.clip(np.searchsorted(fz["t"], t, side="right") - 1, 0, len(fz["p"]) - 1)]
        basis = fz["basis"][np.clip(np.searchsorted(fz["g"], ts, side="right") - 1, 0, len(fz["g"]) - 1)]
        px = A[:, 3] / 10.0
        q = np.where(A[:, 1] == 0, 1.0, -1.0) * A[:, 4] * M.MULT
        rows.append(np.c_[ts, q, px, bn(ts + 20 * MS), basis, A[:, 2], np.full(len(A), int(day[-2:]) * 100 + int(hh))])
    X = np.concatenate(rows) if rows else np.zeros((0, 7))
    return X[np.argsort(X[:, 0], kind="stable")], hours


def account(X, band, fee):
    """-> total USD, array of cumulative USD after each fill (marked), max |KuCoin position|, max |hedge position|, hedge notional."""
    pk = ph = 0.0
    cash = 0.0
    hedged = 0.0
    mk = mh = 0.0
    curve = np.empty(len(X))
    for i, (ts, q, px, pb, basis, lvl, hr) in enumerate(X):
        cash += -q * px + abs(q) * px * REBATE / 1e4
        pk += q
        x = pk + ph
        if abs(x) > band:
            h = -(x - np.sign(x) * band)
            cash += -h * pb - abs(h) * pb * fee / 1e4
            ph += h
            hedged += abs(h) * pb
        mk, mh = max(mk, abs(pk)), max(mh, abs(ph))
        curve[i] = cash + pk * (pb + basis) + ph * pb
    return (curve[-1] if len(X) else 0.0), curve, mk, mh, hedged


def report(name):
    X, hours = load(name)
    cfg = R.CONFIGS[name]
    if not len(X):
        print(f"\n=== {name}: no fills")
        return
    days = hours / 24.0
    notional = (np.abs(X[:, 1]) * X[:, 2]).sum()
    edge = np.average(np.sign(X[:, 1]) * (X[:, 3] + X[:, 4] - X[:, 2]) / X[:, 2] * 1e4, weights=np.abs(X[:, 1]) * X[:, 2])
    print(f"\n=== {name}: levels {cfg['deltas']} bp, sizes {tuple(s * M.MULT for s in cfg['sizes'])} BTC, fair {cfg.get('fair', 'binance')}, cap {cfg.get('cap')}, skew {cfg['skew']} bp/BTC")
    print(f"   fills {len(X):,}; KuCoin notional ${notional / 1e6:.1f}M (${notional / 1e6 / days:.1f}M per day); entry edge vs hedge price {edge:+.2f} bp; break-even hedge fee {edge + REBATE:.2f} bp")
    side_orders = sum(cfg["sizes"]) * M.MULT * 85000
    print(f"   {'band BTC':>9s} {'fee bp':>7s} {'$ total':>10s} {'$ per day':>10s} {'hours > 0':>10s} {'worst hour $':>13s} {'max KuCoin pos':>15s} {'max hedge pos':>14s} {'hedge $M/day':>13s} {'capital $ (20x + 3% buffer)':>28s} {'$ per day / capital':>20s}")
    for band in (0.0, 1.0, 3.0):
        for fee in (0.0, 1.0, 1.8):
            tot, curve, mk, mh, hedged = account(X, band, fee)
            hrs = np.unique(X[:, 6])
            ends = np.array([curve[np.nonzero(X[:, 6] == h)[0][-1]] for h in hrs])
            per = np.diff(np.r_[0.0, ends])
            cap = (mk + mh) * 85000 * (0.05 + 0.03) + side_orders * 0.05
            print(f"   {band:9.1f} {fee:7.1f} {tot:10,.0f} {tot / days:10,.0f} {np.mean(per > 0):10.0%} {per.min():13,.0f} {mk:15.2f} {mh:14.2f} {hedged / 1e6 / days:13.2f} {cap:28,.0f} {tot / days / cap:20.2%}")


if __name__ == "__main__":
    for n in sys.argv[1:]:
        report(n)
