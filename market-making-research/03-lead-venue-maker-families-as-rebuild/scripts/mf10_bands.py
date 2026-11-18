#!/usr/bin/env python3
"""research5 MF-10: how much resting volume lies between the touch and each quote distance on KuCoin BTC-USDT.

User 2026-10-05: the ladder had no rule that uses the book. For the book-based rules we need, every 100 ms and per side,
the cumulative resting size (BTC) within d bp of the best price, d in BANDS: an order of ours at distance d is reached only
after a taker has eaten about that much.
  August / September  purchased, cleaned L2 increments (data/oos/ku_buyc/<day>_<hh>/.../depth_deltas-*.jsonl.gz, absolute sizes).
  10-01 / 10-02       our own L2 recording (data/research5/usdc_pairs/<day>/<hh>_XBTUSDTM_l2 + _snap): the book is reset to
                      every REST snapshot (5 minutes) and increments with a later sequence are applied; sizes in contracts.
Output: data/research5/maker_families/bands_<day>.npz  t (ns), vb / va [n, len(BANDS)] (BTC), bb, ba.
Usage: Python314/python.exe scripts/research5/mf10_bands.py <YYYYMMDD>
"""
import glob, gzip, json, os, sys
import numpy as np
from sortedcontainers import SortedDict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research5", "maker_families")
BANDS = (1.0, 2.0, 3.5, 4.5, 6.0, 7.5, 9.0, 12.0)
STEP = 100_000_000
OCT = ("20261001", "20261002")


def cum_within(book, best, bid):
    """Cumulative size within each band of the best price. book: SortedDict (bids keyed by -price)."""
    out = [0.0] * len(BANDS)
    lim = [best * (1 - d / 1e4) if bid else best * (1 + d / 1e4) for d in BANDS]
    far = lim[-1]
    acc, k = 0.0, 0
    for key, q in book.items():
        p = -key if bid else key
        if (p < far) if bid else (p > far):
            break
        while k < len(BANDS) and ((p < lim[k]) if bid else (p > lim[k])):
            out[k] = acc
            k += 1
        acc += q
    for j in range(k, len(BANDS)):
        out[j] = acc
    return out


class Builder:
    def __init__(self):
        self.bids, self.asks = SortedDict(), SortedDict()
        self.nxt = None
        self.t, self.vb, self.va, self.bb, self.ba = [], [], [], [], []

    def tick(self, ts):
        if self.nxt is None:
            self.nxt = (ts // STEP + 1) * STEP
        while ts >= self.nxt:
            if self.bids and self.asks:
                bb, ba = -self.bids.peekitem(0)[0], self.asks.peekitem(0)[0]
                if bb < ba:
                    self.t.append(self.nxt); self.bb.append(bb); self.ba.append(ba)
                    self.vb.append(cum_within(self.bids, bb, True)); self.va.append(cum_within(self.asks, ba, False))
            self.nxt += STEP

    def set(self, side_bid, p, q):
        book, key = (self.bids, -p) if side_bid else (self.asks, p)
        if q > 0:
            book[key] = q
        else:
            book.pop(key, None)

    def save(self, day):
        np.savez_compressed(os.path.join(OUT, f"bands_{day}.npz"), t=np.array(self.t, np.int64), vb=np.array(self.vb, np.float32),
                            va=np.array(self.va, np.float32), bb=np.array(self.bb), ba=np.array(self.ba), bands=np.array(BANDS))
        print(f"{day}: {len(self.t):,} grid points; median volume within {BANDS} bp of the best bid: " +
              ", ".join(f"{x:.2f}" for x in np.median(np.array(self.vb), axis=0)), flush=True)


def september(day):
    B = Builder()
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "oos", "ku_buyc", f"{day}_??", "kucoin", "swap", "BTC-USDT", "feed_raw", "depth_deltas-*.jsonl.gz"))):
        B.bids.clear(); B.asks.clear()                                  # every hour slice starts with its own snapshot
        with gzip.open(f, "rt") as fh:
            for line in fh:
                m = json.loads(line)
                B.tick(int(m["ts_ns"]))
                if m.get("snapshot"):
                    B.bids.clear(); B.asks.clear()
                for p, q in m.get("bids", ()):
                    B.set(True, float(p), float(q))
                for p, q in m.get("asks", ()):
                    B.set(False, float(p), float(q))
    B.save(day)


def october(day):
    B = Builder()
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "research5", "usdc_pairs", day, "??_XBTUSDTM_l2.jsonl.gz"))):
        snaps = []
        try:
            with gzip.open(f.replace("_l2.", "_snap."), "rt") as fh:
                for line in fh:
                    i = line.find("\t")
                    d = json.loads(line[i + 1:]).get("data") if i > 0 else None
                    if d and d.get("bids"):
                        snaps.append((int(line[:i]), int(d["sequence"]), d["bids"], d["asks"]))
        except (OSError, EOFError, ValueError):
            pass
        si = 0
        synced = False
        seq0 = -1
        try:
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    i = line.find("\t")
                    if i <= 0:
                        continue
                    recv = int(line[:i])
                    while si < len(snaps) and snaps[si][0] <= recv:      # a fresh snapshot: reset the book to it
                        _, seq0, bids, asks = snaps[si]
                        B.bids.clear(); B.asks.clear()
                        for p, q in bids:
                            B.set(True, float(p), q * 0.001)
                        for p, q in asks:
                            B.set(False, float(p), q * 0.001)
                        synced = True
                        si += 1
                    d = json.loads(line[i + 1:]).get("data")
                    if not d or "change" not in d or not synced or d["sequence"] <= seq0:
                        continue
                    B.tick(int(d["timestamp"]) * 1_000_000)
                    p, side, q = d["change"].split(",")
                    B.set(side == "buy", float(p), float(q) * 0.001)
        except (OSError, EOFError):
            pass
    B.save(day)


if __name__ == "__main__":
    day = sys.argv[1]
    (october if day in OCT else september)(day)
