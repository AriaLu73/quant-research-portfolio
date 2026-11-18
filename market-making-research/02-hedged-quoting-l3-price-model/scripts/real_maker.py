#!/usr/bin/env python3
"""research3 audit benchmark: what do the REAL resting orders of BTC-USDT earn when they are filled?
Independent of the virtual-order rules: every match message is one real maker fill. For the maker order we know (from its
open message) when it joined, at which price relative to the best price of its side at that moment (improved the best / joined
the best / deeper), how much was resting at its price when it joined, and how long it had rested when it was hit.
Markout = maker side x (mid after 1 / 5 / 10 s - fill price) / price, against the L3 mid (l3_mid.py); net = 10 s + OUR_FEE.
usage: Python314/python.exe scripts/research3/real_maker.py collect <day> [shard i/n]
       Python314/python.exe scripts/research3/real_maker.py report <day>[,<day>]
output: data/research3/px/real/fills_<day>_<hh>.npy   columns: ts_ns, side, price, size, age_ms, ahead_at_join, level_at_join,
        join_type (0 improved the best, 1 joined the best, 2 deeper, 3 unknown: opened before the file), taker_size, at_best_now"""
import glob, gzip, json, math, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qmm_l3_study as Q        # noqa: E402
import l3_mid as LM             # noqa: E402

L3, SYM, MS = Q.L3, Q.SYM, Q.MS
OUT = os.path.join(Q.ROOT, "data", "research3", "px", "real")
REBATE = OUR_FEE


def collect(day, files):
    os.makedirs(OUT, exist_ok=True)
    for f in files:
        hh = os.path.basename(f)[:2]
        outp = os.path.join(OUT, "fills_%s_%s.npy" % (day, hh))
        if os.path.exists(outp):
            continue
        orders = {}                 # oid -> [sgn, px, size, open_ts, ahead_at_join, join_type]
        tot = {}                    # (sgn, px) -> resting size
        book = {1: Q.Side(1), -1: Q.Side(-1)}
        rows = []
        taker_sz = {}
        pending = []                # rows of the current taker order, to fill in its total size
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
                    if sub == "open":
                        sgn = 1 if d["side"] == "buy" else -1
                        px, oid, sz = float(d["price"]), d["orderId"], float(d["size"])
                        side, other = book[sgn], book[-sgn]
                        opp = other.best()
                        while opp is not None and (px >= opp if sgn > 0 else px <= opp):
                            for stale in list(other.lv.get(opp, ())):
                                o = orders.pop(stale, None)
                                if o is not None:
                                    tot[(o[0], o[1])] = tot.get((o[0], o[1]), 0.0) - o[2]
                            other.lv[opp] = {}
                            opp = other.best()
                        best = side.best()
                        jt = 0 if (best is None or (px > best if sgn > 0 else px < best)) else (1 if px == best else 2)
                        ahead = max(tot.get((sgn, px), 0.0), 0.0)
                        side.add(px, oid)
                        orders[oid] = [sgn, px, sz, ts, ahead, jt]
                        tot[(sgn, px)] = ahead + sz
                        continue
                    if sub == "match":
                        o = orders.get(d["makerOrderId"])
                        sz = float(d["size"])
                        t_id = d["takerOrderId"]
                        taker_sz[t_id] = taker_sz.get(t_id, 0.0) + sz
                        if o is not None:
                            best = book[o[0]].best()
                            rows.append([ts, o[0], o[1], sz, (ts - o[3]) / 1e6, o[4], o[4] + 0.0, o[5], 0.0, 1.0 if best == o[1] else 0.0])
                            pending.append((len(rows) - 1, t_id))
                            o[2] -= sz
                            tot[(o[0], o[1])] = tot.get((o[0], o[1]), 0.0) - sz
                            if d.get("remainSize") in ("0", 0) or o[2] <= 1e-9:
                                tot[(o[0], o[1])] = tot.get((o[0], o[1]), 0.0) - max(o[2], 0.0)
                                orders.pop(d["makerOrderId"], None)
                                book[o[0]].remove(o[1], d["makerOrderId"])
                        continue
                    if sub == "update":
                        o = orders.get(d["orderId"])
                        if o is None:
                            continue
                        new = float(d.get("size", 0) or 0)
                        tot[(o[0], o[1])] = tot.get((o[0], o[1]), 0.0) + new - o[2]
                        o[2] = new
                        if new > 0:
                            continue
                        sub = "done"
                        tot[(o[0], o[1])] = tot.get((o[0], o[1]), 0.0) + o[2]
                    if sub == "done":
                        o = orders.pop(d["orderId"], None)
                        if o is not None:
                            tot[(o[0], o[1])] = tot.get((o[0], o[1]), 0.0) - o[2]
                            book[o[0]].remove(o[1], d["orderId"])
            except EOFError:
                pass
        A = np.array(rows, float) if rows else np.zeros((0, 10))
        for k, t_id in pending:
            A[k, 8] = taker_sz[t_id]
        np.save(outp, A)
        print(day, hh, "maker fills", len(A), flush=True)
    print("REAL_DONE", flush=True)


