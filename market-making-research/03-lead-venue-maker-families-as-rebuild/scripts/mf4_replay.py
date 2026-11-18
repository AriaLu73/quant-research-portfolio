#!/usr/bin/env python3
"""research5 MF-4b: strategy replay of OUR ladder on KuCoin BTC-USDT, anchored on the Binance price, with real queue priority.

Modelled on the four large "#01|20" sessions (MF-3): quotes outside the touch at fixed distances from an external fair
value, re-posted as soon as the fair value moves. Development replay on 10-01 / 10-02 (both days already used: no verdict).

fair value   F(t) = Binance BTCUSDT last trade price seen d_bn ms after its trade time + basis(t); basis = median of
             (KuCoin mid - Binance price) over the previous 5 minutes on a 1 s grid (mf4_hedged_edge.Fair).
ladder       level k on each side at F * (1 -/+ delta_k); one order of size_k contracts per level and side.
re-quote     when the wanted price differs from the resting one by h bp or more: the old order is cancelled (still fillable
             until tau_c ms later) and the new one rests tau_o ms later, behind every order already at that price.
             Post-only: a new order that would cross the KuCoin touch is rejected. One pending replacement per slot.
fills        the public matches are grouped per taker order (one sweep). Our orders are inserted by price / time priority:
             an order of ours is ahead of every real maker fill at a worse price and of real makers at its own price that
             arrived after it. The taker's total volume is fixed: what we take is no longer available further down.
position     not limited here (user 2026-10-03: capital is not a design constraint); optional skew of the fair value by
             skew_bp per BTC of position. Every fill is written with its time so that the hedge on Binance (delay, fee)
             is evaluated afterwards (mf4_eval.py).
Not modelled: our own impact beyond taking the sweep's volume first; rate limits (message counts are reported).
Usage: .venv/Scripts/python.exe scripts/research5/mf4_replay.py <YYYYMMDD> <HH> <config name>
"""
import collections, gzip, heapq, json, os, sys, zlib
import numpy as np
import orjson

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import maker_families as M

