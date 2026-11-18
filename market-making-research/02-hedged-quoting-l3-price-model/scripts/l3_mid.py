#!/usr/bin/env python3
"""research3: the BTC-USDT mid used for every markout on our L3 days, taken from the L3 reconstruction itself.

Why (audit 2026-10-03): markouts were computed against qmm_l3_study.bbo(day), a best bid / ask series rebuilt from the separate
L2 recording. That recording has holes (10-01: one of 33 minutes, 121 longer than 5 s) during which the series stays at an
old price: in hours 14 and 15 of 10-01 it was wrong by more than 1 bp for 19 % and 33 % of the time (up to 40 bp), exactly the
two busiest hours of the development day. Wherever both series are alive they agree to 0.00 bp.
Fix: mid = (best bid + best ask) / 2 of the 2 ms L3 grid (px_l3grid.py), kept as change points. The first 120 s of every hour
file are not used (the L3 book only knows orders opened since the file started); a query there, or more than 5 s after the last
grid point of an hour, returns NaN.
usage as a module: mid = L3Mid(day); mid.at(t_ns)  (vectorised);  fix_markouts(recs, day, t_of, horizons_s=(1, 5, 10))"""
import glob, os
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GRID = os.path.join(ROOT, "data", "research3", "px", "BTC-USDT-L3-2ms")
CACHE = os.path.join(ROOT, "data", "research3", "px", "l3mid")
WARM_NS = 120 * 1_000_000_000
STALE_NS = 5 * 1_000_000_000


class L3Mid:
    def __init__(self, day):
        os.makedirs(CACHE, exist_ok=True)
        cp = os.path.join(CACHE, "mid_%s.npz" % day)
        if os.path.exists(cp):
            z = np.load(cp)
            self.t, self.m = z["t"], z["m"]
            return
        ts, ms = [], []
        for f in sorted(glob.glob(os.path.join(GRID, "grid_%s_??.parquet" % day))):
            g = pd.read_parquet(f, columns=["t", "bb", "ba", "crossed"])
            t = g.t.to_numpy(np.int64)
            mid = np.where(g.crossed.to_numpy(), np.nan, (g.bb.to_numpy() + g.ba.to_numpy()) / 2)
            mid[t < t[0] + WARM_NS] = np.nan
            keep = np.r_[True, ~((mid[1:] == mid[:-1]) | (np.isnan(mid[1:]) & np.isnan(mid[:-1])))]
            ts += [t[keep], np.array([t[-1] + STALE_NS], np.int64)]          # after the hour's last point: unknown
            ms += [mid[keep], np.array([np.nan])]
        self.t, self.m = np.concatenate(ts), np.concatenate(ms)
        o = np.argsort(self.t, kind="stable")
        self.t, self.m = self.t[o], self.m[o]
        np.savez(cp, t=self.t, m=self.m)

    def at(self, t_ns):
        t_ns = np.asarray(t_ns, np.int64)
        i = np.searchsorted(self.t, t_ns, side="right") - 1
        out = np.where(i >= 0, self.m[np.clip(i, 0, len(self.m) - 1)], np.nan)
        return out


def fix_markouts(recs, day, fill_ns, horizons_s=(1, 5, 10)):
    """Recompute rec["m"] of every filled record against the L3 mid. fill_ns(rec) -> fill time in ns (None if not filled)."""
    mid = L3Mid(day)
    idx = [k for k, r in enumerate(recs) if fill_ns(r) is not None]
    if not idx:
        return recs
    tf = np.array([fill_ns(recs[k]) for k in idx], np.int64)
    px = np.array([recs[k]["p"] for k in idx])
    sg = np.array([recs[k]["s"] for k in idx])
    M = np.stack([sg * (mid.at(tf + h * 1_000_000_000) - px) / px * 1e4 for h in horizons_s], 1)
    for row, k in zip(M, idx):
        recs[k]["m"] = [float(x) for x in row]
    return recs
