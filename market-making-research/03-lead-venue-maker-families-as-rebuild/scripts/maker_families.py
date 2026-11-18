#!/usr/bin/env python3
"""research5 MF-1: who earns money as a maker on KuCoin BTC-USDT, and how do they quote and cancel?

The public order-by-order feed gives every order's clientOid (`received`). Its pattern identifies the program that sent
it ("family"). For every maker fill (`match`) we know the resting order: its family, side, price, when it was opened, where
it was placed relative to the touch, how long it had rested, and the taker's family. Markouts use the L3 mid of
scripts/research3/l3_mid.py (read-only). This is a description of real participants, not a backtest of ours.

One hour file -> data/research5/maker_families/<day>_<hh>.npz (fills, orders) + .json (family names).
Usage: .venv/Scripts/python.exe scripts/research5/maker_families.py hour <YYYYMMDD> <HH>
       .venv/Scripts/python.exe scripts/research5/maker_families.py report <YYYYMMDD> [<YYYYMMDD> ...]
"""
import glob, gzip, heapq, json, os, re, sys, zlib
import numpy as np
import orjson

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt")
OUT = os.path.join(ROOT, "data", "research5", "maker_families")
MID = os.path.join(ROOT, "data", "research3", "px", "l3mid")
SYM = "XBTUSDTM"
MULT = 0.001                  # BTC per contract
REBATE = OUR_FEE                  # bp, our OUR_FEE_TIER maker rebate; other makers' fees are unknown
WARM_NS = 120 * 10**9         # the book only knows orders opened since the file started
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
_RUNS = re.compile(r"\d+|[A-Za-z]+|[^A-Za-z\d]+")


def family(client_oid):
    """clientOid -> sender fingerprint (the program that generated it), from the samples seen on XBTUSDTM:
    pure digits  -> '#<first two digits>|<length>'   (e.g. 1100007510955364400 -> '#11|19')
    UUID / 32 hex -> 'uuid' / 'hex32'
    short literal parts with numbers (20261002x4568915, kcf1621..., 14806-2026..., AA148T3708...) -> letters kept, digit runs -> '#'
    anything else (random letters and digits) -> 'mix:<first 3 characters>|<length>' (no prefix for strings of <= 10 characters)."""
    c = client_oid
    if not c:
        return "none"
    if c.isdigit():
        return "#%s|%d" % (c[:2], len(c))
    if _UUID.match(c):
        return "uuid"
    if _HEX32.match(c):
        return "hex32"
    runs = _RUNS.findall(c)
    if len(runs) <= 5 and all(len(r) <= 5 for r in runs if r[0].isalpha()) and 2 * sum(ch.isdigit() for ch in c) >= len(c):
        return "".join("#" if r[0].isdigit() else r for r in runs)
    return "mix:%s|%d" % (c[:3] if len(c) > 10 else "", len(c))


class Touch:
    """Best bid / ask from order counts per price (integer ticks), heaps with lazy deletion."""

    def __init__(self):
        self.cnt = ({}, {})            # 0 = buy, 1 = sell: tick -> resting orders
        self.heap = ([], [])

    def add(self, side, tick):
        c = self.cnt[side]
        if c.get(tick, 0) <= 0:
            c[tick] = 0
            heapq.heappush(self.heap[side], -tick if side == 0 else tick)
        c[tick] += 1

    def remove(self, side, tick):
        c = self.cnt[side]
        if c.get(tick, 0) > 0:
            c[tick] -= 1

    def best(self, side):
        h, c = self.heap[side], self.cnt[side]
        while h:
            tick = -h[0] if side == 0 else h[0]
            if c.get(tick, 0) > 0:
                return tick
            heapq.heappop(h)
            c.pop(tick, None)
        return None

    def clear_through(self, side, tick):
        """An order rests on `side` at `tick`: nothing can rest on the other side at or through it (stale leftovers)."""
        o = 1 - side
        while True:
            b = self.best(o)
            if b is None or (b > tick if o == 1 else b < tick):
                return
            self.cnt[o][b] = 0


