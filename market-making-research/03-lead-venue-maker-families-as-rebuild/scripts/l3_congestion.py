#!/usr/bin/env python3
"""research5: is our exchange-side entry delay (open.ts - open.orderTime) a congestion effect?

Four read-only tests on the public level3v2 recording plus our journal:
  1. exchange load: messages per 100 ms on XBTUSDCM and XBTUSDTM around each of our orders, slow vs fast;
     and for everybody else, the share of slow orders by load quintile (does the exchange slow down when busy?);
  2. same moment: delay of OTHER participants' orders received within +-20 ms of our order, slow vs fast;
  3. periodicity: share of slow orders by the phase of orderTime within the second (periodic account / risk recompute);
  4. account-serial blocking: for pairs of our orders received within 2 ms of each other - if the first is slow, is
     the second slow too, and does it rest right after the first (one queue per account) or independently?
Usage: .venv/Scripts/python.exe scripts/research5/l3_congestion.py <YYYYMMDD> <hours e.g. 18,19,20,21> <trade_events.jsonl>
"""
import bisect, glob, gzip, json, os, sys, zlib
import numpy as np
import orjson

MS = 1_000_000
ROOTS = {"XBTUSDCM": "data/research5/usdc_pairs", "XBTUSDTM": "data/research5/usdc_pairs_l3usdt"}
SLOW, FAST = 10.0, 3.0


def load(sym, day, hours):
    """-> (sorted ts of every message, list of opens (orderId, orderTime_ns, ts_ns, sequence))."""
    ts_all, opens = [], []
    for f in sorted(glob.glob(os.path.join(ROOTS[sym], day, f"??_{sym}_l3.jsonl.gz"))):
        if os.path.basename(f)[:2] not in hours:
            continue
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    i = line.find(b"\t")
                    if i <= 0:
                        continue
                    d = orjson.loads(line[i + 1:]).get("data") or {}
                    t = d.get("ts")
                    if t is None:
                        continue
                    ts_all.append(int(t))
                    if b'"subject":"open"' in line:
                        opens.append((d["orderId"], int(d["orderTime"]), int(t), int(d["sequence"])))
        except (EOFError, OSError, zlib.error):
            pass
    ts_all.sort()
    return np.array(ts_all, np.int64), opens


def count_in(sorted_ts, lo, hi):
    return bisect.bisect_left(sorted_ts, hi) - bisect.bisect_left(sorted_ts, lo)


def share(v, thr=SLOW):
    v = np.asarray(v, float)
    return f"n {len(v):7d}  p50 {np.median(v):5.2f}  p90 {np.percentile(v, 90):6.2f}  >10ms {np.mean(v > thr):5.1%}" if len(v) else "n 0"


