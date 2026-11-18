#!/usr/bin/env python3
"""research3 PX-8: quote around the price of the venue where price discovery happens, not around KuCoin's own mid.
Sources: Makarov & Schoar 2019 (AEA P&P 109: price discovery sits on the most liquid venues; a venue whose price deviates
contributes little); Dimpfl & Peter 2021 (JFM 54: crypto transaction prices are mostly noise - signal-to-noise 36 % against
about 90 % on NYSE / NASDAQ - so a follower's own price is a poor estimate of the efficient price; the information leadership
share picks the leader). Binance BTCUSDT perpetual is the leader for KuCoin BTC-USDT.
  fair(t)  = Binance last trade price at t - L, times exp(basis), basis = mean of ln(KuCoin mid / Binance price) over the past 60 s
  gap(t)   = ln(KuCoin mid / fair), bp          (KuCoin rich when positive)
A. Signal quality by the IC rules: hourly rank IC of -gap against KuCoin's return over the next 1 s and 10 s, for several
   information delays L; and what it adds to the order-book model (ridge.json), fitted on 10-01, read on 10-02.
B. Quoting: every REAL maker fill of BTC-USDT (real_maker.py) is scored by q = side x (fair - fill price) / price, bp: how far
   on the right side of the leader's fair price the quote was when it was hit (information L ms old). Net = 10 s markout against
   the L3 mid + OUR_FEE, per fill and per contract, by decile of q, and for the rule "be in the book only when q >= theta".
Data: Binance aggTrades (data/research5/binance_hist/BTCUSDT-aggTrades-<day>.zip) and our L3 days 10-01 / 10-02. Descriptive:
these two days have been used before; a quoting rule built on this needs a fresh day.
usage: Python314/python.exe scripts/research3/px8_leader.py"""
import glob, math, os, sys, warnings, zipfile
import numpy as np, pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_ic as P          # noqa: E402
import px_cancel as C      # noqa: E402
import l3_mid as LM        # noqa: E402

ROOT = P.ROOT
BN = os.path.join(ROOT, "data", "research5", "binance_hist")
GRID = os.path.join(P.PX, "BTC-USDT-L3")
REAL = os.path.join(P.PX, "real")
OUT = os.path.join(P.PX, "px8")
MS = 1_000_000
BASIS_STEPS = 6000                 # 60 s of 10 ms steps
DAYS = ("20261001", "20261002")


def binance(day):
    z = zipfile.ZipFile(os.path.join(BN, "BTCUSDT-aggTrades-%s-%s-%s.zip" % (day[:4], day[4:6], day[6:])))
    d = pd.read_csv(z.open(z.namelist()[0]), usecols=["price", "transact_time"])
    return d.transact_time.to_numpy(np.int64) * MS, d.price.to_numpy()


def day_grid(day):
    parts = []
    for f in sorted(glob.glob(os.path.join(GRID, "grid_%s_??.parquet" % day))):
        g = pd.read_parquet(f, columns=["t", "bb", "ba", "crossed"])
        t = g.t.to_numpy(np.int64)
        mid = np.where(g.crossed.to_numpy() | (t < t[0] + 120_000 * MS), np.nan, (g.bb.to_numpy() + g.ba.to_numpy()) / 2)
        parts.append(pd.DataFrame(dict(t=t, mid=mid, hour=int(os.path.basename(f)[-10:-8]))))
    return pd.concat(parts, ignore_index=True)


def gap_series(G, bt, bp, lag_ms):
    T = G.t.to_numpy()
    i = np.searchsorted(bt, T - lag_ms * MS, side="right") - 1
    pb = np.where(i >= 0, bp[np.clip(i, 0, len(bp) - 1)], np.nan)
    stale = (T - lag_ms * MS - bt[np.clip(i, 0, len(bt) - 1)]) > 5_000 * MS
    pb[stale] = np.nan
    raw = np.log(G.mid.to_numpy()) - np.log(pb)
    basis = P.trailing_mean(raw, BASIS_STEPS)
    return (raw - basis) * 1e4, basis, pb


def ic_by_hour(x, y, hours):
    out = []
    for h in np.unique(hours):
        m = hours == h
        v = P.rank_ic(x[m][::5], y[m][::5])[0]
        if v == v:
            out.append(v)
    v = np.array(out)
    return v.mean(), v.std(), len(v), (v > 0).sum()