def run_hour(day, hh):
    os.makedirs(OUT, exist_ok=True)
    f = os.path.join(SRC, day, f"{hh}_{SYM}_l3.jsonl.gz")
    fams, fam_ix = [], {}

    def fid(name):
        i = fam_ix.get(name)
        if i is None:
            i = fam_ix[name] = len(fams)
            fams.append(name)
        return i

    fam_of = {}                       # orderId -> family index (from `received`)
    book = {}                         # orderId -> [side, tick, open_ts, fam, dist, size, filled, rank at arrival]
    touch = Touch()
    fills, orders = [], []            # fills: ts, fam, side, tick, size, age_ns, dist, taker_fam, remain, rank, orders at the level ; orders: fam, dist, life_ns, size, filled, end(0 cancel / 1 filled), rank, dist at end
    t_first = None
    try:
        with gzip.open(f, "rb") as fh:
            for line in fh:
                i = line.find(b"\t")
                if i <= 0:
                    continue
                m = orjson.loads(line[i + 1:])
                d = m.get("data")
                s = m.get("subject")
                if not d or not s:
                    continue
                if s == "received":
                    fam_of[d["orderId"]] = fid(family(d.get("clientOid")))
                elif s == "open":
                    t = int(d["ts"])
                    if t_first is None:
                        t_first = t
                    side = 0 if d["side"] == "buy" else 1
                    tick = round(float(d["price"]) * 10)
                    touch.clear_through(side, tick)
                    b = touch.best(side)
                    dist = 9999 if b is None else ((b - tick) if side == 0 else (tick - b))    # < 0 improves the touch, 0 joins
                    rank = touch.cnt[side].get(tick, 0) + 1                                     # 1 = first order at this price
                    book[d["orderId"]] = [side, tick, t, fam_of.get(d["orderId"], fid("unknown")), dist, int(d["size"]), 0, rank]
                    touch.add(side, tick)
                elif s == "match":
                    o = book.get(d["makerOrderId"])
                    t = int(d["ts"])
                    tf = fam_of.get(d["takerOrderId"], fid("unknown"))
                    sz = int(d["size"])
                    if o is None:
                        fills.append((t, fid("pre"), -1, 0, sz, -1, 9999, tf, int(d["remainSize"]), 0, 0))
                    else:
                        o[6] += sz
                        fills.append((t, o[3], o[0], o[1], sz, t - o[2], o[4], tf, int(d["remainSize"]), o[7], touch.cnt[o[0]].get(o[1], 0)))
                        if d["remainSize"] == "0":
                            book.pop(d["makerOrderId"], None)
                            touch.remove(o[0], o[1])
                            orders.append((o[3], o[4], t - o[2], o[5], o[6], 1, o[7], 0))
                elif s == "done":
                    oid = d["orderId"]
                    o = book.pop(oid, None)
                    fam_of.pop(oid, None)
                    if o is not None:
                        b = touch.best(o[0])                                                    # where the order stood when it ended
                        dist_end = 9999 if b is None else ((b - o[1]) if o[0] == 0 else (o[1] - b))
                        touch.remove(o[0], o[1])
                        orders.append((o[3], o[4], int(d["ts"]) - o[2], o[5], o[6], 1 if d.get("reason") == "filled" else 0, o[7], dist_end))
                elif s == "update":
                    o = book.get(d.get("orderId"))
                    if o is not None and d.get("size") is not None:
                        o[5] = int(float(d["size"]))
    except (EOFError, OSError, zlib.error) as e:
        print("damaged tail:", type(e).__name__, flush=True)
    F = np.array(fills, np.int64).reshape(-1, 11)
    O = np.array(orders, np.int64).reshape(-1, 8)
    np.savez_compressed(os.path.join(OUT, f"{day}_{hh}.npz"), fills=F, orders=O, t_first=np.int64(t_first or 0))
    json.dump(fams, open(os.path.join(OUT, f"{day}_{hh}.json"), "w"))
    print(f"{day} {hh}: fills {len(F):,}, ended orders {len(O):,}, families {len(fams)}", flush=True)


class Mid:
    def __init__(self, day):
        z = np.load(os.path.join(MID, f"mid_{day}.npz"))
        self.t, self.m = z["t"], z["m"]

    def at(self, t):
        i = np.searchsorted(self.t, np.asarray(t, np.int64), side="right") - 1
        return np.where(i >= 0, self.m[np.clip(i, 0, len(self.m) - 1)], np.nan)


