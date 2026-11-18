#!/usr/bin/env python3
"""research3 PX-1 step 1: 100 ms grid of book state and cumulative flows from the cleaned L2 slices (data/oos/ku_buyc).
Pre-registration: docs/research3/px_price_model_2026-10-03.md.
Per grid point t (state just before the first message at or after t):
  bb, ba (prices), qb1..qb5 / qa1..qa5 (sizes of the five best levels), crossed (bb >= ba),
  ofi1..ofi5   cumulative order-flow imbalance of level m since the start of the hour (Cont, Kukanov & Stoikov 2014 for m = 1,
               Xu, Gould & Howison 2019 for the deeper levels): e = 1{Pb >= Pb'} qb - 1{Pb <= Pb'} qb' - 1{Pa <= Pa'} qa + 1{Pa >= Pa'} qa'
  tv, tn       cumulative signed taker volume (buy +) and taker trade count since the start of the hour (trades with ts <= t)
usage: Python314/python.exe scripts/research3/px_grid.py BTC-USDT,ETH-USDT 20260826,... [workers | shard i/n] [--step=10] [--hours=02,08,14,20]
output: data/research3/px/<symbol>/grid_<day>_<hh>.parquet"""
import glob, gzip, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd
from sortedcontainers import SortedDict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "data", "oos", "ku_buyc")
OUT = os.path.join(ROOT, "data", "research3", "px")
def _opt(name, default):
    """--name=value anywhere on the command line (removed from sys.argv); the detached launcher does not pass environment."""
    for a in list(sys.argv):
        if a.startswith("--%s=" % name):
            sys.argv.remove(a)
            return a.split("=", 1)[1]
    return default


STEP_MS = int(_opt("step", "100"))                   # grid step, ms
STEP_NS = STEP_MS * 1_000_000
HOURS = [h for h in _opt("hours", "").split(",") if h]      # e.g. 02,08,14,20; empty = all
L = 5


def levels(book, n):
    out = []
    for i in range(min(n, len(book))):
        k, v = book.peekitem(i)
        out.append((abs(k), v))
    while len(out) < n:
        out.append((np.nan, 0.0))
    return out


def one(job):
    sym, slot = job
    d = os.path.join(SRC, slot, "kucoin", "swap", sym, "feed_raw")
    fd = glob.glob(os.path.join(d, "depth_deltas-*.jsonl.gz"))
    ft = glob.glob(os.path.join(d, "ticks-*.jsonl.gz"))
    out = os.path.join(OUT, sym if STEP_MS == 100 else "%s-%dms" % (sym, STEP_MS), "grid_%s.parquet" % slot)
    if not fd or os.path.exists(out):
        return slot, "skip"
    tr = []
    if ft:
        with gzip.open(ft[0], "rt") as fh:
            for line in fh:
                m = json.loads(line)
                tr.append((int(m["ts_ns"]), (1.0 if m["side"] == "buy" else -1.0) * float(m["size"])))
    with gzip.open(fd[0], "rt") as fh:
        df = grid_from((json.loads(line) for line in fh), tr, STEP_NS)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    df.to_parquet(out + ".tmp", index=False)
    os.replace(out + ".tmp", out)
    return slot, len(df)


