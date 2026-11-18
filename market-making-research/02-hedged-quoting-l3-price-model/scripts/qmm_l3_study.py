"""research3 QMM-1: what is a place near the front of a newly formed touch level worth on KuCoin BTC-USDT perpetual?
Order-by-order replay of our own level3v2 recording (data/research5/usdc_pairs_l3usdt, exchange sequence order).

Written before any result was seen (2026-10-02). Background: every earlier passive test on this contract lost about 1 bp
against a OUR_FEE rebate, with one exception that was never reachable in a model: the first orders of a new touch level
(memory kucoin-backtest-sim-fix: "queue head +0.23 / -0.05 bp"). On 2026-10-02 we measured live that the queue of a new
level is built within ~10 ms (0.04 BTC at birth, 0.10 at 2 ms, 0.27 at 5 ms, 0.56 at 10 ms) and that our orders reach the
exchange ~2.4 ms after the decision (feed ~1.4 ms behind the event). So the question is whether arriving 2-5 ms after a
level is born still buys a position that pays.

  level birth   an `open` order at a price better than the best known price on its side (and not crossing the other side).
                Its gateway time (orderTime, ns) is t0. Levels born in the first 120 s of an hour file are ignored.
  virtual order an infinitesimal post-only order at that price sent so that its gateway time is t0 + d,
                d in {0.5, 1, 2, 3, 5, 10, 30} ms. It stands behind every real order of that level with orderTime <= t0 + d
                and in front of the later ones. It is refused if the price is at or through the other side at that moment.
  fill          the first match whose maker is (a) an order of that level standing behind us, or (b) an order at a worse
                price on our side (the level was traded through).
  cancel        "crowd": when no real order is left at our price we send a cancel, effective tau_c later
                (tau_c = 5 ms and 25 ms: the median and the slow end measured live); also a 5 s time limit.
                "hold1s": no reaction, only a 1 s time limit (reference).
  outcome       maker's markout against the BTC-USDT mid 1 s, 5 s and 10 s after the fill, in bp of the fill price;
                net = 10 s markout + OUR_FEE rebate. Also fill rate and fills per hour.
  reading       QMM-1 is worth turning into a strategy only if, for some d >= 2 ms with the crowd rule at tau_c = 25 ms,
                the net is above zero by more than two standard errors on the development hours AND on the later check day,
                with at least 50 fills per hour. d < 2 ms is shown but is not reachable for us.
  also          the same markout for the REAL orders of new levels by arrival rank (1st, 2nd-3rd, 4th-10th, later):
                what the participants who are actually there earn, with their own cancel skill.
An infinitesimal order has no impact and takes nobody's place: fills per hour are an upper bound for any real size.
usage: Python314/python.exe scripts/research3/qmm_l3_study.py <day> <hours e.g. 16,20 or all> [tag]"""
import glob, gzip, heapq, json, math, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research4"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research5"))
import stale_take_replay as S   # noqa: E402
import l3_parse as LP           # noqa: E402
import active_mm_study as AM    # noqa: E402

SYM = "XBTUSDTM"
L3 = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt")
L2 = os.path.join(ROOT, "data", "research5", "usdc_pairs")
MS = 1_000_000
DELAYS = (0.5, 1, 2, 3, 5, 10, 30)                    # ms after the birth of the level
POLICIES = (("crowd5", 5, 5000), ("crowd25", 25, 5000), ("hold1s", None, 1000))     # name, tau_c ms (None = no reaction), time limit ms
HOR = (1, 5, 10)
WARM = 120_000 * MS
REBATE = OUR_FEE
MULT = 0.001                                          # BTC per contract


def bbo(day):
    snaps = []
    for f in AM.hour_files(day, SYM, "snap", L2):
        for m in AM.json_lines(f):
            d = m.get("data")
            if d and d.get("bids") and d.get("asks"):
                snaps.append((int(d["sequence"]), d["bids"], d["asks"]))
    df = S.bbo_from_events(sorted(snaps, key=lambda x: x[0]), AM.l2_events(AM.hour_files(day, SYM, "l2", L2)), LP.Book())
    return df.t.to_numpy(np.int64), ((df.bb + df.ba) / 2).to_numpy()


class Side:
    """One side of the order-by-order book: price -> {oid: None} in time priority, lazy heap for the best price."""
    __slots__ = ("sgn", "lv", "heap")

    def __init__(self, sgn):
        self.sgn, self.lv, self.heap = sgn, {}, []

    def best(self):
        h, lv, s = self.heap, self.lv, self.sgn
        while h:
            p = -h[0] if s > 0 else h[0]
            if lv.get(p):
                return p
            heapq.heappop(h)
        return None

    def add(self, px, oid):
        q = self.lv.get(px)
        if q is None:
            q = self.lv[px] = {}
            heapq.heappush(self.heap, -px if self.sgn > 0 else px)
        elif not q:
            heapq.heappush(self.heap, -px if self.sgn > 0 else px)
        q[oid] = None

    def remove(self, px, oid):
        q = self.lv.get(px)
        if q is not None:
            q.pop(oid, None)
            return len(q)
        return 0


