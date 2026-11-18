#!/usr/bin/env python3
"""research5: where does the time of a live order go - our side or the exchange? (read-only, from a copy of the bus journal)

For each new order the journal holds: the moment the engine published the request (bus time, our clock); the gateway's own
acknowledgement (a report whose timestamp is our clock, published within 0.2 ms of it); and the exchange's private pushes,
stamped by the EXCHANGE clock in nanoseconds: the first when the order arrives, the last when it is resting in the book.
  A  engine publish -> exchange arrival stamp   = our code + network + whatever the exchange does before stamping (two clocks)
  B  arrival stamp  -> resting in the book      = inside the exchange only (one clock: the exchange's)
  C  resting        -> acknowledgement handled  = exchange reply + network + our code
Same for cancels: request published -> exchange stamps the order cancelled.
Usage: .venv/Scripts/python.exe scripts/research5/live_order_path.py <journal.jsonl.gz> [HH:MM-HH:MM UTC window]
"""
import base64, gzip, sys, zlib, datetime as dt
import numpy as np
sys.path.insert(0, r"")
import orjson
from core.pb import bus_pb2
from core.glue import bus_codec


def pct(v, ps=(50, 75, 90, 95, 99, 100)):
    v = np.asarray(v, float)
    return "  ".join(f"p{p if p < 100 else 'max'} {np.percentile(v, p):6.2f}" for p in ps) if len(v) else "no samples"


def split_reports(rs):
    """rs: [(report timestamp ns, bus publish time ns)] -> (gateway acknowledgements, exchange pushes), by whose clock stamped them."""
    ack = sorted(ts for ts, pub in rs if abs(pub - ts) < 200_000)
    push = sorted(ts for ts, pub in rs if abs(pub - ts) >= 200_000)
    return ack, push


def main():
    req, creq, subs, canc, sym = {}, {}, {}, {}, {}
    try:
        with gzip.open(sys.argv[1], "rb") as fh:
            for line in fh:
                if b'"topic":"trade.order' not in line[:60]:
                    continue
                r = orjson.loads(line)
                t = r["ts_ns"]
                env = bus_pb2.BusEnvelope(); env.ParseFromString(base64.b64decode(r["b64"]))
                try:
                    if env.msg_type == "KVGroup":
                        kv = bus_pb2.KVGroup(); kv.ParseFromString(env.payload)
                        creq.setdefault(dict(kv.entries).get("order_id", ""), t)
                        continue
                    o = bus_codec.decode(env.msg_type, env.payload)
                except Exception:  # noqa: BLE001 - an undecodable record is skipped
                    continue
                if env.msg_type == "Order":
                    req[o.order_id] = t
                    sym[o.order_id] = o.symbol
                elif env.msg_type == "OrderReport":
                    if o.status.value == "submitted":
                        subs.setdefault(o.order_id, []).append((o.ts_ns, t))
                    elif o.status.value == "cancelled":
                        canc.setdefault(o.order_id, []).append((o.ts_ns, t))
    except (EOFError, OSError, zlib.error):
        pass
    rows = []
    for oid, t_req in req.items():
        ack, push = split_reports(subs.get(oid) or [])
        if len(push) >= 2 and push[0] > t_req - 5_000_000:
            rows.append((t_req, (push[0] - t_req) / 1e6, (push[-1] - push[0]) / 1e6, (ack[0] - push[-1]) / 1e6 if ack else np.nan, (ack[0] - t_req) / 1e6 if ack else np.nan, sym[oid]))
    a = np.array([(r[0], r[1], r[2], r[3], r[4]) for r in rows], float)
    print(f"new orders with both exchange pushes: {len(a)} of {len(req)}")
    print("A  engine publish -> exchange arrival stamp :", pct(a[:, 1]))
    print("B  arrival stamp  -> resting in the book    :", pct(a[:, 2]))
    print("   A + B  engine publish -> resting         :", pct(a[:, 1] + a[:, 2]))
    print("C  resting -> our acknowledgement handled   :", pct(a[:, 3][np.isfinite(a[:, 3])]))
    print("   engine publish -> acknowledgement handled:", pct(a[:, 4][np.isfinite(a[:, 4])]))
    tot = a[:, 1] + a[:, 2]
    for lo, hi in ((0, 5), (5, 10), (10, 20), (20, 1e9)):
        m = (tot >= lo) & (tot < hi)
        if m.sum():
            print(f"   orders resting after {lo:g}-{hi:g} ms: {m.mean():5.1%} of orders | of that time, part A median {np.median(a[m, 1]):5.2f} ms, part B median {np.median(a[m, 2]):6.2f} ms")
    slow = tot > 10
    print(f"   among the orders slower than 10 ms ({slow.sum()}): share where part B alone exceeds 5 ms {np.mean(a[slow, 2] > 5):.0%}; where part A alone exceeds 5 ms {np.mean(a[slow, 1] > 5):.0%}")
    for s in sorted(set(r[5] for r in rows)):
        m = np.array([r[5] == s for r in rows])
        print(f"   {s}: n {m.sum()} | A {pct(a[m, 1], (50, 90, 99))} | B {pct(a[m, 2], (50, 90, 99))}")
    c = []
    for oid, t_req in creq.items():
        ack, push = split_reports(canc.get(oid) or [])
        if push:
            c.append(((push[0] - t_req) / 1e6, (ack[0] - t_req) / 1e6 if ack else np.nan))
    c = np.array(c, float)
    print(f"cancels: {len(c)}")
    print("   request published -> exchange stamps cancelled:", pct(c[:, 0]))
    print("   request published -> our acknowledgement      :", pct(c[:, 1][np.isfinite(c[:, 1])]))
    hr = np.array([dt.datetime.fromtimestamp(r[0] / 1e9, dt.timezone.utc).hour for r in rows])
    for h in sorted(set(hr)):
        m = hr == h
        print(f"   {h:02d}h UTC: n {m.sum():4d} | A p50 {np.median(a[m, 1]):.2f} p90 {np.percentile(a[m, 1], 90):.2f} | B p50 {np.median(a[m, 2]):.2f} p90 {np.percentile(a[m, 2], 90):.2f} p99 {np.percentile(a[m, 2], 99):.2f}")


if __name__ == "__main__":
    main()
