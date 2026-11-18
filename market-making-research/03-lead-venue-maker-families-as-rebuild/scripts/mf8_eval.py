#!/usr/bin/env python3
"""research5 MF-8: KuCoin only - deep ladder, every fill closed on KuCoin as a taker H ms later (no second venue).

Input: mf4_replay.py chain X*: per fill the entry (maker, price / size) and, for each hold H, the average price a taker
order of the same size obtains from the REAL book at that moment (walking the levels), with the best price then.
Per fill:  result bp = maker-signed (exit average - entry) + 0.7 (maker rebate) - 1.8 (taker fee), on the entry notional.
A fill whose exit could not be fully obtained from the book is counted at the price obtained for the part obtained and
flagged. Our own exit order's effect on later prices is not modelled; the exit order is assumed to arrive exactly at H.
Also: the same fills capped at 0.25 BTC per order with the exit at the best price then (approximation for a small account).
Usage: .venv/Scripts/python.exe scripts/research5/mf8_eval.py X1 X2 X3
"""
import glob, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import maker_families as M
import mf4_replay as R

REBATE, TAKER = 0.7, 1.8


def load(name):
    A, EX, HR = [], [], []
    hours = 0
    for p in sorted(glob.glob(os.path.join(R.OUT, f"fills_{name}_*.npz"))):
        day, hh = os.path.basename(p)[:-4].split("_")[2:4]
        hours += 1
        z = np.load(p)
        if len(z["fills"]):
            A.append(z["fills"]); EX.append(z["exits"]); HR.append(np.full(len(z["fills"]), int(day[-2:]) * 100 + int(hh)))
    return np.concatenate(A), np.concatenate(EX), np.concatenate(HR), hours


def table(title, A, EX, HR, hours, cfg, cap=None):
    px = A[:, 3] / 10.0
    sg = np.where(A[:, 1] == 0, 1.0, -1.0)
    size = A[:, 4] if cap is None else np.minimum(A[:, 4], cap)
    N = size * M.MULT * px
    days = hours / 24.0
    print(f"\n{title}: fills {len(A):,}, entry notional ${N.sum() / 1e6:.2f}M (${N.sum() / 1e6 / days:.2f}M per day)")
    print(f"   {'hold ms':>8s} {'exit vs entry bp':>17s} {'net bp (+0.7 -1.8)':>19s} {'$ per day':>10s} {'hours > 0':>10s} {'fills > 0':>10s} {'worst hour $':>13s} {'exit fully obtained':>20s}  by level (net bp): " +
          "  ".join(f"{d:g}" for d in cfg["deltas"]))
    for hk, h in enumerate(R.HOLDS_MS):
        ex = EX[:, hk, 0] if cap is None else EX[:, hk, 2]                 # small account: exit at the best price then
        ok = np.isfinite(ex)
        gross = sg * (ex / 10.0 - px) / px * 1e4
        net = gross + REBATE - TAKER
        usd = net * N / 1e4
        full = (EX[:, hk, 1] >= A[:, 4] - 1e-9) if cap is None else np.ones(len(A), bool)
        hrs = np.unique(HR[ok])
        per = np.array([usd[ok & (HR == x)].sum() for x in hrs])
        lv = []
        for k in range(len(cfg["deltas"])):
            m = ok & (A[:, 2] == k)
            lv.append(f"{np.average(net[m], weights=N[m]):+.2f}" if m.sum() >= 5 else "-")
        print(f"   {h:8d} {np.average(gross[ok], weights=N[ok]):17.2f} {np.average(net[ok], weights=N[ok]):19.2f} {usd[ok].sum() / days:10,.0f} {np.mean(per > 0):10.0%} "
              f"{np.average(net[ok] > 0, weights=N[ok]):10.0%} {per.min():13,.0f} {np.average(full[ok], weights=N[ok]):20.0%}  " + "  ".join(lv))
    return N


def report(name):
    A, EX, HR, hours = load(name)
    cfg = R.CONFIGS[name]
    print(f"\n=== {name}: levels {cfg['deltas']} bp, {cfg['sizes'][0] * M.MULT:g} BTC each, fair {cfg.get('fair', 'binance')}, order / cancel {cfg['tau_o']:g} / {cfg['tau_c']:g} ms; {hours} hours")
    lv = [(A[:, 2] == k) for k in range(len(cfg["deltas"]))]
    print("   fills per level: " + ", ".join(f"{d:g} bp: {m.sum()} (${(A[m, 4] * M.MULT * A[m, 3] / 10).sum() / 1e6:.2f}M)" for d, m in zip(cfg["deltas"], lv)))
    table("1 BTC per level, exit by walking the real book", A, EX, HR, hours, cfg)
    table("capped at 0.25 BTC per fill, exit at the best price then (approximation)", A, EX, HR, hours, cfg, cap=250)
    # concurrency: largest position if every fill is held 1 s
    ts = A[:, 0]
    o = np.argsort(ts)
    q = (np.where(A[:, 1] == 0, 1.0, -1.0) * A[:, 4] * M.MULT)[o]
    t = ts[o]
    ev = np.r_[np.c_[t, q], np.c_[t + 1e9, -q]]
    ev = ev[np.argsort(ev[:, 0], kind="stable")]
    inv = np.cumsum(ev[:, 1])
    print(f"   largest position when every fill is held 1 s: {np.abs(inv).max():.2f} BTC (resting orders: {sum(cfg['sizes']) * M.MULT:g} BTC per side)")


if __name__ == "__main__":
    for n in sys.argv[1:] or ["X1", "X2", "X3"]:
        report(n)
