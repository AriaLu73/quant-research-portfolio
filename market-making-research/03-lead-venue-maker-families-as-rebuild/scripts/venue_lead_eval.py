#!/usr/bin/env python3
"""research5: lead / lag between BTC venues from venue_lead_probe.py (exchange timestamps).

1. Update rate and timestamp granularity per venue; how long after its own timestamp each venue's update reached us,
   relative to Binance (same PC, so the difference is the venue's publishing delay plus the difference in network path).
2. Around jumps of the Binance perpetual mid (>= J bp within 50 ms): each venue's mid, signed by the jump, at offsets
   from -200 to +1000 ms on the exchange clocks -> who has moved before Binance, who follows and how fast.
3. Around each venue's own jumps: where is Binance (does the venue move first?).
Usage: .venv/Scripts/python.exe scripts/research5/venue_lead_eval.py <probe.npz> [J=0.5]
"""
import sys
import numpy as np

MS = 1.0
OFFS = (-200, -100, -50, -20, -10, -5, 0, 5, 10, 20, 50, 100, 200, 500, 1000)


def series(a, clock):
    """-> (t ms sorted, mid). clock 'x' = exchange timestamp, 'r' = our receive time (ms)."""
    t = a[:, 0] if clock == "x" else a[:, 1] / 1e6
    o = np.argsort(t, kind="stable")
    return t[o], a[o, 2]


def at(t, m, x):
    i = np.searchsorted(t, x, side="right") - 1
    out = m[np.clip(i, 0, len(m) - 1)].astype(float)
    out[i < 0] = np.nan
    return out


def jumps(t, m, J, win=50.0, quiet=500.0):
    prev = at(t, m, t - win)
    j = (m - prev) / prev * 1e4
    idx = np.nonzero(np.abs(j) >= J)[0]
    ev, last = [], -1e18
    for i in idx:
        if t[i] - last > quiet:
            ev.append(i)
        last = t[i]
    ev = np.array(ev, int)
    return t[ev], np.sign(j[ev])


def main():
    z = np.load(sys.argv[1])
    J = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
    V = {k: z[k] for k in z.files}
    ref = "binance_perp"
    lag_ref = np.median(V[ref][:, 1] / 1e6 - V[ref][:, 0])
    span = (V[ref][-1, 0] - V[ref][0, 0]) / 60000
    print(f"probe length {span:.1f} min")
    print(f"{'venue':13s} {'updates/s':>9s} {'distinct ts/s':>13s} {'arrives after its own timestamp, vs Binance (ms): p10 / p50 / p90':>66s}")
    for v, a in V.items():
        d = a[:, 1] / 1e6 - a[:, 0] - lag_ref
        print(f"{v:13s} {len(a) / span / 60:9.1f} {len(np.unique(a[:, 0])) / span / 60:13.1f} {np.percentile(d, 10):22.0f} / {np.median(d):.0f} / {np.percentile(d, 90):.0f}")
    for clock, title in (("x", "exchange timestamps"), ("r", "time the update reached our PC (includes each venue's publishing delay and network path)")):
        t0, sg = jumps(*series(V[ref], clock), J)
        print(f"\n[{title}] Binance perp jumps >= {J} bp within 50 ms: {len(t0)} events. Mean move of each venue in the jump's direction (bp), relative to 300 ms before:")
        print(f"{'offset ms':>13s}" + "".join(f"{o:>7d}" for o in OFFS))
        for v, a in V.items():
            if v == "binance_spot" and clock == "x":
                continue
            t, m = series(a, clock)
            base = at(t, m, t0 - 300)
            row = [np.nanmean(sg * (at(t, m, t0 + o) - base) / base * 1e4) for o in OFFS]
            print(f"{v:13s}" + "".join(f"{x:7.2f}" for x in row))
    print(f"\n[exchange timestamps] each venue's own jumps >= {J} bp within 50 ms: where is Binance perp (mean move in the venue's direction, bp, relative to 300 ms before)?")
    print(f"{'offset ms':>13s}" + "".join(f"{o:>7d}" for o in OFFS) + "   events")
    tb, mb = series(V[ref], "x")
    for v, a in V.items():
        if v in (ref, "binance_spot"):
            continue
        t1, s1 = jumps(*series(a, "x"), J)
        if len(t1) < 5:
            print(f"{v:13s} {len(t1)} events")
            continue
        base = at(tb, mb, t1 - 300)
        row = [np.nanmean(s1 * (at(tb, mb, t1 + o) - base) / base * 1e4) for o in OFFS]
        print(f"{v:13s}" + "".join(f"{x:7.2f}" for x in row) + f"   {len(t1)}")


if __name__ == "__main__":
    main()