def load(days):
    """-> fills table (dict of arrays, family as global index), orders table, family names, hours."""
    names, ix = [], {}
    Fs, Os, hours = [], [], 0
    for day in days:
        mid = Mid(day)
        for p in sorted(glob.glob(os.path.join(OUT, f"{day}_??.npz"))):
            z = np.load(p)
            loc = json.load(open(p[:-4] + ".json"))
            mp = np.array([ix.setdefault(n, len(ix)) for n in loc], np.int64)
            names = list(ix)
            F, O = z["fills"], z["orders"]
            if not len(F):
                continue
            keep = (F[:, 0] >= int(z["t_first"]) + WARM_NS) & (F[:, 2] >= 0)
            F = F[keep]
            px = F[:, 3] / 10.0
            sg = np.where(F[:, 2] == 0, 1.0, -1.0)                         # the maker bought (+1) or sold (-1)
            mo = {h: sg * (mid.at(F[:, 0] + h * 10**9) - px) / px * 1e4 for h in (1, 10, 60)}
            m0 = sg * (mid.at(F[:, 0] - 1) - px) / px * 1e4                # mid just before the fill: the half spread earned
            Fs.append(dict(t=F[:, 0], fam=mp[F[:, 1]], side=F[:, 2], px=px, size=F[:, 4], age=F[:, 5] / 1e6, dist=F[:, 6],
                           tfam=mp[F[:, 7]], rank=F[:, 9], lvl=F[:, 10], m0=m0, m1=mo[1], m10=mo[10], m60=mo[60]))
            Os.append(dict(fam=mp[O[:, 0]], dist=O[:, 1], life=O[:, 2] / 1e6, size=O[:, 3], filled=O[:, 4], end=O[:, 5], rank=O[:, 6], dist_end=O[:, 7]))
            hours += 1
    cat = lambda L: {k: np.concatenate([x[k] for x in L]) for k in L[0]}
    return cat(Fs), cat(Os), names, hours


def report(days):
    F, O, names, hours = load(days)
    ok = np.isfinite(F["m10"])
    notional = F["size"] * MULT * F["px"]
    print(f"days {days}: {hours} hours; maker fills {len(F['t']):,} (markout known for {ok.mean():.0%}); notional ${notional.sum() / 1e6:,.0f}M")
    self_ = F["fam"] == F["tfam"]
    print(f"fills where maker and taker have the same clientOid pattern: {self_.mean():.1%} of fills, {notional[self_].sum() / notional.sum():.1%} of notional")
    tot = notional.sum()
    order = np.argsort(-np.bincount(F["fam"], weights=notional, minlength=len(names)))
    print("\nper maker family (size-weighted bp; net10 = 10 s markout + %.1f rebate; 'x-self' = excluding fills against its own pattern)" % REBATE)
    print(f"{'family':24s} {'$M':>7s} {'share':>6s} {'fills/h':>8s} {'self%':>6s} {'spread':>7s} {'m1s':>7s} {'m10s':>7s} {'m60s':>7s} {'net10':>7s} {'net10 x-self':>12s} {'t':>6s} "
          f"{'fill%':>6s} {'life p50':>9s} {'improve/join/deep':>18s} {'age<20ms':>9s}")
    def w(v, m):
        m = m & np.isfinite(v)
        return np.average(v[m], weights=notional[m]) if m.any() else np.nan

    def by_hour(m):
        """-> (t of the hourly size-weighted net10, share of hours > 0)."""
        hr = F["t"][m] // (3600 * 10**9)
        net = (F["m10"][m] + REBATE) * notional[m]
        hv = np.array([net[hr == h].sum() / notional[m][hr == h].sum() for h in np.unique(hr)]) if m.any() else np.array([])
        if len(hv) < 3:
            return np.nan, np.nan
        return hv.mean() / (hv.std(ddof=1) / np.sqrt(len(hv))), np.mean(hv > 0)

    shown = []
    for fi in order[:25]:
        m = (F["fam"] == fi) & ok
        if m.sum() < 300:
            continue
        shown.append(fi)
        mx = m & ~self_
        tstat, pos = by_hour(mx)
        om = O["fam"] == fi
        d = O["dist"][om]
        plc = "%2.0f/%2.0f/%2.0f" % (100 * np.mean(d < 0), 100 * np.mean(d == 0), 100 * np.mean((d > 0)))
        print(f"{names[fi][:24]:24s} {notional[m].sum() / 1e6:7.1f} {notional[m].sum() / tot:6.1%} {m.sum() / hours:8.0f} {self_[m].mean():6.1%} "
              f"{w(F['m0'], m):7.2f} {w(F['m1'], m):7.2f} {w(F['m10'], m):7.2f} {w(F['m60'], m):7.2f} {w(F['m10'], m) + REBATE:7.2f} "
              f"{w(F['m10'], mx) + REBATE:12.2f} {tstat:6.1f} "
              f"{np.mean(O['filled'][om] > 0):6.1%} {np.median(O['life'][om]):9.0f} {plc:>18s} {np.mean(F['age'][m] < 20):9.1%}")
    mall = ok & ~self_
    print(f"{'ALL MAKERS (x-self)':24s} {notional[mall].sum() / 1e6:7.1f} {'':6s} {mall.sum() / hours:8.0f} {'':6s} "
          f"{w(F['m0'], mall):7.2f} {w(F['m1'], mall):7.2f} {w(F['m10'], mall):7.2f} {w(F['m60'], mall):7.2f} {w(F['m10'], mall) + REBATE:7.2f} "
          f"{'':12s} {by_hour(mall)[0]:6.1f}")

    # where the money is made: all makers, then each shown family
    def cut(title, key, bins, labels, m0):
        print(f"   {title}: " + "  ".join(
            f"{l} {w(F['m10'], m0 & b) + REBATE:+.2f} ({notional[m0 & b].sum() / max(notional[m0].sum(), 1):.0%})" for l, b in zip(labels, bins)))

    rank_b = [F["rank"] == 1, (F["rank"] >= 2) & (F["rank"] <= 3), (F["rank"] >= 4) & (F["rank"] <= 10), F["rank"] > 10]
    rank_l = ["1st", "2-3", "4-10", ">10"]
    dist_b = [F["dist"] < 0, F["dist"] == 0, (F["dist"] > 0) & (F["dist"] <= 5), F["dist"] > 5]
    dist_l = ["improve", "join", "1-5 back", "deeper"]
    age_b = [F["age"] < 20, (F["age"] >= 20) & (F["age"] < 200), (F["age"] >= 200) & (F["age"] < 2000), (F["age"] >= 2000) & (F["age"] < 20000), F["age"] >= 20000]
    age_l = ["<20ms", "20-200ms", "0.2-2s", "2-20s", ">20s"]
    print("\nnet10 (bp, size-weighted, with %.1f rebate) and share of the family's maker notional, excluding fills against its own pattern" % REBATE)
    for fi in [-1] + shown[:12]:
        m0 = mall if fi < 0 else (F["fam"] == fi) & mall
        print(("ALL MAKERS" if fi < 0 else names[fi]) + f"  (t by hour {by_hour(m0)[0]:.1f}, hours > 0 {by_hour(m0)[1]:.0%})")
        cut("arrival rank at its price", "rank", rank_b, rank_l, m0)
        cut("placement when opened    ", "dist", dist_b, dist_l, m0)
        cut("time resting before fill ", "age", age_b, age_l, m0)
        if fi >= 0:
            om = (O["fam"] == fi)
            c = om & (O["end"] == 0) & (O["filled"] == 0)
            life = O["life"][c]
            de = O["dist_end"][c]
            print(f"   cancels (never filled): {c.sum() / hours:,.0f}/h; life p10/p50/p90 {np.percentile(life, 10):.0f}/{np.median(life):.0f}/{np.percentile(life, 90):.0f} ms; "
                  f"at the touch when cancelled {np.mean(de <= 0):.0%}, 1-5 ticks back {np.mean((de > 0) & (de <= 5)):.0%}, deeper {np.mean(de > 5):.0%}; "
                  f"orders/h {om.sum() / hours:,.0f}, filled {np.mean(O['filled'][om] > 0):.2%}, median size {np.median(O['size'][om]):.0f} contracts")