MS = 1_000_000
OUT = os.path.join(M.OUT, os.environ.get("MF4_OUT", "mf4"))          # MF4_OUT=mf4b: rerun with stream-break handling
CONFIGS = {
    # deltas bp, sizes in contracts (0.001 BTC), re-quote threshold bp, order / cancel latency ms, Binance data delay ms, skew bp per BTC
    "A":  dict(deltas=(1.0, 2.0, 3.5), sizes=(1000, 1000, 1000), h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0),
    "B":  dict(deltas=(1.0, 2.0, 3.5), sizes=(1000, 1000, 1000), h=0.15, tau_o=50.0, tau_c=50.0, d_bn=2.0, skew=0.0),   # exchange congested all the time
    "C":  dict(deltas=(0.5, 1.5, 3.0), sizes=(1000, 1000, 1000), h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0),
    "D":  dict(deltas=(1.0, 2.0, 3.5), sizes=(1000, 1000, 1000), h=0.15, tau_o=2.0, tau_c=4.0, d_bn=15.0, skew=0.0),    # Binance data 15 ms late
    "E":  dict(deltas=(1.5, 2.5, 4.0), sizes=(1000, 1000, 1000), h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0),
    "F":  dict(deltas=(2.0, 3.0, 5.0), sizes=(1000, 1000, 1000), h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0),
    "G":  dict(deltas=(1.0, 2.0, 3.5), sizes=(1000, 1000, 1000), h=0.15, tau_o=1.0, tau_c=1.0, d_bn=1.0, skew=0.0),     # fast: 1 ms everywhere
    # pull-and-wait (seen in the large sessions around Binance jumps, MF-4b): when the fair value has moved `jump` bp or more
    # within `jwin` ms, the side it runs into is cancelled and not re-posted until `cool` ms after the last such move
    "H":  dict(deltas=(1.0, 2.0, 3.5), sizes=(1000, 1000, 1000), h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0, jump=0.5, jwin=20.0, cool=100.0),
    "I":  dict(deltas=(1.0, 2.0, 3.5), sizes=(1000, 1000, 1000), h=0.15, tau_o=1.0, tau_c=1.0, d_bn=1.0, skew=0.0, jump=0.5, jwin=20.0, cool=100.0),
    "J":  dict(deltas=(1.0, 2.0, 3.5), sizes=(1000, 1000, 1000), h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0, jump=1.0, jwin=20.0, cool=100.0),
    "K":  dict(deltas=(1.0, 2.0, 3.5), sizes=(1000, 1000, 1000), h=0.15, tau_o=50.0, tau_c=50.0, d_bn=2.0, skew=0.0, jump=0.5, jwin=20.0, cool=100.0),
    "L":  dict(deltas=(1.5, 2.5, 4.0), sizes=(1000, 1000, 1000), h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0, jump=0.5, jwin=20.0, cool=100.0),
    "M":  dict(deltas=(1.0, 2.0, 3.5), sizes=(1000, 1000, 1000), h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0, jump=0.3, jwin=50.0, cool=300.0),
    # v2 (MF-5, from the literature): a level is quoted only while its distance covers what Binance can do before our cancel
    # is effective - buffer = kbuf x q99(|move over tau| given the trades of the last 100 ms), fitted on the OTHER day
    # (Moallemi-Saglam 2013 scaling; Budish-Cramton-Shim 2015 break-even) - and the fair value carries the short-term drift
    # predicted from the last 50 ms of Binance price change and signed volume (Lehalle-Neuman 2019).
    "V1": dict(deltas=(0.5, 1.0, 2.0, 3.5, 6.0), sizes=(1000,) * 5, h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0, v2=True, kbuf=1.0, tau_tab="6.5", drift=True),
    "V2": dict(deltas=(0.5, 1.0, 2.0, 3.5, 6.0), sizes=(1000,) * 5, h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0, v2=True, kbuf=1.0, tau_tab="26.5", drift=True),
    "V3": dict(deltas=(0.5, 1.0, 2.0, 3.5, 6.0), sizes=(1000,) * 5, h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0, v2=True, kbuf=1.5, tau_tab="26.5", drift=True),
    "V4": dict(deltas=(0.5, 1.0, 2.0, 3.5, 6.0), sizes=(1000,) * 5, h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0, v2=True, kbuf=1.0, tau_tab="26.5", drift=False),
    "V5": dict(deltas=(0.5, 1.0, 2.0, 3.5, 6.0), sizes=(1000,) * 5, h=0.15, tau_o=50.0, tau_c=50.0, d_bn=2.0, skew=0.0, v2=True, kbuf=1.0, tau_tab="50.0", drift=True),   # congested
    "V6": dict(deltas=(0.5, 1.0, 2.0, 3.5, 6.0), sizes=(1000,) * 5, h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, skew=0.0, v2=True, kbuf=2.0, tau_tab="50.0", drift=True),
}
# W: the next version (2026-10-05): deep levels only, optional multi-venue fair value (mf6_fair.py), larger size on deep
# levels, a cap on the KuCoin position (only the reducing side is quoted beyond it) and a skew of the fair value per BTC held.
_W = dict(h=0.15, tau_o=2.0, tau_c=4.0, d_bn=2.0, v2=True, kbuf=1.5, tau_tab="26.5", drift=False)
CONFIGS.update({
    "W1": dict(_W, deltas=(2.0, 3.5, 6.0, 9.0), sizes=(1000, 1000, 1000, 1000), skew=0.0),
    "W2": dict(_W, deltas=(2.0, 3.5, 6.0, 9.0), sizes=(1000, 1000, 1000, 1000), skew=0.0, fair="all"),
    "W3": dict(_W, deltas=(2.0, 3.5, 6.0, 9.0), sizes=(1000, 2000, 3000, 3000), skew=0.0, fair="all"),
    "W4": dict(_W, deltas=(2.0, 3.5, 6.0, 9.0), sizes=(1000, 2000, 3000, 3000), skew=0.1, fair="all", cap=5.0),
    "W5": dict(_W, deltas=(2.0, 3.5, 6.0, 9.0), sizes=(250, 500, 750, 750), skew=0.5, fair="all", cap=1.0),       # sized for about $20k
    "W6": dict(_W, deltas=(2.0, 3.5, 6.0, 9.0), sizes=(1000, 1000, 1000, 1000), skew=0.0, fair="all0"),          # every venue seen after 2 ms (upper bound)
    "W7": dict(_W, deltas=(2.0, 3.5, 6.0, 9.0), sizes=(1000, 2000, 3000, 3000), skew=0.0, fair="all", cap=5.0),
    "W8": dict(_W, deltas=(2.0, 3.5, 6.0, 9.0), sizes=(250, 500, 750, 750), skew=0.0, fair="all", cap=1.0),
})
# X: KuCoin only (2026-10-05): deep levels, every fill closed on KuCoin itself as a taker shortly after (evaluated by mf8_eval.py)
CONFIGS.update({
    "X1": dict(_W, deltas=(4.5, 6.0, 7.5, 9.0, 12.0), sizes=(1000,) * 5, skew=0.0, fair="all"),
    "X2": dict(_W, deltas=(4.5, 6.0, 7.5, 9.0, 12.0), sizes=(1000,) * 5, skew=0.0),                       # Binance-only fair value
    "X3": dict(_W, deltas=(4.5, 6.0, 7.5, 9.0, 12.0), sizes=(1000,) * 5, skew=0.0, fair="all", tau_o=50.0, tau_c=50.0, tau_tab="50.0"),   # exchange congested
})
OTHER_DAY = {"20261001": "20261002", "20261002": "20261001"}
EVAL_NS = 5 * MS                       # v2: the activity state is looked at again at least this often


