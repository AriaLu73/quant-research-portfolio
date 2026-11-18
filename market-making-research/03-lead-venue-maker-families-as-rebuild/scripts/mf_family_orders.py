#!/usr/bin/env python3
"""research5 MF-3: every order of ONE sender pattern on KuCoin BTC-USDT, from the public order-by-order feed.

MF-1 (maker_families.py) found one profitable maker: clientOid = 20 digits starting with "01" ("#01|20"). Its ids look like
"0" + a 10-digit unix time (the start of a session) + a 9-digit number, so the first 11 characters name a session of the
program and the rest tells its orders apart. This script writes, per hour, one row per order of that pattern:
  session, number, received (ns: `received` message ts), order_time (ns, exchange receipt), open (ns; 0 = never rested),
  side (0 buy / 1 sell), tick (price x 10), size (contracts), end (ns), reason (0 cancelled, 1 filled), filled (contracts)
and one row per fill: ts, session, side, tick, size, taker family is its own pattern (1/0).
Output: data/research5/maker_families/orders_<tag>_<day>_<hh>.npz
Usage: .venv/Scripts/python.exe scripts/research5/mf_family_orders.py <YYYYMMDD> <HH> ["#01|20"]
"""
import gzip, os, sys, zlib
import numpy as np
import orjson

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import maker_families as M


def tag_of(pattern):
    return "".join(ch if ch.isalnum() else "_" for ch in pattern)


def run(day, hh, pattern="#01|20"):
    f = os.path.join(M.SRC, day, f"{hh}_{M.SYM}_l3.jsonl.gz")
    live = {}                 # orderId -> row index
    rows = []                 # [session, number, received, order_time, open, side, tick, size, end, reason, filled]
    fills = []
    mine = set()
    try:
        with gzip.open(f, "rb") as fh:
            for line in fh:
                i = line.find(b"\t")
                if i <= 0:
                    continue
                m = orjson.loads(line[i + 1:])
                d, s = m.get("data"), m.get("subject")
                if not d or not s:
                    continue
                if s == "received":
                    c = d.get("clientOid")
                    if c and M.family(c) == pattern:
                        live[d["orderId"]] = len(rows)
                        mine.add(d["orderId"])
                        rows.append([int(c[:11]), int(c[11:]), int(d["ts"]), 0, 0, -1, 0, 0, 0, -1, 0])
                elif s == "open":
                    k = live.get(d["orderId"])
                    if k is not None:
                        r = rows[k]
                        r[3], r[4] = int(d["orderTime"]), int(d["ts"])
                        r[5], r[6], r[7] = (0 if d["side"] == "buy" else 1), round(float(d["price"]) * 10), int(d["size"])
                elif s == "match":
                    k = live.get(d["makerOrderId"])
                    if k is not None:
                        r = rows[k]
                        r[10] += int(d["size"])
                        fills.append((int(d["ts"]), r[0], r[5], r[6], int(d["size"]), 1 if d["takerOrderId"] in mine else 0))
                elif s == "done":
                    k = live.pop(d["orderId"], None)
                    if k is not None:
                        rows[k][8] = int(d["ts"])
                        rows[k][9] = 1 if d.get("reason") == "filled" else 0
                        mine.discard(d["orderId"])
    except (EOFError, OSError, zlib.error) as e:
        print("damaged tail:", type(e).__name__, flush=True)
    R = np.array(rows, np.int64).reshape(-1, 11)
    F = np.array(fills, np.int64).reshape(-1, 6)
    out = os.path.join(M.OUT, f"orders_{tag_of(pattern)}_{day}_{hh}.npz")
    np.savez_compressed(out, orders=R, fills=F)
    opened = (R[:, 4] > 0).sum()
    print(f"{day} {hh} {pattern}: orders {len(R):,} (rested {opened:,}), fills {len(F):,}, sessions {len(np.unique(R[:, 0]))}", flush=True)


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "#01|20")