def main():
    os.makedirs(OUT, exist_ok=True)
    lines = []
    keep = {}
    for day in DAYS:
        bt, bp = binance(day)
        G = day_grid(day)
        lm = np.log(G.mid.to_numpy())
        hours = G.hour.to_numpy()
        y = {"1s": np.r_[(lm[100:] - lm[:-100]) * 1e4, np.full(100, np.nan)], "10s": np.r_[(lm[1000:] - lm[:-1000]) * 1e4, np.full(1000, np.nan)]}
        lines.append("\n%s  A. hourly rank IC of -gap (KuCoin rich -> expect KuCoin to fall) against KuCoin's next return" % day)
        for L in (0, 2, 5, 10, 25, 50, 200):
            gap, basis, pb = gap_series(G, bt, bp, L)
            a = ic_by_hour(-gap, y["1s"], hours)
            b = ic_by_hour(-gap, y["10s"], hours)
            lines.append("   information %3d ms old: 1 s IC %.3f (sd %.3f, %d/%d hours > 0)   10 s IC %.3f (sd %.3f, %d/%d)" % (L, a[0], a[1], a[3], a[2], b[0], b[1], b[3], b[2]))
            if L == 5:
                keep[day] = dict(G=G, gap=gap, basis=basis, y=y, hours=hours, bt=bt, bp=bp)
        sd = np.nanstd(keep[day]["gap"])
        q = np.nanquantile(np.abs(keep[day]["gap"]), [.5, .9, .99])
        lines.append("   gap (5 ms old): sd %.2f bp; |gap| median %.2f, 90 %% %.2f, 99 %% %.2f bp" % (sd, *q))
    # A2: what the leader adds to the order-book model (v1, 10 ms grid): fit on 10-01, read on 10-02
    preds = {}
    for day in DAYS:
        pr = C.predictions(day, C.CFG["v1"])
        K = keep[day]
        T = K["G"].t.to_numpy()
        j = np.clip(np.searchsorted(pr["t"], T, side="right") - 1, 0, len(pr["t"]) - 1)
        p = pr["1s"][j].astype(float)
        p[pr["t"][j] != T] = np.nan
        preds[day] = p
    K0, K1 = keep[DAYS[0]], keep[DAYS[1]]
    for h in ("1s", "10s"):
        X0 = np.c_[np.ones(len(K0["gap"])), preds[DAYS[0]], -K0["gap"]]
        m = np.isfinite(X0).all(1) & np.isfinite(K0["y"][h])
        beta = np.linalg.lstsq(X0[m], K0["y"][h][m], rcond=None)[0]
        comb = beta[0] + beta[1] * preds[DAYS[1]] + beta[2] * (-K1["gap"])
        a = ic_by_hour(preds[DAYS[1]], K1["y"][h], K1["hours"])
        b = ic_by_hour(-K1["gap"], K1["y"][h], K1["hours"])
        c = ic_by_hour(comb, K1["y"][h], K1["hours"])
        lines.append("\nA2. %s return on 10-02: order-book model IC %.3f | leader gap alone %.3f | both (weights from 10-01: book %.3f, gap %.3f) %.3f (sd %.3f, %d/%d hours > 0)" % (
            h, a[0], b[0], beta[1], beta[2], c[0], c[1], c[3], c[2]))
        mm = np.isfinite(comb) & np.isfinite(K1["y"][h])
        dq = pd.qcut(pd.Series(comb[mm]).rank(method="first"), 10, labels=False)
        tab = pd.Series(K1["y"][h][mm]).groupby(dq.to_numpy()).mean()
        lines.append("     realised %s return by decile of the combined prediction (bp): %s" % (h, " ".join("%+.2f" % v for v in tab)))
    # B: real maker fills scored against the leader's fair price
    for day in DAYS:
        K = keep[day]
        T = K["G"].t.to_numpy()
        mid = LM.L3Mid(day)
        fs = sorted(glob.glob(os.path.join(REAL, "fills_%s_??.npy" % day)))
        A = np.concatenate([np.c_[np.load(f), np.full(len(np.load(f)), int(f[-6:-4]))] for f in fs])
        ts = A[:, 0].astype(np.int64)
        sg, px, sz, hr = A[:, 1], A[:, 2], A[:, 3], A[:, 10]
        net = sg * (mid.at(ts + 10_000_000_000) - px) / px * 1e4 + 0.7
        lines.append("\n%s  B. real maker fills (%d) scored by q = side x (leader fair - fill price), bp" % (day, len(A)))
        for L in (2.0, 6.5, 26.5):
            g = np.clip(np.searchsorted(T, ts - int(L * MS), side="right") - 1, 0, len(T) - 1)
            i = np.searchsorted(K["bt"], ts - int(L * MS), side="right") - 1
            fair = K["bp"][np.clip(i, 0, len(K["bp"]) - 1)] * np.exp(K["basis"][g])
            q = sg * (fair - px) / px * 1e4
            ok = np.isfinite(q) & np.isfinite(net)
            ric = P.rank_ic(q[ok], net[ok])
            lines.append("  information %.1f ms old: rank IC of q with the fill's net result %.3f (Pearson %.3f), %d fills" % (L, ric[0], ric[1], ok.sum()))
            dq = pd.qcut(pd.Series(q[ok]).rank(method="first"), 10, labels=False).to_numpy()
            row1 = " ".join("%+.2f" % net[ok][dq == k].mean() for k in range(10))
            row2 = " ".join("%+.2f" % ((net[ok][dq == k] * sz[ok][dq == k]).sum() / sz[ok][dq == k].sum()) for k in range(10))
            row0 = " ".join("%+.2f" % np.median(q[ok][dq == k]) for k in range(10))
            lines.append("    decile of q (median q):   %s" % row0)
            lines.append("    net per fill:             %s" % row1)
            lines.append("    net per contract:         %s" % row2)
            hours = np.unique(hr)
            for th in (-99, -0.5, 0.0, 0.25, 0.5, 1.0):
                m = ok & (q >= th)
                per_h = np.array([(net[m & (hr == h)] * np.minimum(sz[m & (hr == h)], 60)).sum() for h in hours])
                w = np.minimum(sz[m], 60).sum()
                t = per_h.mean() / (per_h.std(ddof=1) / math.sqrt(len(per_h))) if per_h.std() > 0 else float("nan")
                lines.append("    in the book only when q >= %+5.2f: fills/h %7.1f  net per fill %+.3f  per contract (fill capped at 0.06 BTC) %+.3f  t(hour) %+5.2f  hours > 0: %d/%d" % (
                    th, m.sum() / len(hours), net[m].mean(), per_h.sum() / w, t, (per_h > 0).sum(), len(hours)))
    rep = "\n".join(lines)
    open(os.path.join(OUT, "px8_report.txt"), "w", encoding="utf-8").write(rep)
    print(rep)
    print("PX8_DONE")


if __name__ == "__main__":
    main()