class Order:
    __slots__ = ("side", "level", "tick", "want", "left", "live_at", "ahead", "cancel_at", "born")

    def __init__(self, side, level, tick, size, live_at, born):
        self.side, self.level, self.tick, self.left = side, level, tick, size
        self.want = tick                                   # the price asked for (tick may be clamped inside the touch when it rests)
        self.live_at, self.ahead, self.cancel_at, self.born = live_at, None, None, born


def allocate(sweep, orders, now):
    """One taker order's real matches [(maker tick, size, maker order id)] in feed order (= priority order), maker side
    `sweep_side` already filtered by the caller. -> [(order, filled)] for our live orders on that side.
    Our order is ahead of a real match when its price is better, or equal with the real maker not among the orders that
    were at that price when ours arrived. The taker's volume is fixed: our fills come out of it first."""
    remaining = sum(s for _, s, _ in sweep)
    out = []
    mine = [o for o in orders if o.left > 0 and o.ahead is not None and (o.cancel_at is None or now < o.cancel_at)]
    if not mine:
        return out
    buy = mine[0].side == 0
    mine.sort(key=lambda o: (-o.tick if buy else o.tick, o.live_at))            # our own price / time priority
    k = 0
    for tick, size, maker in sweep:
        while k < len(mine) and remaining > 0:
            o = mine[k]
            better = (o.tick > tick) if buy else (o.tick < tick)
            if better or (o.tick == tick and maker not in o.ahead):
                f = min(o.left, remaining)
                out.append((o, f))
                remaining -= f
                k += 1
            else:
                break
        if remaining <= 0:
            break
        remaining -= min(size, remaining)
    return out


HOLDS_MS = (100, 200, 500, 1000, 2000, 5000)        # KuCoin-only exit: the position of each fill is closed as a taker this long after it


def take_vwap(levels, sizes, best, size, buy_side):
    """Average price (ticks) of taking `size` contracts from one side of the real book.
    levels: tick -> set(order ids) of that side; sizes: order id -> remaining contracts; best: best tick of that side;
    buy_side True = we hit the bids (walk down from the best bid). -> (average tick, contracts obtained)."""
    if best is None:
        return None, 0
    ticks = sorted((t for t in levels if (t <= best if buy_side else t >= best)), reverse=buy_side)
    got, cost = 0, 0.0
    for t in ticks:
        avail = sum(sizes.get(o, 0) for o in levels[t])
        if avail <= 0:
            continue
        x = min(avail, size - got)
        got += x
        cost += x * t
        if got >= size:
            break
    return (cost / got if got else None), got


def kucoin_basis(day, ft, fp, g):
    """Basis of the KuCoin mid over a fair-value series: median over the previous 300 s on the 1 s grid g, known before."""
    mz = np.load(os.path.join(M.MID, f"mid_{day}.npz"))
    at = lambda t, p, x: np.where(np.searchsorted(t, x, side="right") > 0, p[np.clip(np.searchsorted(t, x, side="right") - 1, 0, len(p) - 1)], np.nan)
    d = at(mz["t"], mz["m"], g) - at(ft, fp, g)
    out = np.full(len(g), np.nan)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out[300:] = np.nanmedian(np.lib.stride_tricks.sliding_window_view(d, 300), axis=1)[:-1]
    return out


