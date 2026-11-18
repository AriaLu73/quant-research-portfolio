#!/usr/bin/env python3
"""research3 PX-2 input: the PX-1 grid (px_grid.grid_from) built from our own level3v2 recording of BTC-USDT, every 10 ms.
Pre-registration: docs/research3/px_cancel_2026-10-03.md.
The order-by-order book is turned into level-total updates (price -> resting size, BTC): open / match / update / done change
one level; an order that opens proves nothing rests at or through its price on the other side, so such stale levels are
removed (the same purge rule as qmm_trace.py). Trades come from match messages (taker side = "side"). Sizes: contracts x 0.001.
The book knows only orders opened since the start of each hour file (no L3 snapshot); the first minutes of an hour are thin.
usage: Python314/python.exe scripts/research3/px_l3grid.py 20261001,20261002 [shard i/n] [--l3step=2]
output: data/research3/px/BTC-USDT-L3/grid_<day>_<hh>.parquet"""
import glob, gzip, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_grid as G      # noqa: E402
from sortedcontainers import SortedDict      # noqa: E402

ROOT = G.ROOT
L3 = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt")
STEP_MS = int(G._opt("l3step", "10"))
OUT = os.path.join(ROOT, "data", "research3", "px", "BTC-USDT-L3" if STEP_MS == 10 else "BTC-USDT-L3-%dms" % STEP_MS)
MULT = 0.001
STEP_NS = STEP_MS * 1_000_000


def level_updates(path):
    orders = {}                     # oid -> [sgn, px, size]
    tot = {1: SortedDict(), -1: SortedDict()}     # sgn -> px -> size (contracts)
    best = {1: None, -1: None}

    def emit(ts, changes):
        m = {"ts_ns": ts, "bids": [], "asks": []}
        for sgn, px in changes:
            q = tot[sgn].get(px, 0.0)
            (m["bids"] if sgn > 0 else m["asks"]).append([px, q * MULT if q > 1e-12 else 0.0])
        return m

    with gzip.open(path, "rt") as fh:
        try:
            for line in fh:
                i = line.find("\t")
                if i <= 0:
                    continue
                try:
                    msg = json.loads(line[i + 1:])
                except ValueError:
                    continue
                sub, d = msg.get("subject"), msg.get("data")
                if sub == "received" or not d:
                    continue
                ts = int(d["ts"])
                ch = []
                if sub == "open":
                    sgn = 1 if d["side"] == "buy" else -1
                    px, sz = float(d["price"]), float(d["size"])
                    other = tot[-sgn]
                    stale = list(other.irange(maximum=px) if sgn > 0 else other.irange(minimum=px))
                    for p in stale:
                        del other[p]
                        ch.append((-sgn, p))
                    if stale:
                        for oid in [o for o, v in orders.items() if v[0] == -sgn and v[1] in stale]:
                            del orders[oid]
                    orders[d["orderId"]] = [sgn, px, sz]
                    tot[sgn][px] = tot[sgn].get(px, 0.0) + sz
                    ch.append((sgn, px))
                elif sub == "match":
                    yield {"ts_ns": ts, "bids": [], "asks": [], "trade": (1.0 if d["side"] == "buy" else -1.0) * float(d["size"]) * MULT}
                    o = orders.get(d["makerOrderId"])
                    if o is None:
                        continue
                    sz = float(d["size"])
                    o[2] -= sz
                    tot[o[0]][o[1]] = tot[o[0]].get(o[1], 0.0) - sz
                    ch.append((o[0], o[1]))
                    if d.get("remainSize") in ("0", 0) or o[2] <= 1e-12:
                        tot[o[0]][o[1]] -= max(o[2], 0.0)
                        del orders[d["makerOrderId"]]
                elif sub == "update":
                    o = orders.get(d["orderId"])
                    if o is None:
                        continue
                    new = float(d.get("size", 0) or 0)
                    tot[o[0]][o[1]] = tot[o[0]].get(o[1], 0.0) + new - o[2]
                    o[2] = new
                    ch.append((o[0], o[1]))
                    if new <= 0:
                        del orders[d["orderId"]]
                elif sub == "done":
                    o = orders.pop(d["orderId"], None)
                    if o is None:
                        continue
                    tot[o[0]][o[1]] = tot[o[0]].get(o[1], 0.0) - o[2]
                    ch.append((o[0], o[1]))
                else:
                    continue
                for sgn, px in ch:
                    if tot[sgn].get(px, 1.0) <= 1e-9:
                        tot[sgn].pop(px, None)
                if ch:
                    yield emit(ts, ch)
        except EOFError:
            return


def one(job):
    day, path = job
    hh = os.path.basename(path)[:2]
    out = os.path.join(OUT, "grid_%s_%s.parquet" % (day, hh))
    if os.path.exists(out):
        return out, "skip"
    df = G.grid_from(level_updates(path), None, STEP_NS)
    os.makedirs(OUT, exist_ok=True)
    df.to_parquet(out + ".tmp", index=False)
    os.replace(out + ".tmp", out)
    return out, len(df)


def main():
    days = sys.argv[1].split(",")
    shard = sys.argv[2] if len(sys.argv) > 2 else "0/1"
    i, n = map(int, shard.split("/"))
    jobs = [(d, p) for d in days for p in sorted(glob.glob(os.path.join(L3, d, "??_XBTUSDTM_l3.jsonl.gz")))]
    for k, job in enumerate(jobs):
        if k % n == i:
            print(*one(job), flush=True)
    print("PX_L3GRID_DONE", flush=True)


if __name__ == "__main__":
    main()
