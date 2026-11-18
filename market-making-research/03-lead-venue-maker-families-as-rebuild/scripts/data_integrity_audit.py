"""Integrity audit of the self-recorded KuCoin level3v2 files (order-by-order feed).

Per hour file: sequence gaps (missing numbers), out-of-order and duplicate sequence numbers,
exchange-timestamp regressions, reconnects, and orders whose life cycle is broken
(open / match / done seen without the preceding event).
"""
import glob
import gzip
import os
import sys

import orjson

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt")


def audit(f):
    last_sn = None
    last_ts = None
    n = gaps = missing = ooo = dup = ts_back = conn = 0
    max_back_ms = 0.0
    gap_list = []
    received, opened = set(), set()
    open_wo_recv = match_wo_open = done_wo_recv = 0
    seen_first = False
    trunc = 0
    fh = gzip.open(f, "rb")
    it = iter(fh)
    while True:
        try:
            line = next(it)
        except StopIteration:
            break
        except EOFError:
            trunc = 1                    # file ends without the gzip end marker (recorder was killed)
            break
        if True:
            i = line.find(b"\t")
            if i <= 0:
                continue
            m = orjson.loads(line[i + 1:])
            if "_marker" in m:
                if m["_marker"].get("event") == "connect":
                    conn += 1
                    last_sn = None          # a new connection starts a new run
                continue
            d = m.get("data")
            s = m.get("subject")
            if not d or not s:
                continue
            n += 1
            sn = d.get("sequence", m.get("sn"))
            if sn is None:
                continue
            ts = int(d["ts"])
            if last_sn is not None:
                if sn == last_sn:
                    dup += 1
                elif sn < last_sn:
                    ooo += 1
                elif sn > last_sn + 1:
                    gaps += 1
                    missing += sn - last_sn - 1
                    gap_list.append((ts, sn - last_sn - 1))
            if last_sn is None or sn > last_sn:
                last_sn = sn
            if last_ts is not None and ts < last_ts:
                ts_back += 1
                max_back_ms = max(max_back_ms, (last_ts - ts) / 1e6)
            else:
                last_ts = ts
            oid = d.get("orderId")
            if s == "received":
                received.add(oid)
            elif s == "open":
                if seen_first and oid not in received:
                    open_wo_recv += 1
                opened.add(oid)
            elif s == "match":
                mk = d.get("makerOrderId")
                if seen_first and mk not in opened:
                    match_wo_open += 1
            elif s == "done":
                if seen_first and oid not in received:
                    done_wo_recv += 1
                received.discard(oid)
                opened.discard(oid)
            if not seen_first and n > 200000:
                seen_first = True          # orders resting before the file started are not errors
    return dict(n=n, trunc=trunc, conn=conn, gaps=gaps, missing=missing, ooo=ooo, dup=dup, ts_back=ts_back,
                max_back_ms=max_back_ms, open_wo_recv=open_wo_recv, match_wo_open=match_wo_open,
                done_wo_recv=done_wo_recv, gap_list=gap_list[:5])


if __name__ == "__main__":
    pat = sys.argv[1] if len(sys.argv) > 1 else "XBTUSDTM"
    for f in sorted(glob.glob(os.path.join(SRC, "*", f"*_{pat}_l3.jsonl.gz"))):
        r = audit(f)
        print(os.path.relpath(f, SRC), r, flush=True)
