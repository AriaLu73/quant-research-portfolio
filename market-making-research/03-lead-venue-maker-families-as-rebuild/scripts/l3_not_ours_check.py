#!/usr/bin/env python3
"""research5: is the exchange-side entry delay of our orders (open.ts - open.orderTime) something WE cause?

Read-only, public level3v2 recording + our decoded live journal. Each test removes one explanation:
  A. load:      share of orders slower than 10 ms per load band (XBTUSDCM + XBTUSDTM messages in +-50 ms),
                ours against the busiest other senders (clientOid pattern) - same moments' busyness;
  B. placement: same, split by where the order lands relative to the same-side best price at arrival
                (improves the touch / joins it / 1-5 ticks behind / deeper), book rebuilt from the L3 feed;
  C. instant:   other participants' orders received 0-5 ms AFTER our slow order - fast => no global stall then;
  D. own cancels: our cancels sent shortly before the order - does the order wait for them (account-serial queue)?
                 compares orders with / without a cancel of ours sent in the previous 5 ms, and the gap between
                 the order resting and those cancels being done (from the public `done` messages).
Book and loads use only orders received after START (the last recording gap ends 18:49:03 UTC; 10 min warm-up).
Usage: .venv/Scripts/python.exe scripts/research5/l3_not_ours_check.py
"""
import collections, gzip, json, os, sys, zlib
import numpy as np
import orjson

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l3_entry_delay as E

MS = 1_000_000
DAY, HOURS = "20261002", ("18", "19", "20", "21")
START = 1790967600 * 10**9 - 0          # 2026-10-02 19:00:00 UTC
END = 1790974980 * 10**9                # 21:03:00 UTC
BOOK_FROM = 1790966945 * 10**9          # 18:49:05 UTC, after the last recording gap: the book is rebuilt from here
JOURNAL = "data/research5/live_20261002/trade_events.jsonl"
TICK = 0.1
SLOW = 10.0


def l3_lines(sym, root):
    for h in HOURS:
        f = os.path.join(root, DAY, f"{h}_{sym}_l3.jsonl.gz")
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    i = line.find(b"\t")
                    if i > 0:
                        yield line[i + 1:]
        except (EOFError, OSError, zlib.error):
            pass


def all_ts(sym, root):
    out = []
    for raw in l3_lines(sym, root):
        j = raw.find(b'"ts":')
        if j > 0:
            k = j + 5
            out.append(int(raw[k:raw.find(b"}", k)].split(b",")[0]))
    return np.sort(np.array(out, np.int64))


def band_table(title, rows, groups, key, bands, labels):
    print(title)
    print("   " + " " * 24 + "".join(f"{l:>20s}" for l in labels))
    for g in groups:
        sub = [r for r in rows if r["fam"] == g]
        cells = []
        for b in bands:
            v = [r["d"] for r in sub if b(key(r))]
            cells.append(f"{np.mean(np.array(v) > SLOW):6.1%} (n {len(v):5d})" if len(v) >= 30 else f"{'-':>6s} (n {len(v):5d})")
        print(f"   {g[:24]:24s}" + "".join(f"{c:>20s}" for c in cells))


