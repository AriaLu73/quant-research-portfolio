#!/usr/bin/env python3
"""research3 PX-7: does the within-second clock matter for a maker on KuCoin BTC-USDT?
Source: Shynkevich 2026 (Economics Letters 266, 113026): on Binance spot and perpetuals, trading volume and trade count peak in
the first 100 ms of every second, and those trades carry a disproportionate share of the permanent price change (excess weighted
price contribution per trade of the first 100 ms bin: BTC USDT-margined perp +0.075, t 14; ETH +0.161), i.e. they are the
informed, algorithmic ones; bins 6-7 (500-700 ms) are below par.
Here, on the September L2 + trades of KuCoin BTC-USDT (data/oos/ku_buyc, 20 days): per 50 ms bin of the second,
  share of taker orders and of taker volume (uniform = 5 % per bin);
  the maker's result when a real taker order trades at the displayed best: 1 s and 10 s markout + OUR_FEE rebate,
  per fill and per contract (size-weighted).
Training days 08-26 ... 09-07 and out-of-sample days 09-10 ... 09-24 are reported separately.
usage: Python314/python.exe scripts/research3/px7_subsecond.py"""
import glob, gzip, json, math, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_ic as P      # noqa: E402

ROOT = P.ROOT
GRID = os.path.join(P.PX, "BTC-USDT")
TICKS = os.path.join(ROOT, "data", "oos", "ku_buyc")
OUT = os.path.join(P.PX, "px7")
NB, BIN_MS = 20, 50
TICK = 0.1
REBATE = OUR_FEE


def hour(slot):
    f = glob.glob(os.path.join(TICKS, slot, "kucoin", "swap", "BTC-USDT", "feed_raw", "ticks-*.jsonl.gz"))
    gp = os.path.join(GRID, "grid_%s.parquet" % slot)
    if not f or not os.path.exists(gp):
        return None
    g = pd.read_parquet(gp, columns=["t", "bb", "ba", "crossed"])
    T, bb, ba = g.t.to_numpy(np.int64), g.bb.to_numpy(), g.ba.to_numpy()
    ok = ~g.crossed.to_numpy()
    mid = (bb + ba) / 2
    agg = {}
    with gzip.open(f[0], "rt") as fh:
        for line in fh:
            m = json.loads(line)
            k = (int(m["ts_ns"]), m["side"])
            a = agg.get(k)
            if a is None:
                agg[k] = [float(m["price"]), float(m["size"])]
            else:
                a[1] += float(m["size"])
    if not agg:
        return None
    ts = np.array([k[0] for k in agg], np.int64)
    s = np.array([-1 if k[1] == "buy" else 1 for k in agg])          # maker side
    px = np.array([v[0] for v in agg.values()])
    sz = np.array([v[1] for v in agg.values()])
    b = ((ts // 1_000_000) % 1000) // BIN_MS
    i = np.clip(np.searchsorted(T, ts, side="right") - 1, 0, len(T) - 1)
    res = np.zeros((NB, 8))
    touch = np.where(s > 0, bb[i], ba[i])
    at = ok[i] & (np.abs(px - touch) < TICK / 2)
    out = {}
    for h, nm in ((1, "1"), (10, "10")):
        j = np.searchsorted(T, ts + h * 1_000_000_000, side="right") - 1
        good = at & (ts + h * 1_000_000_000 <= T[-1]) & ok[np.clip(j, 0, len(T) - 1)]
        out[nm] = (good, s * (mid[np.clip(j, 0, len(T) - 1)] - px) / px * 1e4 + REBATE)
    for k in range(NB):
        m = b == k
        res[k, 0] = m.sum()
        res[k, 1] = sz[m].sum()
        g10, n10 = out["10"]
        g1, n1 = out["1"]
        mm = m & g10
        res[k, 2] = mm.sum()
        res[k, 3] = n10[mm].sum()
        res[k, 4] = sz[mm].sum()
        res[k, 5] = (n10[mm] * sz[mm]).sum()
        mm1 = m & g1
        res[k, 6] = mm1.sum()
        res[k, 7] = n1[mm1].sum()
    return res


def main():
    os.makedirs(OUT, exist_ok=True)
    slots = sorted(os.path.basename(f)[5:-8] for f in glob.glob(os.path.join(GRID, "grid_*.parquet")))
    rows = {}
    for k, slot in enumerate(slots):
        r = hour(slot)
        if r is not None:
            rows[slot] = r
        if k % 60 == 0:
            print("..", slot, flush=True)
    np.savez(os.path.join(OUT, "subsecond.npz"), slots=np.array(list(rows)), data=np.stack(list(rows.values())))
    lines = []
    for part, days in (("training days 08-26 ... 09-07", P.TRAIN), ("out-of-sample days 09-10 ... 09-24", P.OOS)):
        H = np.stack([v for s, v in rows.items() if s[:8] in days])          # hours x bins x 8
        tot = H.sum(0)
        lines.append("\n%s: %d hours, %.2f million taker orders, %.0f BTC" % (part, len(H), tot[:, 0].sum() / 1e6, tot[:, 1].sum()))
        lines.append("  %-12s %8s %8s | %10s %10s %10s | %s" % ("ms of second", "orders%", "volume%", "net/fill", "net/BTC", "1 s/fill", "t of (bin net/fill - hour net/fill) over hours"))
        hour_mean = H[:, :, 3].sum(1) / np.maximum(H[:, :, 2].sum(1), 1)
        for k in range(NB):
            with np.errstate(invalid="ignore", divide="ignore"):
                d = H[:, k, 3] / H[:, k, 2] - hour_mean
            d = d[np.isfinite(d)]
            t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if len(d) > 2 else float("nan")
            lines.append("  %4d-%-7d %7.2f%% %7.2f%% | %+10.3f %+10.3f %+10.3f | %+6.2f" % (
                k * BIN_MS, (k + 1) * BIN_MS, 100 * tot[k, 0] / tot[:, 0].sum(), 100 * tot[k, 1] / tot[:, 1].sum(),
                tot[k, 3] / tot[k, 2], tot[k, 5] / tot[k, 4], tot[k, 7] / tot[k, 6], t))
        lines.append("  all          %7.2f%% %7.2f%% | %+10.3f %+10.3f %+10.3f" % (100, 100, tot[:, 3].sum() / tot[:, 2].sum(), tot[:, 5].sum() / tot[:, 4].sum(), tot[:, 7].sum() / tot[:, 6].sum()))
    rep = "\n".join(lines)
    open(os.path.join(OUT, "px7_report.txt"), "w", encoding="utf-8").write(rep)
    print(rep)


if __name__ == "__main__":
    main()
