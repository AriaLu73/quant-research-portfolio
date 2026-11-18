#!/usr/bin/env python3
"""research5 MF-9: the KuCoin-only deep ladder (MF-8) on days WITHOUT order-by-order data - the 20 purchased days of
August / September - and, as a check of this simpler simulator, on 10-01 / 10-02 against the order-by-order replay.

Same rules as mf4_replay.py X2: fair value = Binance BTCUSDT last trade (seen d_bn ms after its trade time) + basis (median
of KuCoin mid - Binance price over the previous 300 s, 1 s grid); levels at fixed distances; a level is quoted only while
its distance >= kbuf x q99(|Binance move over tau| given the Binance trades of the last 100 ms) (table fitted on 10-02);
re-quote when the wanted price moved h bp: cancel effective tau_c ms later, new order resting tau_o ms later.
Differences forced by the data (public trades + best bid / ask grid only, no order ids):
  fills   QUEUE-FRONT (user's standing rule, never through-only): a KuCoin taker order (trades of one millisecond and one
          side) fills our order with its volume that traded at our price or through it; at our own price we are ahead of
          the other orders. An upper bound on our queue position. The taker's volume is fixed and shared from the best of
          our prices outwards. (The first version of this file, frozen as mm_xvl_r1, counted only volume strictly through
          our price - that convention is not allowed and its results are superseded.)
  exit    taker order H ms after the fill at the best bid / ask of the grid then, minus SLIP bp (in the order-by-order
          replay the mean slippage of the exit beyond the best price was 0.1-0.2 bp).
Result per fill = maker-signed (exit - entry) bp - SLIP + OUR_FEE rebate - 1.8 taker fee.
Usage: Python314/python.exe scripts/research5/mf9_sim.py <day YYYYMMDD> [config]      (writes data/research5/maker_families/mf9/)
       Python314/python.exe scripts/research5/mf9_sim.py report [config]
"""
import glob, gzip, json, os, sys, zipfile
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research5", "maker_families", "mf9q")
MFD = os.path.join(ROOT, "data", "research5", "maker_families")
MS = 1_000_000
SLIP, REBATE, TAKER = 0.2, 0.7, 1.8
HOLDS_MS = (100, 200, 500, 1000, 2000, 5000)
HEDGE_MS = (20, 100, 1000, 10000)
OCT = ("20261001", "20261002")
CONFIGS = {
    "N": dict(deltas=(4.5, 6.0, 7.5, 9.0, 12.0), size=1000, h=0.15, tau_o=1.5, tau_c=1.5, d_bn=2.0, kbuf=1.5, tau_tab="26.5"),     # normal
    "C": dict(deltas=(4.5, 6.0, 7.5, 9.0, 12.0), size=1000, h=0.15, tau_o=50.0, tau_c=50.0, d_bn=2.0, kbuf=1.5, tau_tab="50.0"),   # exchange congested
    "H": dict(deltas=(2.0, 3.5, 6.0, 9.0), size=1000, h=0.15, tau_o=1.5, tau_c=1.5, d_bn=2.0, kbuf=1.5, tau_tab="26.5"),           # the hedged ladder W1 (Binance fair value)
    "HS": dict(deltas=(2.0, 3.5, 6.0, 9.0), size=1000, h=0.15, tau_o=1.5, tau_c=1.5, d_bn=10.0, kbuf=1.5, tau_tab="26.5"),         # same, Binance data 10 ms late
    "L": dict(deltas=(2.0, 3.5, 4.5, 6.0, 7.5, 9.0, 12.0), size=1000, h=0.15, tau_o=1.5, tau_c=1.5, d_bn=2.0, kbuf=1.5, tau_tab="26.5"),   # wide ladder for the book rules (MF-10)
    "S": dict(deltas=(4.5, 6.0, 7.5, 9.0, 12.0), size=1000, h=0.15, tau_o=1.5, tau_c=1.5, d_bn=10.0, kbuf=1.5, tau_tab="26.5"),    # Binance data 10 ms late
}


def binance(day):
    if day in OCT:
        z = np.load(os.path.join(MFD, f"binance_BTCUSDT_{day}.npz"))
        return z["t"], z["p"]
    d = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    zf = zipfile.ZipFile(os.path.join(ROOT, "data", "research5", "binance_hist", f"BTCUSDT-aggTrades-{d}.zip"))
    df = pd.read_csv(zf.open(zf.namelist()[0]), usecols=["price", "transact_time"])
    t = df.transact_time.to_numpy(np.int64) * MS
    o = np.argsort(t, kind="stable")
    return t[o], df.price.to_numpy(float)[o]