def wmean(x, w):
    m = np.isfinite(x)
    return float((x[m] * w[m]).sum() / w[m].sum()) if m.any() and w[m].sum() > 0 else float("nan")


def report(days):
    for day in days:
        A = np.concatenate([np.load(f) for f in sorted(glob.glob(os.path.join(OUT, "fills_%s_??.npy" % day)))])
        mid = LM.L3Mid(day)
        ts = A[:, 0].astype(np.int64)
        sg, px, sz, age, ahead, jt, tk, atb = A[:, 1], A[:, 2], A[:, 3], A[:, 4], A[:, 5], A[:, 7], A[:, 8], A[:, 9]
        mo = {h: sg * (mid.at(ts + h * 1_000_000_000) - px) / px * 1e4 for h in (1, 5, 10)}
        net = mo[10] + REBATE
        ok = np.isfinite(net)
        print("\n%s: %d real maker fills (%.0f BTC), with a markout %d" % (day, len(A), sz.sum() / 1000, ok.sum()))
        print("  all fills:            per fill  1 s %+.3f  5 s %+.3f  10 s %+.3f  net %+.3f | per contract  10 s %+.3f  net %+.3f" % (
            np.nanmean(mo[1]), np.nanmean(mo[5]), np.nanmean(mo[10]), np.nanmean(net), wmean(mo[10], sz), wmean(net, sz)))

        def line(name, m):
            m = m & ok
            if m.sum() < 30:
                return
            se = net[m].std(ddof=1) / math.sqrt(m.sum())
            print("  %-34s fills %7d (%4.1f%%)  size %5.1f%%  net per fill %+.3f (se %.3f)  per contract %+.3f" % (
                name, m.sum(), 100 * m.sum() / ok.sum(), 100 * sz[m].sum() / sz[ok].sum(), net[m].mean(), se, wmean(net[m], sz[m])))
        print(" by how the order joined:")
        for v, nm in ((0, "improved the best price"), (1, "joined the best price"), (2, "posted deeper in the book")):
            line(nm, jt == v)
        print(" by how long it had rested when it was hit:")
        for lo, hi, nm in ((0, 20, "< 20 ms"), (20, 200, "20-200 ms"), (200, 1000, "0.2-1 s"), (1000, 10000, "1-10 s"), (10000, 60000, "10-60 s"), (60000, 1e12, "> 1 min")):
            line(nm, (age >= lo) & (age < hi))
        print(" joined the best price, by the size resting ahead of it at that moment (contracts of 0.001 BTC):")
        for lo, hi, nm in ((-1, 0, "nobody ahead"), (0, 100, "<= 0.1 BTC"), (100, 500, "0.1-0.5 BTC"), (500, 2000, "0.5-2 BTC"), (2000, 1e12, "> 2 BTC")):
            line(nm, (jt == 1) & (ahead > lo) & (ahead <= hi))
        print(" by the size of the taker order (contracts):")
        for lo, hi, nm in ((0, 10, "<= 10"), (10, 100, "10-100"), (100, 500, "100-500"), (500, 1e12, "> 500")):
            line(nm, (tk > lo) & (tk <= hi))
        print(" filled at the best price of its side / behind it (the level in front had no known order):")
        line("at the best", atb == 1)
        line("not at the best", atb == 0)


if __name__ == "__main__":
    if sys.argv[1] == "collect":
        day = sys.argv[2]
        i, n = map(int, (sys.argv[3] if len(sys.argv) > 3 else "0/1").split("/"))
        fs = sorted(glob.glob(os.path.join(L3, day, f"??_{SYM}_l3.jsonl.gz")))
        collect(day, [f for k, f in enumerate(fs) if k % n == i])
    else:
        report(sys.argv[2].split(","))
