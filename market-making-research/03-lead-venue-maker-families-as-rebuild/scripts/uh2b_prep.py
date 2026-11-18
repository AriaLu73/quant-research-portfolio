#!/usr/bin/env python3
"""research5 UH-2b: loss-rate table for a resting quote that cannot be cancelled faster than tau_c (training days only).

Budish-Cramton-Shim (QJE 2015, eq. 3) balance for one resting quote with margin d (bp from fair value):
    benign profit rate  Lambda(d) (d - c_net)   >=   rate of being picked off  R(d)
R(d) [bp per second] = expected loss per second from reference moves that happen inside our reaction time tau_c:
for every change of the reference mid at time t_j, the last state we could still have acted on is the mid at t_j - tau_c
("stale reference"). With a = adverse move from that stale reference after the change and a_pre = the same just before it,
the change adds   max(0, (a - d)+ - (a_pre - d)+)   to the loss of a quote that had margin d at the stale reference
(each increment is counted once; a recovery does not undo a loss). Averaged over the two sides and divided by the time
covered. This assumes every such move is taken by somebody faster than our cancel (p_lose = 1, conservative; the real
share needs live "cancel rejected: filled" statistics).
Differs from research2/sep_u16_prep.py (U16): that table is per reference-change event with overlapping windows and was
compared with Lambda x tau_c, which overstates the loss side by 1 / (changes per second x tau_c).

Input : data/research2/events/book_<SYM>_<day>.parquet (ts in microseconds, bb / ba in ticks; KuCoin USDT contract L1)
Output: data/research5/uh2b_prep_<SYM>_tau<us>.json: grid step, R table at the reference volatility, sigma_ref
Usage : python scripts/research5/uh2b_prep.py BTC_B 1800        (Python314)
"""
import json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EV = os.path.join(ROOT, "data", "research2", "events")
DAYS = ["20260901", "20260902", "20260903", "20260910", "20260911", "20260914", "20260917", "20260918"]     # September training days
GRID = np.round(np.arange(0, 10.001, 0.05), 2)


def loss_increments(t, mid, tau, grid):
    """Sum over reference changes of the loss increment for each margin in grid, one side at a time.
    t (same unit as tau) and mid are the reference mid at its change times. Returns (down, up): losses of a resting bid
    (reference falls) and of a resting ask (reference rises), each an array like grid, in bp summed over events."""
    t, mid = np.asarray(t), np.asarray(mid, float)
    if len(t) < 2:
        return np.zeros(len(grid)), np.zeros(len(grid))
    post, pre, tj = mid[1:], mid[:-1], t[1:]
    k = np.clip(np.searchsorted(t, tj - tau, side="right") - 1, 0, len(t) - 1)      # last change at or before t_j - tau
    ref = mid[k]
    out = []
    for sgn in (1.0, -1.0):                                   # +1: adverse = down (bid);  -1: adverse = up (ask)
        a = sgn * (ref - post) / ref * 1e4
        a_pre = sgn * (ref - pre) / ref * 1e4
        tot = np.empty(len(grid))
        for i, d in enumerate(grid):
            tot[i] = np.maximum(0.0, np.maximum(a - d, 0.0) - np.maximum(a_pre - d, 0.0)).sum()
        out.append(tot)
    return out[0], out[1]


def main():
    import pandas as pd
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTC_B"
    tau_us = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
    tabs, sig, nu = [], [], []
    for d in DAYS:
        b = pd.read_parquet(os.path.join(EV, f"book_{sym}_{d}.parquet"), columns=["ts", "bb", "ba"])
        ok = ((b.bb > 0) & (b.ba > b.bb)).to_numpy()
        ts = b.ts.to_numpy().astype(np.int64)[ok]
        mid = ((b.bb.to_numpy() + b.ba.to_numpy()) / 2.0)[ok]
        ch = np.r_[True, np.diff(mid) != 0]
        t, m = ts[ch], mid[ch]
        secs = (ts[-1] - ts[0]) / 1e6
        dn, up = loss_increments(t, m, tau_us, GRID)
        tabs.append((dn + up) / 2 / secs)
        g = np.arange(ts[0], ts[-1], 1_000_000)
        a = mid[np.clip(np.searchsorted(ts, g, side="right") - 1, 0, len(mid) - 1)]
        sig.append(float(np.abs(np.diff(np.log(a))).mean() * 1e4 * np.sqrt(np.pi / 2)))
        nu.append(len(t) / secs)
        print(d, f"sigma {sig[-1]:.3f} bp/sqrt(s)  mid changes {nu[-1]:.1f}/s  R(0) {tabs[-1][0]:.4f}  R(0.5) {tabs[-1][10]:.5f}  R(1) {tabs[-1][20]:.6f}  R(2) {tabs[-1][40]:.7f}", flush=True)
    out = dict(sym=sym, tau_s=tau_us / 1e6, days=DAYS, step_bp=0.05, sigma_ref=float(np.mean(sig)), changes_per_s=float(np.mean(nu)),
               loss_rate=np.mean(tabs, axis=0).tolist())
    json.dump(out, open(os.path.join(ROOT, "data", "research5", f"uh2b_prep_{sym}_tau{tau_us}.json"), "w"), indent=1)
    print({k: v for k, v in out.items() if k not in ("loss_rate", "days")})
    print("R(d) at d = 0, 0.25, 0.5, 1, 2, 3, 5 bp:", [float(f"{out['loss_rate'][i]:.3g}") for i in (0, 5, 10, 20, 40, 60, 100)])


if __name__ == "__main__":
    main()
