#!/usr/bin/env python3
"""research5 MF-10: a book-based quoting rule, chosen on one half of the purchased days and tested on the other half.

Rule family (fixed before looking at the test half): a level at distance d is quoted only while the resting volume between
the touch and d on that side, V(d), is at or below its q-quantile over the previous 60 minutes (rank <= q). The threshold is
a quantile of the recent past, not a number of BTC, so it adapts to how thick the book currently is.
  q in {0.10, 0.25, 0.50, 0.75, 1.00 (= no rule)}; one q for all levels.
Fills: mf9_sim.py config L (wide ladder, 7 levels, Binance fair value, activity rule), every day. V(d) from mf10_bands.py,
taken 100 ms before the fill. The rule is applied as a filter on those fills (our absence would leave slightly more of a
sweep for our other levels; ignored).
  development  08-26 .. 09-04 (10 days): choose q, separately for the two ways of closing the position
  test         09-05 .. 09-24 (10 days), and 10-01 / 10-02 shown separately
  A  KuCoin only: taker exit on KuCoin 0.5 s after the fill (net of 0.2 slippage, OUR_FEE rebate, -1.8 fee), levels >= 4.5 bp
  B  hedge on Binance 20 ms after the fill at fee 1 bp (OUR_FEE rebate), all levels
Usage: Python314/python.exe scripts/research5/mf10_rules.py
"""
import glob, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mf9_sim as S
import mf10_bands as BD

MS = 10**6
QS = (0.10, 0.25, 0.50, 0.75, 1.00)
DEV_END = "20260904"
WINDOW = 36000                       # 60 minutes of 100 ms points


def load():
    cfg = S.CONFIGS["L"]
    band_ix = [BD.BANDS.index(d) for d in cfg["deltas"]]
    rows = []
    for p in sorted(glob.glob(os.path.join(S.OUT, "L_*.npz"))):
        day = os.path.basename(p)[2:-4]
        z = np.load(p)
        A = z["fills"]
        bp_ = os.path.join(BD.OUT, f"bands_{day}.npz")
        if not len(A) or not os.path.exists(bp_):
            continue
        b = np.load(bp_)
        bt = b["t"]
        j = np.searchsorted(bt, A[:, 0].astype(np.int64) - 100 * MS, side="right") - 1
        ok = (j >= 600) & ((A[:, 0] - bt[np.clip(j, 0, len(bt) - 1)]) < 5e9)
        V = np.full(len(A), np.nan); rank = np.full(len(A), np.nan)
        for i in np.nonzero(ok)[0]:
            arr = b["vb"] if A[i, 1] == 0 else b["va"]
            col = band_ix[int(A[i, 2])]
            v = arr[j[i], col]
            hist = arr[max(0, j[i] - WINDOW):j[i], col]
            V[i] = v
            rank[i] = np.mean(hist <= v)
        px = A[:, 3] / 10.0
        sg = np.where(A[:, 1] == 0, 1.0, -1.0)
        N = A[:, 4] * 0.001 * px
        ku = sg * (z["exits"][:, 2] - px) / px * 1e4 - S.SLIP + S.REBATE - S.TAKER
        hd = sg * (z["hedge"][:, 0] - px) / px * 1e4 + S.REBATE - 1.0
        rows.append(pd.DataFrame(dict(day=day, lvl=A[:, 2].astype(int), d=[cfg["deltas"][int(k)] for k in A[:, 2]], N=N, V=V, rank=rank, ku=ku, hd=hd, hours=int(z["hours"]))))
    return pd.concat(rows, ignore_index=True), cfg


def w(g, c):
    m = np.isfinite(g[c])
    return np.average(g[c][m], weights=g.N[m]) if m.sum() >= 5 else np.nan


def line(g, c, days):
    m = np.isfinite(g[c])
    usd = (g[c][m] * g.N[m] / 1e4)
    per = usd.groupby(g.day[m]).sum().reindex(days, fill_value=0.0)
    se = np.sqrt(np.average((g[c][m] - w(g, c)) ** 2, weights=g.N[m]) / max(m.sum(), 1)) if m.sum() >= 5 else np.nan
    return f"fills {m.sum():5d}  ${g.N[m].sum() / 1e6:6.2f}M  net {w(g, c):+6.2f} bp (se {se:.2f})  $ per day {usd.sum() / len(days):7,.0f}  days > 0 {np.mean(per > 0):4.0%}  worst day {per.min():7,.0f}"


def main():
    D, cfg = load()
    D = D[np.isfinite(D["rank"])]
    sets = {"development 08-26..09-04": D[(D.day <= DEV_END) & (D.day < "20261001")], "TEST 09-05..09-24": D[(D.day > DEV_END) & (D.day < "20261001")], "10-01 / 10-02": D[D.day >= "20261001"]}
    pd.set_option("display.width", 220)
    dev = sets["development 08-26..09-04"]
    print("development half: net bp by level and by the rank of the volume ahead (A = KuCoin only exit, B = Binance hedge at fee 1 bp); fills in brackets")
    dev = dev.assign(rb=pd.cut(dev["rank"], [-0.01, 0.10, 0.25, 0.50, 0.75, 1.0], labels=["<=10%", "10-25%", "25-50%", "50-75%", ">75%"]))
    for c, nm in (("ku", "A"), ("hd", "B")):
        t = dev.groupby(["d", "rb"], observed=True).apply(lambda g: f"{w(g, c):+.2f} ({len(g)})" if len(g) >= 5 else f"- ({len(g)})").unstack(1)
        print(f" {nm}:"); print(t.to_string())
    print("\nvolume ahead at the fills (BTC), development half, median by level: " + ", ".join(f"{d:g} bp: {dev[dev.d == d].V.median():.2f}" for d in cfg["deltas"]))
    choice = {}
    for c, nm, sel in (("ku", "A  KuCoin only, levels >= 4.5 bp", lambda g: g.d >= 4.5), ("hd", "B  Binance hedge at fee 1 bp, all levels", lambda g: g.d >= 0)):
        print(f"\n=== {nm}")
        best = None
        for q in QS:
            g = dev[sel(dev) & (dev["rank"] <= q)]
            days = sorted(dev.day.unique())
            usd = (g[c] * g.N / 1e4).sum() / len(days) if len(g) else 0.0
            print(f"   development  q {q:4.2f}: {line(g, c, days)}")
            if best is None or usd > best[1]:
                best = (q, usd)
        choice[c] = best[0]
        print(f"   -> chosen on the development half: q = {best[0]:.2f}")
        for name in ("TEST 09-05..09-24", "10-01 / 10-02"):
            T = sets[name]
            days = sorted(T.day.unique())
            for q in (best[0], 1.00):
                g = T[sel(T) & (T["rank"] <= q)]
                print(f"   {name:18s} q {q:4.2f}{' (no rule)' if q == 1 else '          '}: {line(g, c, days)}")
        # by level on the test half with the chosen q
        T = sets["TEST 09-05..09-24"]
        g = T[sel(T) & (T["rank"] <= best[0])]
        print("   test half by level (chosen q): " + ", ".join(f"{d:g} bp {w(g[g.d == d], c):+.2f} ({(g.d == d).sum()})" for d in cfg["deltas"] if (g.d == d).sum() >= 5))


if __name__ == "__main__":
    main()