def main():
    day, hours, journal = sys.argv[1], {"%02d" % int(h) for h in sys.argv[2].split(",")}, sys.argv[3]
    ours = set()
    for line in open(journal, encoding="utf-8"):
        e = json.loads(line)
        if e["type"] == "OrderReport" and e["msg"].get("exchange_order_id"):
            ours.add(e["msg"]["exchange_order_id"])
    ts_c, op_c = load("XBTUSDCM", day, hours)
    ts_t, _ = load("XBTUSDTM", day, hours)
    print(f"messages: XBTUSDCM {len(ts_c):,}, XBTUSDTM {len(ts_t):,}; opens XBTUSDCM {len(op_c):,}")
    rows = [(o, (t - ot) / MS, ot, t, s) for o, ot, t, s in op_c if -5 < (t - ot) / MS < 500]
    mine = [r for r in rows if r[0] in ours]
    other = [r for r in rows if r[0] not in ours]
    oth_ot = np.array([r[2] for r in other], np.int64); order = np.argsort(oth_ot)
    oth_ot = oth_ot[order]; oth_d = np.array([r[1] for r in other])[order]
    print(f"our opens {len(mine)}, other opens {len(other):,}\n")

    # 1. load around our orders
    print("1. exchange load (messages in orderTime +-50 ms, i.e. per 100 ms) around OUR orders")
    for name, sel in (("our slow (>10 ms)", lambda d: d > SLOW), ("our fast (<3 ms)", lambda d: d < FAST)):
        sub = [r for r in mine if sel(r[1])]
        lc = [count_in(ts_c, r[2] - 50 * MS, r[2] + 50 * MS) for r in sub]
        lt = [count_in(ts_t, r[2] - 50 * MS, r[2] + 50 * MS) for r in sub]
        print(f"   {name:18s} n {len(sub):5d} | XBTUSDCM median {np.median(lc):6.0f} p90 {np.percentile(lc, 90):6.0f} | "
              f"XBTUSDTM median {np.median(lt):6.0f} p90 {np.percentile(lt, 90):6.0f}")
    print("   everybody else on XBTUSDCM: share slow by load quintile (XBTUSDCM + XBTUSDTM messages per 100 ms)")
    samp = np.arange(0, len(other), max(1, len(other) // 40000))
    lo_ = np.array([count_in(ts_c, oth_ot[i] - 50 * MS, oth_ot[i] + 50 * MS) + count_in(ts_t, oth_ot[i] - 50 * MS, oth_ot[i] + 50 * MS) for i in samp])
    dd = oth_d[samp]; qs = np.percentile(lo_, [20, 40, 60, 80])
    for k in range(5):
        m = (lo_ >= (qs[k - 1] if k else -1)) & (lo_ < (qs[k] if k < 4 else 1e18))
        print(f"     Q{k + 1} load {lo_[m].min():6.0f}-{lo_[m].max():6.0f}: {share(dd[m])}")
    lm = np.array([count_in(ts_c, r[2] - 50 * MS, r[2] + 50 * MS) + count_in(ts_t, r[2] - 50 * MS, r[2] + 50 * MS) for r in mine])
    md = np.array([r[1] for r in mine])
    print("   our orders, same quintile edges:")
    for k in range(5):
        m = (lm >= (qs[k - 1] if k else -1)) & (lm < (qs[k] if k < 4 else 1e18))
        print(f"     Q{k + 1}: {share(md[m])}")

    # 2. others at the same moment
    print("\n2. OTHER participants' orders received within +-20 ms of our order")
    for name, sel in (("our slow (>10 ms)", lambda d: d > SLOW), ("our fast (<3 ms)", lambda d: d < FAST)):
        vals, anyslow = [], []
        for r in mine:
            if not sel(r[1]):
                continue
            a, b = np.searchsorted(oth_ot, r[2] - 20 * MS), np.searchsorted(oth_ot, r[2] + 20 * MS)
            if b > a:
                vals.extend(oth_d[a:b]); anyslow.append(np.max(oth_d[a:b]) > SLOW)
        print(f"   when {name:18s}: others {share(vals)} | moments with any other order >10 ms {np.mean(anyslow):5.1%}")

    # 3. phase within the second
    print("\n3. share of orders slower than 10 ms by orderTime phase within the second (100 ms bins)")
    ph_m = np.array([(r[2] // MS) % 1000 for r in mine]); ph_o = (oth_ot // MS) % 1000
    print("   bin(ms)   ours            others")
    for b in range(10):
        m1 = (ph_m >= b * 100) & (ph_m < b * 100 + 100); m2 = (ph_o >= b * 100) & (ph_o < b * 100 + 100)
        print(f"   {b * 100:3d}-{b * 100 + 99:3d}  {np.mean(md[m1] > SLOW):5.1%} (n {m1.sum():4d})  {np.mean(oth_d[m2] > SLOW):5.1%}")

    # 4. account-serial blocking
    print("\n4. pairs of OUR orders received within 2 ms of each other (first, second by orderTime)")
    ms_ = sorted(mine, key=lambda r: r[2])
    pairs = [(ms_[i], ms_[i + 1]) for i in range(len(ms_) - 1) if ms_[i + 1][2] - ms_[i][2] <= 2 * MS]
    f_slow = [p for p in pairs if p[0][1] > SLOW]; f_fast = [p for p in pairs if p[0][1] < FAST]
    print(f"   pairs {len(pairs)}; P(second slow | first slow) {np.mean([p[1][1] > SLOW for p in f_slow]):.1%} (n {len(f_slow)}), "
          f"P(second slow | first fast) {np.mean([p[1][1] > SLOW for p in f_fast]):.1%} (n {len(f_fast)})")
    both = [p for p in f_slow if p[1][1] > SLOW]
    if both:
        gap = np.array([(p[1][3] - p[0][3]) / MS for p in both]); inord = np.mean([p[1][4] > p[0][4] for p in both])
        oseq = np.sort(np.array([r[4] for r in other], np.int64)); n_between = []
        for p in both:
            lo_s, hi_s = sorted((p[0][4], p[1][4]))
            n_between.append(np.searchsorted(oseq, hi_s) - np.searchsorted(oseq, lo_s, side="right"))
        print(f"   both slow (n {len(both)}): resting-time gap second-first p50 {np.median(gap):.1f} ms, |gap|<=1 ms {np.mean(np.abs(gap) <= 1):.0%}; "
              f"rest in receive order {inord:.0%}; other opens between them median {np.median(n_between):.0f}")
    # runs: are slow orders clustered in time?
    t_slow = np.array([r[2] for r in ms_ if r[1] > SLOW]); t_all = np.array([r[2] for r in ms_])
    for w in (50, 200, 1000):
        near = [(np.searchsorted(t_slow, t + w * MS) - np.searchsorted(t_slow, t - w * MS)) - (1 if d > SLOW else 0) > 0
                for t, d in zip(t_all, [r[1] for r in ms_])]
        near = np.array(near); dsl = np.array([r[1] > SLOW for r in ms_])
        print(f"   P(slow | another of our slow orders within +-{w} ms) {np.mean(dsl[near]):5.1%} (n {near.sum()}) vs otherwise {np.mean(dsl[~near]):5.1%}")


if __name__ == "__main__":
    main()
