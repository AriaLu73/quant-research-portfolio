#!/usr/bin/env python3
"""research5 HDG-1: what does it really cost to hedge on the KuCoin BTC-USDT perpetual with a resting order?

Order-by-order replay of our own level3v2 recording (data/research5/usdc_pairs_l3usdt), so the place of our order in the
queue is exact. The book logic follows scripts/research3/qmm_l3_study.py (QMM-1, another session's study of new levels);
this file asks the hedging question that the live run of 2026-10-02 raised: the strategy hedged with an order that joined
an old, full price level and it cost 2.9 bp against the mid at the moment of the quote fill.

  need      a hedge of direction sgn (+1 buy, -1 sell) is needed at time t. Two samples:
              "flow"  the real (not self-traded) taker orders on the BTC-USDC contract: a taker buy lifts our ask, we must buy BTC-USDT
              "grid"  one need every GRID_S seconds with a random direction (how the market treats a hedge that carries no information)
  taker     benchmark: a market order arriving LAT after the need, filled at the opposite best price, fee OUR_FEE
  join      what the live strategy did: LAT after the need, rest at the current best price on our side, BEHIND everything
            already there; whenever a better price level is born on our side, move to it (we arrive LAT after its birth)
  wait      do not join the old level: rest only at levels born after the need (arriving LAT after each birth, near the front)
  time limit after T seconds without a fill the remainder is taken at the opposite best price (taker fee)
  fill      a real trade whose maker order stood behind us at our price, or a trade at a worse price on our side
  cost (bp) = how much worse the hedge price is than the BTC-USDT mid at the moment of the need, minus the OUR_FEE rebate
              for a resting fill or plus the OUR_FEE fee for a taker fill. Positive = it costs.
Our order is infinitesimal (it takes nobody's place and moves no price): fills are an upper bound for a real size.
Usage: Python314/python.exe scripts/research5/hedge_l3_study.py 20261001 [hours e.g. 16,17,18 | all] [lat_ms]
"""
import glob, gzip, heapq, json, math, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L3 = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt")
PAIRS = os.path.join(ROOT, "data", "research5", "usdc_pairs")
SYM = "XBTUSDTM"
MS = 1_000_000
LAT_MS = 4.0                      # feed 1.4 ms behind the event + 2.4 ms until our order is at the exchange (measured live 2026-10-02)
TIMEOUTS_S = (1, 5, 30)
INITS = ("join", "wait")
TAKER_BP, REBATE_BP = OUR_FEE, 0.7
WARM_NS = 120_000 * MS            # orders resting from before an hour file starts are unknown: no needs in its first two minutes
GRID_S = 3.0


def hedge_cost_bp(sgn, mid_need, fill_px, maker):
    """Cost of a hedge of direction sgn filled at fill_px, against the mid at the moment of the need, incl. fee / rebate."""
    return sgn * (fill_px - mid_need) / mid_need * 1e4 + (-REBATE_BP if maker else TAKER_BP)


def flow_needs(t_ms, taker_sgn):
    """Hedge needs created by real taker orders on the quoted contract: (time ns, hedge direction). A taker buy takes our
    ask, we are short and must buy the hedge contract: the hedge has the taker's direction."""
    return [(int(t) * MS, int(s), "flow") for t, s in zip(t_ms, taker_sgn)]


def grid_needs(t0_ns, t1_ns, step_s=GRID_S, seed=7):
    rng = np.random.default_rng(seed)
    ts = np.arange(t0_ns, t1_ns, int(step_s * 1e9), dtype=np.int64)
    return [(int(t), int(s), "grid") for t, s in zip(ts, rng.choice([1, -1], len(ts)))]


class Side:
    """One side of the order-by-order book: price -> {order id: None} in time priority, lazy heap for the best price
    (same structure as in scripts/research3/qmm_l3_study.py)."""
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
        if q is None or not q:
            if q is None:
                q = self.lv[px] = {}
            heapq.heappush(self.heap, -px if self.sgn > 0 else px)
        q[oid] = None

    def remove(self, px, oid):
        q = self.lv.get(px)
        if q is not None:
            q.pop(oid, None)


def better(sgn, a, b):
    """Price a is a better resting price than b for an order of direction sgn (a buy wants to rest higher)."""
    return a > b if sgn > 0 else a < b