def run(day, hh, name, pos0=0.0):
    cfg = CONFIGS[name]
    os.makedirs(OUT, exist_ok=True)
    z = np.load(os.path.join(M.OUT, f"fair_{day}.npz"))                         # Binance trades + basis, written by mf4_hedged_edge.Fair
    bt, bp = z["t"] + int(cfg["d_bn"] * MS), z["p"]                             # when we see each Binance trade (also drives the activity state)
    gi, basis = z["g"], z["basis"]
    ft, fp = bt, bp                                                             # the fair-value series
    if cfg.get("fair"):
        fz = np.load(os.path.join(M.OUT, f"fairmv_{cfg['fair']}_{day}.npz"))    # multi-venue filter; its times already include each venue's delay
        ft, fp = fz["t"], fz["m"]
        basis = kucoin_basis(day, ft, fp, gi)
    cap = cfg.get("cap")
    deltas, sizes = cfg["deltas"], cfg["sizes"]
    tau_o, tau_c = int(cfg["tau_o"] * MS), int(cfg["tau_c"] * MS)

    book = {}                              # orderId -> (side, tick)
    osize = {}                             # orderId -> remaining contracts (for the taker exit)
    exits = []                             # heap of (time, fill index, hold index, book side to hit, contracts)
    exit_px = {}                           # (fill index, hold index) -> (average tick obtained, best tick then, contracts obtained)
    at_tick = ({}, {})                     # side -> tick -> set(orderId)
    touch = M.Touch()
    slots = {(s, k): [] for s in (0, 1) for k in range(len(deltas))}            # live + cancelling orders of the slot
    pending = {}                           # (side, level) -> Order not yet resting
    fills = []                             # ts, side, level, tick, size, F (USD), age ms, sweep contracts
    stats = dict(placed=0, cancelled=0, rejected=0)
    pos = pos0                             # BTC, carried from the previous hour
    ib = ig = jf = 0
    F = None
    sweep, sweep_taker, sweep_side, sweep_ts = [], None, None, 0
    t_first = None
    dirty = True                           # something of ours changed: look at the quotes again
    jump, jwin, cool = cfg.get("jump"), int(cfg.get("jwin", 0) * MS), int(cfg.get("cool", 0) * MS)
    hist = collections.deque()             # (time, F) of the last jwin ms
    blocked = [0, 0]                       # side -> not re-posted before this time
    stats["pulls"] = 0
    stats["breaks"] = 0                   # stream breaks (lost messages / reconnects) after which the book was rebuilt from empty
    last_sn = None
    v2 = cfg.get("v2")
    if v2:
        fit = json.load(open(os.path.join(M.OUT, f"mf5_fit_{OTHER_DAY[day]}.json")))
        bz = np.load(os.path.join(M.OUT, f"binance_BTCUSDT_{day}.npz"))
        csq = np.r_[0.0, np.cumsum(bz["q"] * np.where(bz["bm"], -1.0, 1.0))]     # cumulative signed volume, same order as bt
        bk = np.array(fit["buckets"])
        buf_tab = np.array([fit["buffer"][str(b)][cfg["tau_tab"]] for b in fit["buckets"]]) * cfg["kbuf"]
        b_chg, b_sv, sv_cap = (fit["beta_chg50"], fit["beta_sv50"], fit["sv_cap"]) if cfg["drift"] else (0.0, 0.0, 1.0)
    i50 = i100 = 0
    next_eval = 0
    stats["level_time"] = [0] * len(deltas)

    def flush():
        nonlocal sweep, sweep_taker, pos, dirty
        if sweep:
            mine = [o for k in range(len(deltas)) for o in slots[(sweep_side, k)]]
            for o, f in allocate(sweep, mine, sweep_ts):
                o.left -= f
                dirty = True
                pos += (f if o.side == 0 else -f) * M.MULT
                fills.append((sweep_ts, o.side, o.level, o.tick, f, F or 0.0, (sweep_ts - o.live_at) / MS, sum(s for _, s, _ in sweep)))
                for hk, h in enumerate(HOLDS_MS):
                    heapq.heappush(exits, (sweep_ts + h * MS, len(fills) - 1, hk, o.side, f))
            sweep, sweep_taker = [], None

    def requote(now):
        if F is None or t_first is None or now < t_first + M.WARM_NS:
            return
        Fs = F * (1 - cfg["skew"] * pos / 1e4)
        hticks = cfg["h"] * F / 1e4 * 10
        buf = 0.0
        if v2:
            nonlocal i50, i100
            while i50 < ib and bt[i50] <= now - 50 * MS:
                i50 += 1
            while i100 < ib and bt[i100] <= now - 100 * MS:
                i100 += 1
            buf = buf_tab[np.searchsorted(bk, ib - i100, side="right") - 1]
            p_old = bp[i50 - 1] if i50 > 0 else bp[0]
            sv = min(max(csq[ib] - csq[i50], -sv_cap), sv_cap)
            Fs *= 1 + (b_chg * (bp[ib - 1] - p_old) / bp[ib - 1] * 1e4 + b_sv * sv) / 1e4
        if jump:
            hist.append((now, F))
            while hist[0][0] < now - jwin:
                hist.popleft()
            lo_f = min(x[1] for x in hist)
            hi_f = max(x[1] for x in hist)
            for s, moved_bp in ((1, (F - lo_f) / F * 1e4), (0, (hi_f - F) / F * 1e4)):     # a rise runs into our asks, a fall into our bids
                if moved_bp >= jump:
                    if blocked[s] <= now:
                        stats["pulls"] += 1
                    blocked[s] = now + cool
        for s in (0, 1):
            if cap and ((s == 0 and pos >= cap) or (s == 1 and pos <= -cap)):   # at the position cap only the reducing side is quoted
                blocked[s] = max(blocked[s], now + 1)
            if blocked[s] > now:
                for k in range(len(deltas)):
                    for o in slots[(s, k)]:
                        if o.cancel_at is None:
                            o.cancel_at = now + tau_c
                            stats["cancelled"] += 1
                continue
            for k, d in enumerate(deltas):
                if d < buf:                                   # this level does not cover the move Binance can make before our cancel: not quoted
                    for o in slots[(s, k)]:
                        if o.cancel_at is None:
                            o.cancel_at = now + tau_c
                            stats["cancelled"] += 1
                    continue
                want = int(np.floor(Fs * (1 - d / 1e4) * 10)) if s == 0 else int(np.ceil(Fs * (1 + d / 1e4) * 10))
                if (s, k) in pending:
                    continue
                cur = [o for o in slots[(s, k)] if o.cancel_at is None and o.left > 0]
                if cur and abs(cur[0].want - want) < hticks:
                    continue
                for o in cur:
                    o.cancel_at = now + tau_c
                    stats["cancelled"] += 1
                pending[(s, k)] = Order(s, k, want, sizes[k], now + tau_o, now)
                stats["placed"] += 1

    def advance(now):
        """Apply everything of ours that becomes effective up to `now`: new orders rest, cancelled orders leave."""
        nonlocal dirty
        for key in [k for k, o in pending.items() if o.live_at <= now]:
            dirty = True
            o = pending.pop(key)
            other = touch.best(1 - o.side)
            if other is not None and ((o.tick >= other) if o.side == 0 else (o.tick <= other)):
                stats["rejected"] += 1                                          # post-only would cross: rest one tick inside the touch instead
                o.tick = other - 1 if o.side == 0 else other + 1
            o.ahead = frozenset(at_tick[o.side].get(o.tick, ()))
            slots[key].append(o)
        for key, L in slots.items():
            if L:
                slots[key] = [o for o in L if o.left > 0 and (o.cancel_at is None or o.cancel_at > now)]

    f = os.path.join(M.SRC, day, f"{hh}_{M.SYM}_l3.jsonl.gz")
    try:
        with gzip.open(f, "rb") as fh:
            for line in fh:
                i = line.find(b"\t")
                if i <= 0:
                    continue
                j = line.find(b'"sn":', i, i + 120)
                broke = False
                if j > 0:
                    sn = int(line[j + 5:line.index(b",", j)])
                    broke = last_sn is not None and sn > last_sn + 2            # one missing number sits between a match and its done and is never published
                    last_sn = sn
                elif b'"_marker"' in line and b'"connect"' in line:
                    broke, last_sn = t_first is not None, None
                if b'"subject":"received"' in line and not broke:
                    continue
                m = orjson.loads(line[i + 1:])
                d, s = m.get("data"), m.get("subject")
                if broke:
                    # the stream lost messages: the rebuilt book is no longer the real one. Start again as at the top of a file:
                    # empty book, our orders dropped, no quoting until the warm-up has passed.
                    flush()
                    book.clear(), osize.clear(), at_tick[0].clear(), at_tick[1].clear(), pending.clear()
                    touch = M.Touch()
                    for key in slots:
                        slots[key] = []
                    t_first = None
                    stats["breaks"] += 1
                if not d or not s or s == "received":
                    continue
                ts = int(d["ts"])
                if t_first is None:
                    t_first = ts
                if s != "match" or d["takerOrderId"] != sweep_taker:
                    flush()
                # fair value: Binance trades and the basis second seen up to now
                moved = False
                while ib < len(bt) and bt[ib] <= ts:
                    ib += 1
                    moved = True
                while jf < len(ft) and ft[jf] <= ts:
                    jf += 1
                    moved = True
                while ig < len(gi) - 1 and gi[ig + 1] <= ts:
                    ig += 1
                    moved = True
                if moved and jf > 0 and ib > 0 and basis[ig] == basis[ig]:
                    F = fp[jf - 1] + basis[ig]
                if pending or dirty or moved:
                    advance(ts)
                if jump and not dirty and (0 < blocked[0] <= ts or 0 < blocked[1] <= ts):
                    dirty = True                                                # a pulled side may come back
                    blocked[0] = 0 if blocked[0] <= ts else blocked[0]
                    blocked[1] = 0 if blocked[1] <= ts else blocked[1]
                if v2 and ts >= next_eval:
                    dirty = True
                    next_eval = ts + EVAL_NS
                if moved or dirty:
                    dirty = False
                    requote(ts)
                while exits and exits[0][0] <= ts:
                    _, fi, hk, sd, sz = heapq.heappop(exits)
                    b = touch.best(sd)
                    exit_px[(fi, hk)] = (*take_vwap(at_tick[sd], osize, b, sz, sd == 0), b)
                if s == "open":
                    side = 0 if d["side"] == "buy" else 1
                    tick = round(float(d["price"]) * 10)
                    touch.clear_through(side, tick)
                    book[d["orderId"]] = (side, tick)
                    osize[d["orderId"]] = int(d["size"])
                    at_tick[side].setdefault(tick, set()).add(d["orderId"])
                    touch.add(side, tick)
                elif s == "match":
                    o = book.get(d["makerOrderId"])
                    if o is not None:
                        if sweep_taker is None:
                            sweep_taker, sweep_side, sweep_ts = d["takerOrderId"], o[0], ts
                        if o[0] == sweep_side:
                            sweep.append((o[1], int(d["size"]), d["makerOrderId"]))
                        osize[d["makerOrderId"]] = int(d["remainSize"])
                        if d["remainSize"] == "0":
                            osize.pop(d["makerOrderId"], None)
                            book.pop(d["makerOrderId"], None)
                            touch.remove(o[0], o[1])
                            at_tick[o[0]].get(o[1], set()).discard(d["makerOrderId"])
                elif s == "update":
                    if d.get("orderId") in osize and d.get("size") is not None:
                        osize[d["orderId"]] = int(float(d["size"]))
                elif s == "done":
                    o = book.pop(d["orderId"], None)
                    osize.pop(d["orderId"], None)
                    if o is not None:
                        touch.remove(o[0], o[1])
                        st = at_tick[o[0]].get(o[1])
                        if st is not None:
                            st.discard(d["orderId"])
                            if not st:
                                del at_tick[o[0]][o[1]]
        flush()
    except (EOFError, OSError, zlib.error) as e:
        print("damaged tail:", type(e).__name__, flush=True)
    A = np.array(fills, np.float64).reshape(-1, 8)
    EX = np.full((len(fills), len(HOLDS_MS), 3), np.nan)       # average exit tick, contracts obtained, best tick at the exit
    for (fi, hk), (vw, got, b) in exit_px.items():
        EX[fi, hk] = (np.nan if vw is None else vw, got, np.nan if b is None else b)
    np.savez_compressed(os.path.join(OUT, f"fills_{name}_{day}_{hh}.npz"), fills=A, ts=np.array([x[0] for x in fills], np.int64), exits=EX)
    json.dump(dict(stats, cfg=cfg, day=day, hh=hh, pos_end=pos), open(os.path.join(OUT, f"stats_{name}_{day}_{hh}.json"), "w"))
    print(f"{day} {hh} {name}: fills {len(A)}, contracts {A[:, 4].sum() if len(A) else 0:.0f}, placed {stats['placed']:,}, rejected {stats['rejected']:,}, position end {pos:+.2f} BTC", flush=True)
    return pos


def chain(name):
    """All recorded hours of both days in order, the position carried from hour to hour (needed for the position cap)."""
    import glob
    pos = 0.0
    for day in ("20261001", "20261002"):
        for f in sorted(glob.glob(os.path.join(M.SRC, day, f"??_{M.SYM}_l3.jsonl.gz"))):
            pos = run(day, os.path.basename(f)[:2], name, pos)
    print("CHAIN_DONE", name, flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "chain":
        chain(sys.argv[2])
    else:
        run(sys.argv[1], sys.argv[2], sys.argv[3])
