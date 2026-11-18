"""research3 QMM-2 (data collection): the life of an early order on a new BTC-USDT touch level, event by event.
QMM-1 (scripts/research3/qmm_l3_study.py) on 2026-10-01, 11 h, 43,048 new touch levels: arriving 2 ms after the birth and
leaving only when the level is empty loses 0.48 bp per fill after the rebate (se 0.15), while the real orders that arrived
1st-10th earn about +0.26 bp after the rebate with their own cancels and let only 0.5-0.8 % of their posted size be filled
(our naive rule: 8.5 % of orders filled). The difference is the cancel rule. This script records, for one virtual order per
new level (arrival DELAY_MS after the birth, held up to 5 s, never cancelled), everything a cancel rule could look at:

  trace   at every event on its price level, and whenever the opposite best queue changes by a fifth or its price moves:
          [microseconds since arrival, real size on the level, size in front of us (Q_before), size behind us (Q_after),
          size traded on the level since arrival, size of the best opposite queue (Q_opp)]   (contracts of 0.001 BTC).
          (Q_before, Q_after, Q_opp) is the state of Lehalle-Mounjid 2017 s3.1; queue position QP = Q_before / (Q_before +
          Q_after) and the near / opposite queue sizes are the conditioning variables of Albers et al. 2025 s5, Table 1.
  better  when somebody first posted a better price on our side (we are no longer the touch)
  fill    when it would have been filled without any cancel (an order behind us is hit, or the level is traded through),
          and the maker's markout against the BTC-USDT mid 1 / 5 / 10 s later, bp
Also: how long the real orders that arrived 1st-10th rested before they were cancelled.
Rules are then evaluated offline on these traces (scripts/research3/qmm_rules.py): a rule gives a cancel time; the order is
filled only if its fill comes before cancel time + tau_c.
usage: Python314/python.exe scripts/research3/qmm_trace.py <day> <hours|all> [delay_ms=2] [part suffix of the output name]
output: data/research3/qmm/trace_<day>_d<delay>[part].jsonl.gz (parts of one day run side by side; qmm_state.py reads them all)"""
import glob, gzip, heapq, json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qmm_l3_study as Q        # noqa: E402  (bbo, Side, paths)

ROOT, L3, SYM, MS = Q.ROOT, Q.L3, Q.SYM, Q.MS
LIMIT_MS = 5000
WARM = 120_000 * MS