def crosses(sgn, px, opp):
    return opp is not None and (px >= opp if sgn > 0 else px <= opp)


def replay(msgs, needs, lat_ms=LAT_MS, timeouts=TIMEOUTS_S, inits=INITS, warm_ns=WARM_NS):
    """msgs: iterable of (subject, data) of one continuous level3 stream in exchange order; needs: [(t ns, sgn, tag)] sorted.
    Returns one dict per (need, policy): tag, init ("taker" / "join" / "wait"), timeout_s, maker, wait_ms, cost_bp."""
    lat = int(lat_ms * MS)
    orders, book = {}, {1: Side(1), -1: Side(-1)}
    jobs = {1: [], -1: []}            # live hedge orders by the book side they rest on
    timers, tseq, rows, ni, t_first = [], 0, [], 0, None

    def finish(j, ts, px, maker):
        j["state"] = "done"
        rows.append(dict(tag=j["tag"], init=j["init"], timeout_s=j["T"], maker=maker, wait_ms=(ts - j["t"]) / MS, cost_bp=hedge_cost_bp(j["sgn"], j["mid"], px, maker), sgn=j["sgn"], t=j["t"]))

    def push(t, j, what, px=None):
        nonlocal tseq
        tseq += 1
        heapq.heappush(timers, (t, tseq, j, what, px))

    for sub, d in msgs:
        if sub == "received" or not d:
            continue
        ts = int(d["ts"])
        if t_first is None:
            t_first = ts
        # ---- needs whose order can now be at the exchange
        while ni < len(needs) and needs[ni][0] + lat <= ts:
            tn, sgn, tag = needs[ni]
            ni += 1
            bb, ba = book[1].best(), book[-1].best()
            if tn - t_first < warm_ns or bb is None or ba is None or ba <= bb:
                continue
            mid = (bb + ba) / 2
            opp = ba if sgn > 0 else bb
            rows.append(dict(tag=tag, init="taker", timeout_s=0, maker=False, wait_ms=lat / MS, cost_bp=hedge_cost_bp(sgn, mid, opp, False), sgn=sgn, t=tn))
            for init in inits:
                for T in timeouts:
                    j = dict(sgn=sgn, t=tn, mid=mid, tag=tag, init=init, T=T, state="live", px=None, t_post=None)
                    if init == "join":
                        j["px"], j["t_post"] = (bb if sgn > 0 else ba), tn + lat
                    jobs[sgn].append(j)
                    push(tn + int(T * 1e9), j, "deadline")
        # ---- time-driven: moves to a newly born level, time limits
        while timers and timers[0][0] <= ts:
            t_ev, _, j, what, px = heapq.heappop(timers)
            if j["state"] != "live":
                continue
            if what == "move":
                if (j["px"] is None or better(j["sgn"], px, j["px"])) and not crosses(j["sgn"], px, book[-j["sgn"]].best()) and book[j["sgn"]].lv.get(px):
                    j["px"], j["t_post"] = px, t_ev
            else:                                                   # deadline: take the opposite best price
                opp = book[-j["sgn"]].best()
                if opp is None:
                    j["state"] = "done"
                else:
                    finish(j, t_ev, opp, False)
        if sub == "open":
            sgn = 1 if d["side"] == "buy" else -1
            px, oid, ot = float(d["price"]), d["orderId"], int(d["orderTime"])
            side, other = book[sgn], book[-sgn]
            opp = other.best()
            while opp is not None and (px >= opp if sgn > 0 else px <= opp):   # stale orders on the other side (recorder gap): purge
                for stale in list(other.lv.get(opp, ())):
                    orders.pop(stale, None)
                other.lv[opp] = {}
                opp = other.best()
            best = side.best()
            if best is not None and opp is not None and better(sgn, px, best):          # a new touch level is born on this side
                for j in jobs[sgn]:
                    if j["state"] == "live":
                        push(ot + lat, j, "move", px)
            side.add(px, oid)
            orders[oid] = [sgn, px, ot]
        elif sub == "match":
            o = orders.get(d["makerOrderId"])
            if o is None:
                continue
            sgn, px = o[0], o[1]
            live = []
            for j in jobs[sgn]:
                if j["state"] != "live":
                    continue
                if j["px"] is not None and j["t_post"] <= ts and ((px == j["px"] and o[2] > j["t_post"]) or better(sgn, j["px"], px)):
                    finish(j, ts, j["px"], True)
                else:
                    live.append(j)
            jobs[sgn] = live
            if d.get("remainSize") in ("0", 0):
                orders.pop(d["makerOrderId"], None)
                side_ = book[sgn]
                side_.remove(px, d["makerOrderId"])
        elif sub == "done" or (sub == "update" and d.get("size") in ("0", 0)):
            o = orders.pop(d["orderId"], None)
            if o is not None:
                book[o[0]].remove(o[1], d["orderId"])
    return rows