def kucoin(day):
    """-> trades (ts ns, price, size in contracts, taker side +1 buy / -1 sell), grid (t ns, best bid, best ask)."""
    T, G = [], []
    if day in OCT:
        for f in sorted(glob.glob(os.path.join(ROOT, "data", "research5", "usdc_pairs", day, "??_XBTUSDTM_trades.jsonl.gz"))):
            try:
                with gzip.open(f, "rt") as fh:
                    for line in fh:
                        i = line.find("\t")
                        d = json.loads(line[i + 1:]).get("data") if i > 0 else None
                        if d and "price" in d:
                            T.append((int(d["ts"]), float(d["price"]), float(d["size"]), 1 if d["side"] == "buy" else -1))
            except (EOFError, OSError):
                pass
        gf = sorted(glob.glob(os.path.join(ROOT, "data", "research3", "px", "BTC-USDT-L3-2ms", f"grid_{day}_??.parquet")))
    else:
        for f in sorted(glob.glob(os.path.join(ROOT, "data", "oos", "ku_buyc", f"{day}_??", "kucoin", "swap", "BTC-USDT", "feed_raw", "ticks-*.jsonl.gz"))):
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    m = json.loads(line)
                    T.append((int(m["ts_ns"]), float(m["price"]), float(m["size"]) * 1000.0, 1 if m["side"] == "buy" else -1))
        gf = sorted(glob.glob(os.path.join(ROOT, "data", "research3", "px", "BTC-USDT-10ms", f"grid_{day}_??.parquet")))
    for f in gf:
        g = pd.read_parquet(f, columns=["t", "bb", "ba", "crossed"])
        g = g[~g.crossed]
        G.append(g[["t", "bb", "ba"]].to_numpy(float))
    T = np.array(sorted(T), float)
    G = np.concatenate(G)
    return T, G[np.argsort(G[:, 0], kind="stable")]


def sweeps(T):
    """Trades of one millisecond and one taker side -> list of (ts, taker side, [(tick, contracts)] best price first)."""
    out = []
    i, n = 0, len(T)
    while i < n:
        j = i
        while j < n and T[j, 0] == T[i, 0] and T[j, 3] == T[i, 3]:
            j += 1
        side = int(T[i, 3])
        lv = sorted(((round(T[k, 1] * 10), T[k, 2]) for k in range(i, j)), reverse=(side < 0))      # a seller hits the highest bids first
        out.append((int(T[i, 0]), side, lv))
        i = j
    return out


