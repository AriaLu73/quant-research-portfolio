#!/usr/bin/env python3
"""research3 PX-5 (collection): regular orders joining the back of the BTC-USDT touch queue, on our level3v2 recording.
Pre-registration: docs/research3/px5_join_touch_2026-10-03.md. Method after Moallemi & Yuan 2017 s5.1 (artificial orders).
Every second, one infinitesimal buy and one sell join the best price of their side behind every order with orderTime <= arrival.
Recorded per order (no cancel rule applied here): arrival, price, size ahead and total at arrival, the time somebody posted a
better price on our side, the fill time if it is filled within 10 s (a later order at our price is hit, or the level is traded
through), size ahead / total just before the fill, and the maker markout 1 / 5 / 10 s after the fill.
usage: Python314/python.exe scripts/research3/px5_join.py <day> [shard i/n]
output: data/research3/px/px5/join_<day>_<hh>.jsonl.gz"""
import glob, gzip, json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qmm_l3_study as Q        # noqa: E402

ROOT, L3, SYM, MS = Q.ROOT, Q.L3, Q.SYM, Q.MS
OUT = os.path.join(ROOT, "data", "research3", "px", "px5")
LIFE_NS = 10_000 * MS
STEP_NS = 1_000 * MS
WARM = 300_000 * MS             # the book knows only orders opened since the start of the hour file


def run(day, files):
    bt, bmid = Q.bbo(day)

    def mid_at(t_ms):
        i = np.searchsorted(bt, t_ms, side="right") - 1
        return bmid[i] if i >= 0 else float("nan")

    os.makedirs(OUT, exist_ok=True)
    for f in files:
        hh = os.path.basename(f)[:2]
        outp = os.path.join(OUT, "join_%s_%s.jsonl.gz" % (day, hh))
        if os.path.exists(outp):
            continue
        out = gzip.open(outp + ".tmp", "wt")
        orders = {}                     # oid -> [sgn, px, size, order_time_ns]
        book = {1: Q.Side(1), -1: Q.Side(-1)}
        live = {1: [], -1: []}
        st = {"made": 0, "fill": 0}
        t_first, nxt = None, None

        def level(sgn, px, t):
            ahead = tot = 0.0
            for oid in book[sgn].lv.get(px) or ():
                o = orders.get(oid)
                if o is None:
                    continue
                tot += o[2]
                if o[3] <= t:
                    ahead += o[2]
            return ahead, tot

        def finish(v, ts, filled, thru=False):
            rec = {"h": hh, "s": v["sgn"], "p": v["px"], "t": v["t"], "a0": v["a0"], "q0": v["q0"], "b": v["b"], "f": None}
            if filled:
                st["fill"] += 1
                ah, tt = level(v["sgn"], v["px"], v["t"])
                rec.update(f=(ts - v["t"]) // 1000, thru=bool(thru), af=ah, qf=tt,
                           m=[round(v["sgn"] * (mid_at(ts // MS + h * 1000) - v["px"]) / v["px"] * 1e4, 3) for h in (1, 5, 10)])
            out.write(json.dumps(rec) + "\n")

        with gzip.open(f, "rt") as fh:
            try:
                for line in fh:
                    i = line.find("\t")
                    if i <= 0:
                        continue
                    try:
                        m = json.loads(line[i + 1:])
                    except ValueError:
                        continue
                    sub, d = m.get("subject"), m.get("data")
                    if sub == "received" or not d:
                        continue
                    ts = int(d["ts"])
                    if t_first is None:
                        t_first = ts
                        nxt = (ts + WARM) // STEP_NS * STEP_NS + STEP_NS
                    for sg in (1, -1):                                  # time limit
                        if live[sg] and ts - live[sg][0]["t"] >= LIFE_NS:
                            keep = []
                            for v in live[sg]:
                                if ts - v["t"] >= LIFE_NS:
                                    finish(v, v["t"] + LIFE_NS, False)
                                else:
                                    keep.append(v)
                            live[sg] = keep
                    while ts >= nxt:                                    # new virtual orders at the back of both touch queues
                        bb, ba = book[1].best(), book[-1].best()
                        if bb is not None and ba is not None and bb < ba:
                            for sg, px in ((1, bb), (-1, ba)):
                                a0, q0 = level(sg, px, nxt)
                                live[sg].append({"sgn": sg, "px": px, "t": nxt, "a0": a0, "q0": q0, "b": None})
                                st["made"] += 1
                        nxt += STEP_NS
                    if sub == "open":
                        sgn = 1 if d["side"] == "buy" else -1
                        px, oid, ot = float(d["price"]), d["orderId"], int(d["orderTime"])
                        side, other = book[sgn], book[-sgn]
                        opp = other.best()
                        while opp is not None and (px >= opp if sgn > 0 else px <= opp):
                            for stale in list(other.lv.get(opp, ())):
                                orders.pop(stale, None)
                            other.lv[opp] = {}
                            opp = other.best()
                        for v in live[sgn]:
                            if v["b"] is None and (px > v["px"] if sgn > 0 else px < v["px"]):
                                v["b"] = (ts - v["t"]) // 1000
                        side.add(px, oid)
                        orders[oid] = [sgn, px, float(d["size"]), ot]
                        continue
                    if sub == "match":
                        o = orders.get(d["makerOrderId"])
                        if o is None:
                            continue
                        sgn, px, sz = o[0], o[1], float(d["size"])
                        if live[sgn]:
                            keep = []
                            for v in live[sgn]:
                                if (px == v["px"] and o[3] > v["t"]) or (px < v["px"] if sgn > 0 else px > v["px"]):
                                    finish(v, ts, True, px != v["px"])
                                else:
                                    keep.append(v)
                            live[sgn] = keep
                        o[2] -= sz
                        if d.get("remainSize") not in ("0", 0):
                            continue
                        d = {"orderId": d["makerOrderId"]}
                        sub = "done"
                    if sub == "update":
                        o = orders.get(d["orderId"])
                        if o is None:
                            continue
                        if d.get("size") in ("0", 0):
                            sub = "done"
                        else:
                            try:
                                o[2] = float(d["size"])
                            except (KeyError, ValueError):
                                pass
                            continue
                    if sub == "done":
                        o = orders.pop(d["orderId"], None)
                        if o is not None:
                            book[o[0]].remove(o[1], d["orderId"])
            except EOFError:
                pass
        for sg in (1, -1):
            for v in live[sg]:
                finish(v, v["t"] + LIFE_NS, False)
        out.close()
        os.replace(outp + ".tmp", outp)
        print(day, hh, "orders", st["made"], "filled within 10 s without any cancel", st["fill"], flush=True)
    print("PX5_JOIN_DONE", flush=True)


if __name__ == "__main__":
    day = sys.argv[1]
    i, n = map(int, (sys.argv[2] if len(sys.argv) > 2 else "0/1").split("/"))
    fs = sorted(glob.glob(os.path.join(L3, day, f"??_{SYM}_l3.jsonl.gz")))
    run(day, [f for k, f in enumerate(fs) if k % n == i])