def _main():
    if sys.argv[1] == "hour":
        run_hour(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "report":
        report(sys.argv[2:])


def depth_report(days):
    """Where is the maker's edge: by distance of the fill price from the mid just before the fill, and each family's
    whole trade stream on this contract (maker + taker fills) marked to the mid."""
    F, O, names, hours = load(days)
    notional = F["size"] * MULT * F["px"]
    ok = np.isfinite(F["m10"]) & np.isfinite(F["m0"]) & (F["fam"] != F["tfam"])

    def w(v, m):
        m = m & np.isfinite(v)
        return np.average(v[m], weights=notional[m]) if m.any() else np.nan

    edges = [-99, 0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 99]
    labels = ["<0 (through mid)", "0-0.25", "0.25-0.5", "0.5-1", "1-2", "2-4", ">4"]
    dbp = F["dist"] * 0.1 / F["px"] * 1e4                       # distance behind the same-side best when the order was opened, bp

    def table(title, m0):
        print(f"\n{title}: maker markout by distance of the fill price from the mid just before the fill (bp; + {REBATE} rebate in the net columns)")
        print(f"   {'distance bp':18s} {'share':>6s} {'$M':>7s} {'fills/h':>8s} {'m1s':>7s} {'m10s':>7s} {'m60s':>7s} {'net1':>7s} {'net10':>7s} {'net60':>7s} {'hours>0':>8s}")
        for a, b, l in zip(edges[:-1], edges[1:], labels):
            m = m0 & (F["m0"] >= a) & (F["m0"] < b)
            if m.sum() < 50:
                continue
            hr = F["t"][m] // (3600 * 10**9)
            hv = np.array([np.average(F["m10"][m][hr == h], weights=notional[m][hr == h]) + REBATE for h in np.unique(hr)])
            print(f"   {l:18s} {notional[m].sum() / notional[m0].sum():6.1%} {notional[m].sum() / 1e6:7.1f} {m.sum() / hours:8.0f} {w(F['m1'], m):7.2f} {w(F['m10'], m):7.2f} {w(F['m60'], m):7.2f} "
                  f"{w(F['m1'], m) + REBATE:7.2f} {w(F['m10'], m) + REBATE:7.2f} {w(F['m60'], m) + REBATE:7.2f} {np.mean(hv > 0):8.0%}")

    table("ALL MAKERS", ok)
    top = np.argsort(-np.bincount(F["fam"][ok], weights=notional[ok], minlength=len(names)))[:8]
    for fi in top:
        table(names[fi], ok & (F["fam"] == fi))

    print("\nALL MAKERS: net10 by how far behind the same-side best the order was when OPENED (bp) x how long it rested")
    de = [(-99, 0.0001, "at/inside touch"), (0.0001, 0.5, "0-0.5 bp back"), (0.5, 2, "0.5-2"), (2, 5, "2-5"), (5, 9999, ">5")]
    ag = [(0, 200, "<0.2 s"), (200, 2000, "0.2-2 s"), (2000, 20000, "2-20 s"), (20000, 1e12, ">20 s")]
    print("   " + " " * 18 + "".join(f"{l:>22s}" for _, _, l in ag))
    for a, b, l in de:
        row = []
        for c, d, _ in ag:
            m = ok & (dbp >= a) & (dbp < b) & (F["age"] >= c) & (F["age"] < d)
            row.append(f"{w(F['m10'], m) + REBATE:+6.2f} ({notional[m].sum() / notional[ok].sum():4.0%})" if m.sum() >= 100 else f"{'-':>13s}")
        print(f"   {l:18s}" + "".join(f"{x:>22s}" for x in row))

    # each family's whole trade stream on this contract: maker fills (+) and taker fills
    print("\nwhole trade stream per family on this contract, marked to the mid (bp of traded notional; fees not included)")
    print(f"   {'family':14s} {'maker $M':>9s} {'taker $M':>9s} {'taker share':>11s} {'PnL at +10 s':>13s} {'PnL at +60 s':>13s} {'PnL at hour end':>16s} {'max |inv| BTC':>14s}")
    allok = np.isfinite(F["m10"])
    sgn = np.where(F["side"] == 0, 1.0, -1.0)                   # maker side
    hour_id = F["t"] // (3600 * 10**9)
    for fi in top:
        mk = allok & (F["fam"] == fi)
        tk = allok & (F["tfam"] == fi)
        mn, tn = notional[mk].sum(), notional[tk].sum()
        p10 = (F["m10"][mk] * notional[mk]).sum() - (F["m10"][tk] * notional[tk]).sum()
        m60k, t60k = mk & np.isfinite(F["m60"]), tk & np.isfinite(F["m60"])
        p60 = (F["m60"][m60k] * notional[m60k]).sum() - (F["m60"][t60k] * notional[t60k]).sum()
        # inventory and mark at the end of each hour: use the last fill price of the hour as the mark
        pnl_h, max_inv = 0.0, 0.0
        for h in np.unique(hour_id):
            sel = (hour_id == h) & (mk | tk)
            if not sel.any():
                continue
            q = F["size"][sel] * MULT * np.where(F["fam"][sel] == fi, sgn[sel], -sgn[sel])
            q = np.where((F["fam"][sel] == fi) & (F["tfam"][sel] == fi), 0.0, q)
            px = F["px"][sel]
            last = F["px"][hour_id == h][-1]
            inv = np.cumsum(q)
            max_inv = max(max_inv, np.abs(inv).max())
            pnl_h += (q * (last - px)).sum()
        print(f"   {names[fi][:14]:14s} {mn / 1e6:9.1f} {tn / 1e6:9.1f} {tn / max(mn + tn, 1):11.1%} {p10 / max(mn + tn, 1):13.2f} {p60 / max(mn + tn, 1):13.2f} "
              f"{pnl_h / max(mn + tn, 1) * 1e4:16.2f} {max_inv:14.2f}")


if __name__ == "__main__":
    if sys.argv[1] == "depth":
        depth_report(sys.argv[2:])
    else:
        _main()