def l3_msgs(path):
    with gzip.open(path, "rt") as fh:
        try:
            for line in fh:
                i = line.find("\t")
                if i <= 0:
                    continue
                try:
                    m = json.loads(line[i + 1:])
                except ValueError:
                    continue
                yield m.get("subject"), m.get("data")
        except (EOFError, OSError):
            return


def summarize(rows, hours):
    import pandas as pd
    d = pd.DataFrame(rows)
    out = []
    for (tag, init, T), g in d.groupby(["tag", "init", "timeout_s"]):
        c = g.cost_bp.to_numpy()
        out.append(dict(sample=tag, policy=init, limit_s=T, n=len(g), resting_fill=float(g.maker.mean()), wait_s_median=float(np.median(g.wait_ms)) / 1000,
                        wait_s_mean=float(g.wait_ms.mean()) / 1000, cost_bp=float(c.mean()), se=float(c.std(ddof=1) / math.sqrt(len(c))) if len(c) > 1 else float("nan"),
                        cost_p10=float(np.percentile(c, 10)), cost_p50=float(np.percentile(c, 50)), cost_p90=float(np.percentile(c, 90)),
                        cost_resting=float(g.cost_bp[g.maker].mean()) if g.maker.any() else float("nan"), cost_taken=float(g.cost_bp[~g.maker].mean()) if (~g.maker).any() else float("nan")))
    return pd.DataFrame(out)


def main():
    import pandas as pd
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import active_mm_study as A
    day = sys.argv[1]
    hours = sys.argv[2] if len(sys.argv) > 2 else "all"
    lat = float(sys.argv[3]) if len(sys.argv) > 3 else LAT_MS
    files = sorted(glob.glob(os.path.join(L3, day, f"??_{SYM}_l3.jsonl.gz")))
    if hours != "all":
        keep = {"%02d" % int(h) for h in hours.split(",")}
        files = [f for f in files if os.path.basename(f)[:2] in keep]
    real, _ = A.load_orders(day, "XBTUSDCM", 0.0001, root=PAIRS)
    rows = []
    for f in files:
        hh = int(os.path.basename(f)[:2])
        t0 = int(pd.Timestamp(f"{day[:4]}-{day[4:6]}-{day[6:]} {hh:02d}:00:00", tz="UTC").value)
        t1 = t0 + 3600 * 10**9
        r = real[(real.t * MS >= t0) & (real.t * MS < t1)]
        needs = sorted(flow_needs(r.t.to_numpy(), r.sgn.to_numpy()) + grid_needs(t0, t1))
        got = replay(l3_msgs(f), needs, lat_ms=lat)
        rows += got
        print(day, "%02d" % hh, "needs", len(needs), "(flow %d)" % len(r), "rows", len(got), flush=True)
    s = summarize(rows, len(files))
    pd.set_option("display.width", 250)
    print(f"\nHDG-1 {day} hours {hours}, our order arrives {lat:g} ms after the need / after a level is born; cost in bp of the hedge, + = worse than the mid at the moment of the need, incl. OUR_FEE rebate (resting) or OUR_FEE fee (taken)")
    print(s.sort_values(["sample", "policy", "limit_s"]).round(2).to_string(index=False))
    os.makedirs(os.path.join(ROOT, "data", "research5", "hedge"), exist_ok=True)
    pd.DataFrame(rows).to_parquet(os.path.join(ROOT, "data", "research5", "hedge", f"hdg1_{day}_{hours.replace(',', '-')}_lat{lat:g}.parquet"))


if __name__ == "__main__":
    main()