def main():
    # ---- our orders and cancels from the journal
    ours, cancels = set(), []                       # cancels: (engine send ns, exchange order id)
    for line in open(JOURNAL, encoding="utf-8"):
        e = json.loads(line)
        if e["type"] == "OrderReport" and e["msg"].get("exchange_order_id"):
            ours.add(e["msg"]["exchange_order_id"])
        elif e["type"] == "KVGroup" and e["msg"].get("exchange_order_id"):
            cancels.append((e["ts_ns"], e["msg"]["exchange_order_id"]))
    cancels.sort()
    c_send = np.array([c[0] for c in cancels], np.int64)

    # ---- one pass over XBTUSDCM: families, book, opens, done times
    fam_of, done_ts, rows = {}, {}, []
    book = {}                                       # orderId -> (side, price)
    lv = {"buy": collections.Counter(), "sell": collections.Counter()}
    for raw in l3_lines("XBTUSDCM", "data/research5/usdc_pairs"):
        m = orjson.loads(raw)
        d = m.get("data") or {}
        s = m.get("subject")
        if s == "received":
            fam_of[d["orderId"]] = "OURS" if d["orderId"] in ours else E.family(d.get("clientOid"))
        elif s == "open":
            oid, side, px = d["orderId"], d["side"], round(float(d["price"]), 1)
            ot, t = int(d["orderTime"]), int(d["ts"])
            if START <= ot <= END:
                same = lv[side]
                best = (max(same) if side == "buy" else min(same)) if same else None
                if best is None:
                    dist = None
                else:
                    dist = round(((best - px) if side == "buy" else (px - best)) / TICK)
                rows.append({"oid": oid, "fam": fam_of.pop(oid, "unknown"), "d": (t - ot) / MS, "ot": ot, "ts": t, "dist": dist})
            if ot < BOOK_FROM:
                continue
            # an order resting at px proves nothing rests on the other side at or through px: clear such leftovers
            # (orders whose `done` fell into a recording gap) so the touch is not taken from stale orders
            other = "sell" if side == "buy" else "buy"
            stale = [p for p in lv[other] if (p <= px if side == "buy" else p >= px)]
            for p in stale:
                del lv[other][p]
            book[oid] = (side, px)
            lv[side][px] += 1
        elif s == "done":
            done_ts[d["orderId"]] = int(d["ts"])
            o = book.pop(d["orderId"], None)
            if o:
                lv[o[0]][o[1]] -= 1
                if lv[o[0]][o[1]] <= 0:
                    del lv[o[0]][o[1]]
    rows = [r for r in rows if -5 < r["d"] < 500]

    # ---- load around each order
    ts_c = all_ts("XBTUSDCM", "data/research5/usdc_pairs")
    ts_t = all_ts("XBTUSDTM", "data/research5/usdc_pairs_l3usdt")
    ot = np.array([r["ot"] for r in rows], np.int64)
    load = (np.searchsorted(ts_c, ot + 50 * MS) - np.searchsorted(ts_c, ot - 50 * MS)
            + np.searchsorted(ts_t, ot + 50 * MS) - np.searchsorted(ts_t, ot - 50 * MS))
    for r, l in zip(rows, load):
        r["load"] = int(l)

    cnt = collections.Counter(r["fam"] for r in rows if r["fam"] not in ("OURS", "unknown"))
    groups = ["OURS"] + [f for f, _ in cnt.most_common(5)]
    mine = [r for r in rows if r["fam"] == "OURS"]
    print(f"window 19:00-21:03 UTC; opens {len(rows):,}, ours {len(mine)}; our cancels in journal {len(cancels)}")
    print("senders:", ", ".join(f"{g} n={sum(1 for r in rows if r['fam'] == g)}" for g in groups))

    # A. load
    lb = [(0, 343), (343, 744), (744, 1200), (1200, 1800), (1800, 10**9)]
    band_table("\nA. share of orders slower than 10 ms by load (messages per 100 ms on XBTUSDCM+XBTUSDTM)", rows, groups + ["ALL OTHERS"],
               lambda r: r["load"], [lambda x, a=a, b=b: a <= x < b for a, b in lb], [f"{a}-{b if b < 10**9 else 'max'}" for a, b in lb])
    for r in rows:
        if r["fam"] != "OURS":
            r["fam2"] = "ALL OTHERS"
    allo = [dict(r, fam="ALL OTHERS") for r in rows if r["fam"] != "OURS"]
    band_table("   (all other participants pooled)", allo, ["ALL OTHERS"], lambda r: r["load"],
               [lambda x, a=a, b=b: a <= x < b for a, b in lb], [f"{a}-{b if b < 10**9 else 'max'}" for a, b in lb])
    # load-matched expectation: reweight others to our load distribution
    ol = np.array([r["load"] for r in allo]); od = np.array([r["d"] for r in allo]) > SLOW
    edges = np.percentile([r["load"] for r in mine], np.linspace(0, 100, 21))
    exp = []
    for r in mine:
        k = np.clip(np.searchsorted(edges, r["load"]) - 1, 0, 19)
        m = (ol >= edges[k]) & (ol <= edges[k + 1])
        exp.append(od[m].mean() if m.sum() > 50 else np.nan)
    print(f"   load-matched: ours {np.mean([r['d'] > SLOW for r in mine]):.1%} slow vs others reweighted to our load {np.nanmean(exp):.1%}")

    # B. placement x load (high-load only, where most of ours are)
    db = [lambda x: x is not None and x < 0, lambda x: x == 0, lambda x: x is not None and 1 <= x <= 5, lambda x: x is not None and x > 5]
    dl = ["improves touch", "joins touch", "1-5 ticks back", ">5 ticks back"]
    hi = [r for r in rows if r["load"] >= 744]
    band_table("\nB. load >= 744 only: share slower than 10 ms by placement vs same-side best at arrival", hi + [dict(r, fam="ALL OTHERS") for r in hi if r["fam"] != "OURS"],
               groups + ["ALL OTHERS"], lambda r: r["dist"], db, dl)

    # C. the same instant
    oth = sorted((r["ot"], r["d"]) for r in rows if r["fam"] != "OURS")
    o_t = np.array([x[0] for x in oth], np.int64); o_d = np.array([x[1] for x in oth])
    print("\nC. other participants' orders received 0-5 ms AFTER our order")
    for name, sel in (("slow (>10 ms)", lambda d: d > SLOW), ("fast (<3 ms)", lambda d: d < 3)):
        v, faster = [], []
        for r in mine:
            if sel(r["d"]):
                a, b = np.searchsorted(o_t, r["ot"]), np.searchsorted(o_t, r["ot"] + 5 * MS)
                if b > a:
                    v.extend(o_d[a:b]); faster.append(np.mean(o_d[a:b] < 3))
        v = np.array(v)
        print(f"   our {name:14s}: n others {len(v):5d}, their p50 {np.median(v):5.2f} ms, slower than 10 ms {np.mean(v > SLOW):5.1%}, "
              f"faster than 3 ms {np.mean(v < 3):5.1%}")

    # E. are the slow senders slow at the same instants (a shared bottleneck) or independently?
    print("\nE. orders of each busy sender received within +-5 ms of OUR order: share slower than 10 ms")
    for g in groups[1:4]:
        gs = sorted((r["ot"], r["d"]) for r in rows if r["fam"] == g)
        g_t = np.array([x[0] for x in gs], np.int64); g_d = np.array([x[1] for x in gs])
        out = []
        for name, sel in (("our slow", lambda d: d > SLOW), ("our fast", lambda d: d < 3)):
            v = []
            for r in mine:
                if sel(r["d"]):
                    a, b = np.searchsorted(g_t, r["ot"] - 5 * MS), np.searchsorted(g_t, r["ot"] + 5 * MS)
                    v.extend(g_d[a:b])
            v = np.array(v)
            out.append(f"when {name}: {np.mean(v > SLOW):5.1%} (n {len(v):4d})" if len(v) else f"when {name}: n 0")
        print(f"   {g:12s} " + " | ".join(out))

    # D. own cancels just before
    print("\nD. our own cancels sent shortly before the order (engine send times, journal)")
    o_send = {}
    for line in open(JOURNAL, encoding="utf-8"):
        e = json.loads(line)
        if e["type"] == "OrderReport" and e["msg"].get("exchange_order_id") and e["msg"]["status"] == "submitted":
            o_send.setdefault(e["msg"]["exchange_order_id"], e["msg"]["ts_ns"])   # first push = exchange receipt (ns)
    with_c, without_c, gaps, cslow = [], [], [], []
    for r in mine:
        a = np.searchsorted(c_send, r["ot"] - 5 * MS); b = np.searchsorted(c_send, r["ot"])
        prev = [cancels[i][1] for i in range(a, b)]
        (with_c if prev else without_c).append(r["d"] > SLOW)
        dts = [done_ts[x] for x in prev if x in done_ts]
        if prev and dts and r["d"] > SLOW:
            gaps.append((r["ts"] - max(dts)) / MS)
            cslow.append((max(dts) - r["ot"]) / MS)
    print(f"   with a cancel of ours in the previous 5 ms: slow {np.mean(with_c):.1%} (n {len(with_c)}); without: slow {np.mean(without_c):.1%} (n {len(without_c)})")
    if gaps:
        g = np.array(gaps)
        print(f"   slow orders with preceding cancels (n {len(g)}): order rests minus last of those cancels done: p10 {np.percentile(g, 10):.1f}, "
              f"p50 {np.median(g):.1f}, p90 {np.percentile(g, 90):.1f} ms; within +-1 ms {np.mean(np.abs(g) <= 1):.0%}; "
              f"cancel done after the order's receipt by p50 {np.median(cslow):.1f} ms")


if __name__ == "__main__":
    main()