def grid_from(msgs, tr, step_ns):
    """Grid of book state and cumulative flows. msgs: iterable of {"ts_ns", "bids": [[p, q]], "asks": [[p, q]], "snapshot"}
    with q = new absolute size at that price (0 = level gone); tr: [(ts_ns, signed taker size)], or None when the trades come
    inside msgs as m["trade"] (counted from the next grid point on)."""
    stream = tr is None                              # trades arrive inside msgs as m["trade"] (signed size), in feed order
    tr = sorted(tr or [])
    tts = np.array([x[0] for x in tr], np.int64)
    tcv = np.cumsum([x[1] for x in tr]) if tr else np.zeros(0)
    tv_run, tn_run = 0.0, 0
    bids, asks = SortedDict(), SortedDict()          # bids keyed by -price
    prev = None
    ofi = np.zeros(L)
    ncol = 3 + 2 * L + L + 2
    chunks, buf, nb = [], np.empty((65536, ncol)), 0
    tgrid = []
    nxt = None
    if True:
        for m in msgs:
            ts = int(m["ts_ns"])
            if nxt is None:
                nxt = (ts // step_ns + 1) * step_ns
            while ts >= nxt and prev is not None:
                bl, al = prev
                if stream:
                    tvk, tnk = tv_run, float(tn_run)
                else:
                    k = np.searchsorted(tts, nxt, side="right")
                    tvk, tnk = (float(tcv[k - 1]) if k else 0.0), float(k)
                if nb == len(buf):
                    chunks.append(buf)
                    buf, nb = np.empty((65536, ncol)), 0
                buf[nb] = [0.0, bl[0][0], al[0][0]] + [x[1] for x in bl] + [x[1] for x in al] + list(ofi) + [tvk, tnk]
                tgrid.append(nxt)
                nb += 1
                nxt += step_ns
            if stream and "trade" in m:
                tv_run += m["trade"]
                tn_run += 1
            if m.get("snapshot"):
                bids.clear()
                asks.clear()
                prev = None
            for p, q in m.get("bids", ()):
                p, q = float(p), float(q)
                if q > 0:
                    bids[-p] = q
                else:
                    bids.pop(-p, None)
            for p, q in m.get("asks", ()):
                p, q = float(p), float(q)
                if q > 0:
                    asks[p] = q
                else:
                    asks.pop(p, None)
            if not bids or not asks:
                continue
            bl, al = levels(bids, L), levels(asks, L)
            if prev is not None:
                pbl, pal = prev
                for i in range(L):
                    pb, qb = bl[i]
                    pb0, qb0 = pbl[i]
                    pa, qa = al[i]
                    pa0, qa0 = pal[i]
                    e = 0.0
                    if pb == pb and pb0 == pb0:
                        e += (qb if pb >= pb0 else 0.0) - (qb0 if pb <= pb0 else 0.0)
                    if pa == pa and pa0 == pa0:
                        e += -(qa if pa <= pa0 else 0.0) + (qa0 if pa >= pa0 else 0.0)
                    ofi[i] += e
            prev = (bl, al)
    cols = ["t", "bb", "ba"] + ["qb%d" % i for i in range(1, L + 1)] + ["qa%d" % i for i in range(1, L + 1)] + \
           ["ofi%d" % i for i in range(1, L + 1)] + ["tv", "tn"]
    df = pd.DataFrame(np.concatenate(chunks + [buf[:nb]]), columns=cols)
    df["t"] = np.array(tgrid, np.int64)               # int64 ns: a float64 column would lose the last digits
    df["crossed"] = df.bb >= df.ba
    return df


def main():
    syms = sys.argv[1].split(",")
    days = sys.argv[2].split(",")
    arg = sys.argv[3] if len(sys.argv) > 3 else "6"
    jobs = [(s, os.path.basename(p)) for s in syms for d in days for p in sorted(glob.glob(os.path.join(SRC, d + "_??")))
            if not HOURS or os.path.basename(p)[-2:] in HOURS]
    print(len(jobs), "slices", flush=True)
    if "/" in arg:                                   # shard i/n: this process alone, one slice after another
        i, n = map(int, arg.split("/"))
        for k, job in enumerate(jobs):
            if k % n == i:
                slot, rows = one(job)
                print(job[0], slot, rows, flush=True)
        print("PX_GRID_DONE", flush=True)
        return
    workers = int(arg)
    with ProcessPoolExecutor(workers) as ex:
        for i, (slot, n) in enumerate(ex.map(one, jobs, chunksize=1)):
            if i % 24 == 0:
                print(i, slot, n, flush=True)
    print("PX_GRID_DONE", flush=True)


if __name__ == "__main__":
    main()