def run(day, hours, delay_ms, part=""):
    bt, bmid = Q.bbo(day)

    def mid_at(t_ms):
        i = np.searchsorted(bt, t_ms, side="right") - 1
        return bmid[i] if i >= 0 else float("nan")

    files = sorted(glob.glob(os.path.join(L3, day, f"??_{SYM}_l3.jsonl.gz")))
    if hours != "all":
        keep = {"%02d" % int(h) for h in hours.split(",")}
        files = [f for f in files if os.path.basename(f)[:2] in keep]
    os.makedirs(os.path.join(ROOT, "data", "research3", "qmm"), exist_ok=True)
    out = gzip.open(os.path.join(ROOT, "data", "research3", "qmm", "trace_%s_d%g%s.jsonl.gz" % (day, delay_ms, part)), "wt")
    orders = {}                     # oid -> [sgn, px, size, order_time_ns, rank, open_ts]
    tot = {}                        # (sgn, px) -> real size resting on that level
    life = {1: [], 2: [], 4: [], 11: []}        # resting time (ms) of cancelled real orders by arrival rank bucket
    st = {"births": 0, "msgs": 0, "virt": 0, "fill": 0}
    for f in files:
        hh = os.path.basename(f)[:2]
        t_first = None
        orders.clear()
        tot.clear()
        book = {1: Q.Side(1), -1: Q.Side(-1)}
        births, level_birth = {}, {}
        on_level = {}               # (sgn, px) -> [live virtual orders at that price]
        virt = {1: [], -1: []}
        timers, tseq = [], 0

        def snap(v, ts, q, traded_add=0.0):
            real = ahead = 0.0
            for oid in q:
                o = orders.get(oid)
                if o is None:
                    continue
                real += o[2]
                if o[3] <= v["t"]:
                    ahead += o[2]
            v["traded"] += traded_add
            opp = book[-v["sgn"]].best()
            qo = tot.get((-v["sgn"], opp), 0.0) if opp is not None else 0.0
            v["opp"] = (opp, qo)
            v["tr"].append([(ts - v["t0"]) // 1000, real, ahead, real - ahead, v["traded"], qo])

        def watch_opp(ts):
            """Opposite best queue of every live virtual order: a new trace row when it moved by a fifth or changed price."""
            for sg in (1, -1):
                vs = virt[sg]
                if not vs:
                    continue
                opp = book[-sg].best()
                qo = tot.get((-sg, opp), 0.0) if opp is not None else 0.0
                for v in vs:
                    if v["state"] != "live":
                        continue
                    p0, q0 = v["opp"]
                    if opp != p0 or abs(qo - q0) > 0.2 * max(q0, 1.0):
                        last = v["tr"][-1]
                        v["opp"] = (opp, qo)
                        v["tr"].append([(ts - v["t0"]) // 1000, last[1], last[2], last[3], last[4], qo])

        def finish(v, ts, filled, thru=False):
            v["state"] = "done"
            rec = {"h": v["hour"], "s": v["sgn"], "p": v["px"], "t": v["t0"] // MS, "tr": v["tr"], "b": v["b"], "f": None}
            if filled:
                st["fill"] += 1
                tms = ts // MS
                rec["f"] = (ts - v["t0"]) // 1000
                rec["thru"] = bool(thru)
                rec["m"] = [round(v["sgn"] * (mid_at(tms + h * 1000) - v["px"]) / v["px"] * 1e4, 3) for h in (1, 5, 10)]
            out.write(json.dumps(rec) + "\n")
            lst = on_level.get((v["sgn"], v["px"]))
            if lst and v in lst:
                lst.remove(v)

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
                    st["msgs"] += 1
                    if t_first is None:
                        t_first = ts
                    while timers and timers[0][0] <= ts:
                        _, _, v, what = heapq.heappop(timers)
                        if v["state"] == "done":
                            continue
                        if what == "activate":
                            opp = book[-v["sgn"]].best()
                            if opp is not None and (v["px"] >= opp if v["sgn"] > 0 else v["px"] <= opp):
                                v["state"] = "done"                                     # post-only would be refused
                                continue
                            v["state"], v["t0"] = "live", ts
                            st["virt"] += 1
                            virt[v["sgn"]].append(v)
                            on_level.setdefault((v["sgn"], v["px"]), []).append(v)
                            snap(v, ts, book[v["sgn"]].lv.get(v["px"]) or ())
                            best = book[v["sgn"]].best()
                            if best is not None and (best > v["px"] if v["sgn"] > 0 else best < v["px"]):
                                v["b"] = 0
                            tseq += 1
                            heapq.heappush(timers, (ts + LIMIT_MS * MS, tseq, v, "end"))
                        elif v["state"] == "live":
                            finish(v, ts, False)
                    if sub == "open":
                        sgn = 1 if d["side"] == "buy" else -1
                        px, oid, ot = float(d["price"]), d["orderId"], int(d["orderTime"])
                        side, other = book[sgn], book[-sgn]
                        opp = other.best()
                        while opp is not None and (px >= opp if sgn > 0 else px <= opp):
                            for stale in list(other.lv.get(opp, ())):
                                orders.pop(stale, None)
                            other.lv[opp] = {}
                            tot.pop((-sgn, opp), None)
                            level_birth.pop((-sgn, opp), None)
                            opp = other.best()
                        best = side.best()
                        key = level_birth.get((sgn, px)) if side.lv.get(px) else None
                        better = best is not None and (px > best if sgn > 0 else px < best)
                        if key is None and better and opp is not None and ts - t_first > WARM:
                            key = (sgn, px, ot)
                            births[key] = 0
                            level_birth[(sgn, px)] = key
                            st["births"] += 1
                            v = {"sgn": sgn, "px": px, "t": ot + int(delay_ms * MS), "state": "wait", "hour": hh, "tr": [], "b": None,
                                 "traded": 0.0, "t0": 0, "opp": (None, 0.0)}
                            tseq += 1
                            heapq.heappush(timers, (v["t"], tseq, v, "activate"))
                        elif key is None:
                            level_birth.pop((sgn, px), None)
                        if better:
                            for v in virt[sgn]:
                                if v["state"] == "live" and v["b"] is None and (px > v["px"] if sgn > 0 else px < v["px"]):
                                    v["b"] = (ts - v["t0"]) // 1000
                        rank = None
                        if key is not None and key in births:
                            births[key] += 1
                            rank = births[key]
                        side.add(px, oid)
                        orders[oid] = [sgn, px, float(d["size"]), ot, rank, ts]
                        tot[(sgn, px)] = tot.get((sgn, px), 0.0) + float(d["size"])
                        for v in on_level.get((sgn, px), ()):
                            snap(v, ts, side.lv[px])
                        watch_opp(ts)
                        continue
                    if sub == "match":
                        o = orders.get(d["makerOrderId"])
                        if o is None:
                            continue
                        sgn, px, sz = o[0], o[1], float(d["size"])
                        o[2] -= sz
                        tot[(sgn, px)] = max(tot.get((sgn, px), 0.0) - sz, 0.0)
                        vs = virt[sgn]
                        if vs:
                            keep = []
                            for v in vs:
                                if v["state"] != "live":
                                    continue
                                if (px == v["px"] and o[3] > v["t"]) or (px < v["px"] if sgn > 0 else px > v["px"]):
                                    finish(v, ts, True, px != v["px"])
                                else:
                                    keep.append(v)
                            virt[sgn] = keep
                        for v in on_level.get((sgn, px), ()):
                            snap(v, ts, book[sgn].lv.get(px) or (), sz)
                        if d.get("remainSize") not in ("0", 0):
                            watch_opp(ts)
                            continue
                        d = {"orderId": d["makerOrderId"], "reason": "filled"}
                        sub = "done"
                    if sub == "update":
                        o = orders.get(d["orderId"])
                        if o is None:
                            continue
                        if d.get("size") in ("0", 0):
                            sub = "done"
                        else:
                            try:
                                new = float(d["size"])
                                tot[(o[0], o[1])] = max(tot.get((o[0], o[1]), 0.0) + new - o[2], 0.0)
                                o[2] = new
                            except (KeyError, ValueError):
                                pass
                            for v in on_level.get((o[0], o[1]), ()):
                                snap(v, ts, book[o[0]].lv.get(o[1]) or ())
                            watch_opp(ts)
                            continue
                    if sub == "done":
                        o = orders.pop(d["orderId"], None)
                        if o is None:
                            continue
                        left = book[o[0]].remove(o[1], d["orderId"])
                        if left == 0:
                            tot.pop((o[0], o[1]), None)
                        else:
                            tot[(o[0], o[1])] = max(tot.get((o[0], o[1]), 0.0) - o[2], 0.0)
                        if o[4] is not None and d.get("reason") != "filled":
                            k = 1 if o[4] == 1 else 2 if o[4] <= 3 else 4 if o[4] <= 10 else 11
                            life[k].append((ts - o[5]) / 1e6)
                        if left == 0:
                            level_birth.pop((o[0], o[1]), None)
                        for v in on_level.get((o[0], o[1]), ()):
                            snap(v, ts, book[o[0]].lv.get(o[1]) or ())
                        watch_opp(ts)
            except EOFError:
                pass
        for v in virt[1] + virt[-1]:
            if v["state"] == "live":
                finish(v, v["t0"] + LIMIT_MS * MS, False)
        print(day, hh, "messages", st["msgs"], "births", st["births"], "virtual orders", st["virt"], "filled without any cancel", st["fill"], flush=True)
    out.close()
    print("\nresting time of real orders on new levels before they were cancelled, ms (by arrival rank):")
    for k, name in ((1, "1st"), (2, "2nd-3rd"), (4, "4th-10th"), (11, "11th+")):
        v = np.array(life[k])
        if len(v):
            print("  %-8s n=%-7d p10 %.1f  p25 %.1f  median %.1f  p75 %.1f  p90 %.1f" % ((name, len(v)) + tuple(np.quantile(v, [.1, .25, .5, .75, .9]))))
    print("TRACE DONE", flush=True)


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "all", float(sys.argv[3]) if len(sys.argv) > 3 else 2.0,
        sys.argv[4] if len(sys.argv) > 4 else "")