def run(day, hours, tag):
    bt, bmid = bbo(day)

    def mid_at(t_ms):
        i = np.searchsorted(bt, t_ms, side="right") - 1
        return bmid[i] if i >= 0 else float("nan")

    files = sorted(glob.glob(os.path.join(L3, day, f"??_{SYM}_l3.jsonl.gz")))
    if hours != "all":
        keep = {"%02d" % int(h) for h in hours.split(",")}
        files = [f for f in files if os.path.basename(f)[:2] in keep]
    orders = {}                     # oid -> [sgn, px, size, order_time_ns, birth_key or None, rank]
    book = {1: Side(1), -1: Side(-1)}
    births = {}                     # (sgn, px, t0) -> {"n": opens so far}
    level_birth = {}                # (sgn, px) -> birth key of the level currently alive at that price
    virt = {1: [], -1: []}          # active virtual orders per side
    timers = []                     # (time_ns, seq, virtual)
    res = {(p[0], d): [] for p in POLICIES for d in DELAYS}       # rows: (hour, px, fill_ts_ms, sgn) or None for no fill
    cnt = {(p[0], d): [0, 0] for p in POLICIES for d in DELAYS}   # [sent, refused]
    real = []                       # (rank, sgn, px, size, filled, fill_ts_ms)
    n_births = n_msgs = n_stale = 0
    tseq = 0
    hours_done = []
    for f in files:
        hh = os.path.basename(f)[:2]
        t_first = None
        orders.clear(); births.clear(); level_birth.clear(); virt[1].clear(); virt[-1].clear(); timers.clear()
        book = {1: Side(1), -1: Side(-1)}
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
                    n_msgs += 1
                    if t_first is None:
                        t_first = ts
                    # ---- time-driven transitions of virtual orders (activation, cancel, time limit)
                    while timers and timers[0][0] <= ts:
                        _, _, v, what = heapq.heappop(timers)
                        if v["state"] == "done":
                            continue
                        if what == "activate":
                            opp = book[-v["sgn"]].best()
                            cnt[v["key"]][0] += 1
                            if opp is not None and (v["px"] >= opp if v["sgn"] > 0 else v["px"] <= opp):
                                cnt[v["key"]][1] += 1
                                v["state"] = "done"
                                continue
                            v["state"] = "live"
                            virt[v["sgn"]].append(v)
                            tseq += 1
                            heapq.heappush(timers, (v["t"] + v["limit"] * MS, tseq, v, "end"))
                            if v["tau"] is not None and not book[v["sgn"]].lv.get(v["px"]):
                                tseq += 1
                                heapq.heappush(timers, (ts + v["tau"] * MS, tseq, v, "end"))     # nobody is there: leave
                        elif what == "end":
                            if v["state"] == "live":
                                v["state"] = "done"
                                res[v["key"]].append(None)
                    if sub == "open":
                        sgn = 1 if d["side"] == "buy" else -1
                        px, oid, ot = float(d["price"]), d["orderId"], int(d["orderTime"])
                        side = book[sgn]
                        other = book[-sgn]
                        opp = other.best()
                        while opp is not None and (px >= opp if sgn > 0 else px <= opp):
                            # an order can only rest (open) at px if nothing rests at or through px on the other side:
                            # whatever we still hold there is stale (its removal was not seen: recorder gap, size-0 update)
                            for stale in list(other.lv.get(opp, ())):
                                orders.pop(stale, None)
                                n_stale += 1
                            other.lv[opp] = {}
                            level_birth.pop((-sgn, opp), None)
                            opp = other.best()
                        best = side.best()
                        key = level_birth.get((sgn, px)) if side.lv.get(px) else None
                        if key is None and best is not None and opp is not None and ts - t_first > WARM and (
                                (px > best and px < opp) if sgn > 0 else (px < best and px > opp)):
                            key = (sgn, px, ot)                                  # a new touch level is born
                            births[key] = 0
                            level_birth[(sgn, px)] = key
                            n_births += 1
                            for name, tau, limit in POLICIES:
                                for dl in DELAYS:
                                    v = {"sgn": sgn, "px": px, "t": ot + int(dl * MS), "tau": tau, "limit": limit, "key": (name, dl),
                                         "state": "wait", "hour": hh}
                                    tseq += 1
                                    heapq.heappush(timers, (v["t"], tseq, v, "activate"))
                        elif key is None:
                            level_birth.pop((sgn, px), None)
                        rank = None
                        if key is not None and key in births:
                            births[key] += 1
                            rank = births[key]
                        side.add(px, oid)
                        orders[oid] = [sgn, px, float(d["size"]), ot, rank, 0.0, 0]
                    elif sub == "match":
                        o = orders.get(d["makerOrderId"])
                        if o is None:
                            continue
                        sgn, px, sz = o[0], o[1], float(d["size"])
                        o[2] -= sz
                        o[5] += sz
                        o[6] = ts // MS
                        gone = d.get("remainSize") in ("0", 0)
                        vs = virt[sgn]
                        if vs:
                            keep = []
                            for v in vs:
                                if v["state"] != "live":
                                    continue
                                hit = (px == v["px"] and o[3] > v["t"]) or (px < v["px"] if sgn > 0 else px > v["px"])
                                if hit:
                                    v["state"] = "done"
                                    res[v["key"]].append((v["hour"], v["px"], ts // MS, sgn))
                                else:
                                    keep.append(v)
                            virt[sgn] = keep
                        if not gone:
                            continue
                        d = {"orderId": d["makerOrderId"]}
                        sub = "done"
                    if sub == "update" and d.get("size") in ("0", 0):
                        sub = "done"
                    if sub == "done":
                        o = orders.pop(d["orderId"], None)
                        if o is None:
                            continue
                        left = book[o[0]].remove(o[1], d["orderId"])
                        if o[4] is not None:
                            real.append((o[4], o[0], o[1], o[2] + o[5], o[5], o[6]))
                        if left == 0:
                            level_birth.pop((o[0], o[1]), None)
                            for v in virt[o[0]]:
                                if v["state"] == "live" and v["px"] == o[1] and v["tau"] is not None:
                                    tseq += 1
                                    heapq.heappush(timers, (ts + v["tau"] * MS, tseq, v, "end"))
                    elif sub == "update":
                        o = orders.get(d["orderId"])
                        if o is not None:
                            try:
                                o[2] = float(d["size"])
                            except (KeyError, ValueError):
                                pass
            except EOFError:
                pass
        hours_done.append(hh)
        print(day, hh, "messages so far", n_msgs, "births", n_births, "stale orders purged", n_stale, flush=True)

    H = len(hours_done)
    out = {"day": day, "hours": hours_done, "births": n_births, "rows": []}
    print("\n%s hours %s: %d new touch levels (%.0f per hour)" % (day, ",".join(hours_done), n_births, n_births / max(H, 1)))
    print("policy   delay ms | sent  refused  filled  fill rate  fills/h | markout bp 1 s   5 s   10 s (se) | net incl. rebate (se)")
    for name, tau, limit in POLICIES:
        for dl in DELAYS:
            r = res[(name, dl)]
            sent, refused = cnt[(name, dl)]
            f = [x for x in r if x is not None]
            mk = {h: [] for h in HOR}
            for hh, px, tms, sgn in f:
                for h in HOR:
                    m1 = mid_at(tms + h * 1000)
                    if m1 == m1:
                        mk[h].append(sgn * (m1 - px) / px * 1e4)
            mean = {h: (float(np.mean(mk[h])) if mk[h] else float("nan")) for h in HOR}
            se = float(np.std(mk[10], ddof=1) / math.sqrt(len(mk[10]))) if len(mk[10]) > 1 else float("nan")
            print("%-8s %5.1f    | %5d  %5d  %6d   %5.1f%%   %7.1f | %+6.2f  %+6.2f  %+6.2f (%.2f) | %+6.2f (%.2f)" % (
                name, dl, sent, refused, len(f), 100 * len(f) / max(sent - refused, 1), len(f) / max(H, 1), mean[1], mean[5], mean[10], se, mean[10] + REBATE, se))
            out["rows"].append(dict(policy=name, delay_ms=dl, sent=sent, refused=refused, fills=len(f), m1=mean[1], m5=mean[5], m10=mean[10], se10=se))
    print("\nreal orders of new levels by arrival rank (their own cancel skill): share of posted size that was filled, 5 s markout of the fills")
    for name, lo, hi in (("1st", 1, 1), ("2nd-3rd", 2, 3), ("4th-10th", 4, 10), ("11th+", 11, 10 ** 9)):
        rr = [x for x in real if lo <= x[0] <= hi]
        if not rr:
            continue
        posted = sum(x[3] for x in rr); filled = sum(x[4] for x in rr)
        mk, w = [], []
        for rank, sgn, px, size, fl, tms in rr:
            if fl > 0:
                m1 = mid_at(tms + 5000)
                if m1 == m1:
                    mk.append(sgn * (m1 - px) / px * 1e4); w.append(fl)
        m5 = float(np.average(mk, weights=w)) if mk else float("nan")
        print("  %-8s orders %7d | posted %.1f BTC, filled %.1f BTC (%.1f%%) | 5 s markout %+5.2f bp, with rebate %+5.2f | filled per hour %.2f BTC" % (
            name, len(rr), posted * MULT, filled * MULT, 100 * filled / posted if posted else 0, m5, m5 + REBATE, filled * MULT / max(H, 1)))
    os.makedirs(os.path.join(ROOT, "data", "research3", "qmm"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "data", "research3", "qmm", f"qmm1_{day}_{tag}.json"), "w"), indent=1)


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "all", sys.argv[3] if len(sys.argv) > 3 else "run")