def simulate(day, cfg):
    bt, bp = binance(day)
    T, G = kucoin(day)
    gt = G[:, 0].astype(np.int64)
    at_b = lambda x: bp[np.clip(np.searchsorted(bt, x, side="right") - 1, 0, len(bp) - 1)]
    # basis on a 1 s grid, trailing 300 s median, known before
    sec = np.arange(gt[0] // 10**9 + 1, gt[-1] // 10**9) * 10**9
    kmid = (G[:, 1] + G[:, 2]) / 2
    gi = np.searchsorted(gt, sec, side="right") - 1
    stale = (sec - gt[np.clip(gi, 0, len(gt) - 1)]) > 5 * 10**9                      # no fresh KuCoin quote: no basis
    d = np.where(stale, np.nan, kmid[np.clip(gi, 0, len(gt) - 1)] - at_b(sec))
    basis = np.full(len(sec), np.nan)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        basis[300:] = np.nanmedian(np.lib.stride_tricks.sliding_window_view(d, 300), axis=1)[:-1]
        nvalid = np.r_[np.zeros(300), np.sum(np.isfinite(np.lib.stride_tricks.sliding_window_view(d, 300)), axis=1)[:-1]]
    basis[nvalid < 60] = np.nan

    fit = json.load(open(os.path.join(MFD, "mf5_fit_20261001.json" if day == "20261002" else "mf5_fit_20261002.json")))
    bk = np.array(fit["buckets"])
    tab = np.array([fit["buffer"][str(b)][cfg["tau_tab"]] for b in fit["buckets"]]) * cfg["kbuf"]

    # fair-value events: every Binance trade when we see it, plus a look 100 ms after a trade when no other trade came (activity has decayed)
    seen = bt + int(cfg["d_bn"] * MS)
    extra = seen[:-1][np.diff(seen) > 100 * MS] + 100 * MS + 1
    et = np.concatenate([seen, extra])
    order = np.argsort(et, kind="stable")
    et = et[order]
    ib = np.searchsorted(seen, et, side="right")                                    # Binance trades seen so far
    n100 = ib - np.searchsorted(seen, et - 100 * MS, side="right")
    buf = tab[np.searchsorted(bk, n100, side="right") - 1]
    bs = basis[np.clip(np.searchsorted(sec, et, side="right") - 1, 0, len(sec) - 1)]
    F = bp[np.clip(ib - 1, 0, len(bp) - 1)] + bs
    ok = np.isfinite(F) & (ib > 0)
    et, F, buf = et[ok], F[ok], buf[ok]

    SW = sweeps(T)
    st = np.array([s[0] for s in SW], np.int64)
    # merged event order: 0 = fair-value event, 1 = KuCoin sweep
    kinds = np.r_[np.zeros(len(et), np.int8), np.ones(len(st), np.int8)]
    times = np.r_[et, st]
    idx = np.r_[np.arange(len(et)), np.arange(len(st))]
    o = np.argsort(times, kind="stable")
    kinds, times, idx = kinds[o].tolist(), times[o].tolist(), idx[o].tolist()
    Fl, bufl = F.tolist(), buf.tolist()

    deltas, size = cfg["deltas"], cfg["size"]
    tau_o, tau_c = int(cfg["tau_o"] * MS), int(cfg["tau_c"] * MS)
    live = {}        # (side, level) -> [tick, left, cancel_at or None, want]      side 0 = bid, 1 = ask
    dying = []       # orders being cancelled: [side, tick, left, cancel_at]
    pend = {}        # (side, level) -> (tick, live_at)
    want_of = {}     # (side, level) -> the price asked for (the resting price may be clamped inside the touch)
    fills = []       # ts, side, level, tick, contracts
    placed = 0
    for kind, now, i in zip(kinds, times, idx):
        if pend:
            for key in [k for k, v in pend.items() if v[1] <= now]:
                tick, _ = pend.pop(key)
                j = np.searchsorted(gt, now, side="right") - 1
                if j >= 0:                                                           # post-only: stay inside the touch
                    if key[0] == 0 and tick >= round(G[j, 2] * 10):
                        tick = round(G[j, 2] * 10) - 1
                    elif key[0] == 1 and tick <= round(G[j, 1] * 10):
                        tick = round(G[j, 1] * 10) + 1
                live[key] = [tick, size, None, want_of.pop(key, tick)]
        if dying:
            dying = [x for x in dying if x[3] > now and x[2] > 0]
        if kind == 0:
            f, b = Fl[i], bufl[i]
            ht = cfg["h"] * f / 1e4 * 10
            for s in (0, 1):
                for k, dl in enumerate(deltas):
                    key = (s, k)
                    cur = live.get(key)
                    if dl < b:
                        if cur is not None:
                            dying.append([s, cur[0], cur[1], now + tau_c])
                            del live[key]
                        pend.pop(key, None)
                        continue
                    want = int(np.floor(f * (1 - dl / 1e4) * 10)) if s == 0 else int(np.ceil(f * (1 + dl / 1e4) * 10))
                    if key in pend:
                        continue
                    if cur is not None and cur[1] > 0 and abs(cur[3] - want) < ht:
                        continue
                    if cur is not None:
                        dying.append([s, cur[0], cur[1], now + tau_c])
                        del live[key]
                    pend[key] = (want, now + tau_o)
                    want_of[key] = want
                    placed += 1
        else:
            ts, side, lv = SW[i]
            s = 0 if side < 0 else 1                                                 # a taker sell hits our bids
            mine = [(k, v) for (ss, k), v in live.items() if ss == s and v[1] > 0] + [(-1, x) for x in dying if x[0] == s and x[2] > 0]
            if not mine:
                continue
            get_tick = lambda e: e[1][0] if e[0] >= 0 else e[1][1]
            mine.sort(key=lambda e: -get_tick(e) if s == 0 else get_tick(e))
            remaining = sum(q for _, q in lv)
            m = 0
            for tick, q in lv:
                while m < len(mine) and remaining > 0:
                    e = mine[m]
                    mt = get_tick(e)
                    if (mt >= tick) if s == 0 else (mt <= tick):                     # at or through our price: queue-front (upper bound)
                        left_i = 1 if e[0] >= 0 else 2
                        x = min(e[1][left_i], remaining)
                        e[1][left_i] -= x
                        remaining -= x
                        fills.append((ts, s, e[0], mt, x))
                        m += 1
                    else:
                        break
                if remaining <= 0:
                    break
                remaining -= min(q, remaining)
    A = np.array(fills, float).reshape(-1, 5)
    # exits
    EX = np.full((len(A), len(HOLDS_MS)), np.nan)
    for hk, h in enumerate(HOLDS_MS):
        x = A[:, 0].astype(np.int64) + h * MS
        j = np.searchsorted(gt, x, side="right") - 1
        fresh = (j >= 0) & ((x - gt[np.clip(j, 0, len(gt) - 1)]) < 5 * 10**9)
        px = np.where(A[:, 1] == 0, G[np.clip(j, 0, len(gt) - 1), 1], G[np.clip(j, 0, len(gt) - 1), 2])    # long exits at the bid, short at the ask
        EX[:, hk] = np.where(fresh, px, np.nan)
    os.makedirs(OUT, exist_ok=True)
    hours = len(np.unique(gt // (3600 * 10**9)))
    # hedge prices: Binance price L ms after the fill + basis at the fill (KuCoin terms), for L = 20, 100, 1000, 10000 ms
    ft = A[:, 0].astype(np.int64)
    bfill = basis[np.clip(np.searchsorted(sec, ft, side="right") - 1, 0, len(sec) - 1)]
    HB = np.stack([at_b(ft + l * MS) + bfill for l in HEDGE_MS], 1) if len(A) else np.zeros((0, len(HEDGE_MS)))
    return A, EX, hours, placed, HB


def run(day, name):
    A, EX, hours, placed, HB = simulate(day, CONFIGS[name])
    np.savez_compressed(os.path.join(OUT, f"{name}_{day}.npz"), fills=A, exits=EX, hours=hours, placed=placed, hedge=HB)
    print(f"{day} {name}: hours {hours}, fills {len(A)}, contracts {A[:, 4].sum() if len(A) else 0:.0f}, orders {placed:,}", flush=True)


def report(name):
    cfg = CONFIGS[name]
    rows = []
    for p in sorted(glob.glob(os.path.join(OUT, f"{name}_*.npz"))):
        z = np.load(p)
        rows.append((os.path.basename(p)[len(name) + 1:-4], z["fills"], z["exits"], int(z["hours"])))
    for title, sel in (("August / September (purchased days, no order-by-order data)", lambda d: d not in OCT), ("10-01 / 10-02 (check against the order-by-order replay X2)", lambda d: d in OCT)):
        R = [r for r in rows if sel(r[0])]
        if not R:
            continue
        A = np.concatenate([r[1] for r in R]); EX = np.concatenate([r[2] for r in R])
        dayix = np.concatenate([np.full(len(r[1]), k) for k, r in enumerate(R)])
        days = sum(r[3] for r in R) / 24.0
        px = A[:, 3] / 10.0
        sg = np.where(A[:, 1] == 0, 1.0, -1.0)
        N = A[:, 4] * 0.001 * px
        print(f"\n=== {name} | {title}: {len(R)} days ({days:.1f} days of data), fills {len(A):,}, ${N.sum() / 1e6:.2f}M (${N.sum() / 1e6 / days:.2f}M per day)")
        print("   fills per level: " + ", ".join(f"{d:g} bp: {(A[:, 2] == k).sum()} (${N[A[:, 2] == k].sum() / 1e6:.2f}M)" for k, d in enumerate(cfg["deltas"])))
        for lab, m0 in (("all levels", A[:, 2] >= 0), (">= 6 bp", A[:, 2] >= 1), (">= 7.5 bp", A[:, 2] >= 2)):
            print(f"   {lab}:  {'hold ms':>8s} {'net bp':>7s} {'se':>5s} {'$ per day':>10s} {'days > 0':>9s} {'worst day $':>12s} {'best day $':>11s} {'top-5 fills / profit':>21s}   by level: " + "  ".join(f"{d:g}" for d in cfg["deltas"]))
            for hk, h in enumerate(HOLDS_MS):
                ok = m0 & np.isfinite(EX[:, hk])
                if ok.sum() < 5:
                    continue
                net = sg * (EX[:, hk] - px) / px * 1e4 - SLIP + REBATE - TAKER
                usd = net * N / 1e4
                per = np.array([usd[ok & (dayix == k)].sum() for k in range(len(R))])
                mean = np.average(net[ok], weights=N[ok])
                se = np.sqrt(np.average((net[ok] - mean) ** 2, weights=N[ok]) / ok.sum())
                top = np.sort(usd[ok])[-5:].sum() / usd[ok].sum() if usd[ok].sum() > 0 else np.nan
                lv = [f"{np.average(net[ok & (A[:, 2] == k)], weights=N[ok & (A[:, 2] == k)]):+.2f}" if (ok & (A[:, 2] == k)).sum() >= 5 else "-" for k in range(len(cfg["deltas"]))]
                print(f"               {h:8d} {mean:7.2f} {se:5.2f} {usd[ok].sum() / days:10,.0f} {np.mean(per > 0):9.0%} {per.min():12,.0f} {per.max():11,.0f} {top:21.0%}   " + "  ".join(lv))
        if not sel("20261001"):
            usd = (sg * (EX[:, 2] - px) / px * 1e4 - SLIP + REBATE - TAKER) * N / 1e4
            print("   by day (>= 6 bp, hold 500 ms): " + ", ".join(f"{r[0][4:]} {np.nansum(usd[(dayix == k) & (A[:, 2] >= 1)]):+,.0f}" for k, r in enumerate(R)))


def report_hedged(name):
    """Entry edge of the fills against a hedge on Binance (as MF-4 / MF-7): by period, level and day."""
    cfg = CONFIGS[name]
    for title, sel in (("August / September", lambda d: d not in OCT), ("10-01 / 10-02", lambda d: d in OCT)):
        R = []
        for p in sorted(glob.glob(os.path.join(OUT, f"{name}_*.npz"))):
            day = os.path.basename(p)[len(name) + 1:-4]
            z = np.load(p)
            if sel(day) and len(z["fills"]):
                R.append((day, z["fills"], z["hedge"], int(z["hours"])))
        if not R:
            continue
        A = np.concatenate([r[1] for r in R]); HB = np.concatenate([r[2] for r in R])
        dayix = np.concatenate([np.full(len(r[1]), k) for k, r in enumerate(R)])
        days = sum(r[3] for r in R) / 24.0
        px = A[:, 3] / 10.0
        sg = np.where(A[:, 1] == 0, 1.0, -1.0)
        N = A[:, 4] * 0.001 * px
        E = sg[:, None] * (HB - px[:, None]) / px[:, None] * 1e4
        print()
        print(f"=== {name} hedged on Binance | {title}: {len(R)} days with fills, ${N.sum() / 1e6:.2f}M (${N.sum() / 1e6 / days:.2f}M per day)")
        print(f"   {'level':>10s} {'fills':>6s} {'$M':>7s} " + " ".join(f"{'edge ' + str(l) + ' ms':>14s}" for l in HEDGE_MS) + f" {'break-even fee':>15s} {'$ per day at fee 1':>19s} {'days > 0 (fee 1)':>17s} {'worst day $':>12s}")
        for lab, m in [("all", np.ones(len(A), bool))] + [(f"{d:g} bp", A[:, 2] == k) for k, d in enumerate(cfg["deltas"])]:
            ok = m & np.isfinite(E[:, 0])
            if ok.sum() < 5:
                continue
            e = [np.average(E[ok & np.isfinite(E[:, j]), j], weights=N[ok & np.isfinite(E[:, j])]) for j in range(len(HEDGE_MS))]
            usd = (E[:, 0] + REBATE - 1.0) * N / 1e4
            per = np.array([usd[ok & (dayix == k)].sum() for k in range(len(R))])
            print(f"   {lab:>10s} {ok.sum():6d} {N[ok].sum() / 1e6:7.2f} " + " ".join(f"{x:14.2f}" for x in e) + f" {e[0] + REBATE:15.2f} {usd[ok].sum() / days:19,.0f} {np.mean(per > 0):17.0%} {per.min():12,.0f}")


if __name__ == "__main__":
    if sys.argv[1] == "hedged":
        report_hedged(sys.argv[2])
    elif sys.argv[1] == "report":
        report(sys.argv[2] if len(sys.argv) > 2 else "N")
    else:
        run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "N")
