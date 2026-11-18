"""research3: behaviour check of a strategy version on the recorded live feed of 2026-10-02 (no matching, no fills).
Feeds the public BTC-USDC top-5 book, the BTC-USDT touch and the BTC-USDC prints of the first live run
(data/research3/live_20261002/run1_extract.jsonl.gz; our own run-1 orders are removed from the book) to the strategy.
Orders rest from the next event; a cancel is confirmed LAT_MS later; a post-only order that would cross is rejected.
Reports what the strategy does, not what it earns: regime, how often level 1 is at the touch, messages against the rate limit.
usage: .venv/Scripts/python.exe -X utf8 scripts/research3/uh_v9_dryrun.py <strategy.py> [touch_mode=1]"""
import gzip, json, os, sys
from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from core.enums import OrderStatus, Side          # noqa: E402
from tests.research5 import uh_harness as H       # noqa: E402

mod = H.load(sys.argv[1], "dry")
touch_mode = int(sys.argv[2]) if len(sys.argv) > 2 else 1
QS, HS, LAT = "BTC-USDC", "BTC-USDT", 5_000_000
rows = [json.loads(l) for l in gzip.open(os.path.join(ROOT, "data", "research3", "live_20261002", "run1_extract.jsonl.gz"), "rt", encoding="utf-8")]

# our run-1 orders, to take them out of the recorded book
new, rep = {}, defaultdict(list)
for r in rows:
    if r[0] == "N" and r[3] == QS:
        new[r[2]] = (r[4], r[5], r[6])
    elif r[0] == "R":
        rep[r[3]].append((r[1], r[2], r[5]))
ev = []
for oid, o in new.items():
    push = [x for x in rep.get(oid, []) if abs(x[0] - x[1]) >= 200_000 and x[1] > 10 ** 18]
    opens = [x[0] for x in push if x[2] in ("submitted", "partially_filled")]
    ends = [x[0] for x in push if x[2] in ("cancelled", "filled")]
    if opens or ends:
        ev.append((min(opens) if opens else min(ends), 1, oid))
        if ends:
            ev.append((min(ends), -1, oid))
ev.sort()

ctx = H.Ctx()
s = mod.MmUsdcHedge(ctx)
P = {"clip_usd": 750, "l1_clips": 0.5, "l2_clips": 2.5, "l2_bp": 6.0, "max_order_usd": 2450, "fl_c_m0": 0.523, "fl_c_n0": 0.0438,
     "sk_gamma": 0.03220157063614489, "sk_sb_m0": 0.3217536590811478, "sk_sb_n0": 56.80308159362998, "sk_sqrtB": 1.613033638637577}
if "touch_mode" in mod.DEFAULTS:
    P["touch_mode"] = touch_mode
s.params = P
s.on_start()
lv = lambda p, q: NS(price=Decimal(str(p)), size=Decimal(str(q)))
live, j = {}, 0
pending_cancel = {}                 # oid -> time the cancel takes effect
w, rejects = [], 0
pub = None
near_state = defaultdict(int)       # per USDC book update: where level 1 stands
t_first = t_last = None
n_log = 0
for r in rows:
    t = r[1]
    while j < len(ev) and ev[j][0] <= t:
        if ev[j][1] > 0:
            live[ev[j][2]] = new[ev[j][2]]
        else:
            live.pop(ev[j][2], None)
        j += 1
    # answer what the strategy sent before this event
    for oid in list(ctx.open):
        o = ctx.open[oid]
        if o["new"]:
            o["new"] = False
            if o["sym"] == QS and pub is not None and o["px"] is not None and (
                    (o["side"] == "buy" and float(o["px"]) >= pub[1]) or (o["side"] == "sell" and float(o["px"]) <= pub[0])):
                del ctx.open[oid]
                rejects += 1
                s.on_order_report(NS(status=OrderStatus.REJECTED, order_id=oid, ts_ns=t))
                continue
        if o["cancel"]:
            pending_cancel.setdefault(oid, t + LAT)
            if t >= pending_cancel[oid]:
                del ctx.open[oid]
                pending_cancel.pop(oid, None)
                s.on_order_report(NS(status=OrderStatus.CANCELLED, order_id=oid, ts_ns=t))
    if r[0] == "D" and r[3] == HS:
        s.on_depth(NS(symbol=HS, ts_ns=t, bids=[lv(*r[4][0])], asks=[lv(*r[5][0])]))
    elif r[0] == "D" and r[3] == QS:
        own_b, own_a = defaultdict(float), defaultdict(float)
        for side, px, qty in live.values():
            (own_b if side == "buy" else own_a)[px] += qty
        bids = [(p, q - own_b.get(p, 0.0)) for p, q in r[4] if q - own_b.get(p, 0.0) > 1e-9]
        asks = [(p, q - own_a.get(p, 0.0)) for p, q in r[5] if q - own_a.get(p, 0.0) > 1e-9]
        if not bids or not asks or asks[0][0] <= bids[0][0]:
            continue
        pub = (bids[0][0], asks[0][0])
        s.on_depth(NS(symbol=QS, ts_ns=t, bids=[lv(p, q) for p, q in bids], asks=[lv(p, q) for p, q in asks]))
        if s.t0 and t - s.t0 > 90_000_000_000:
            t_first = t_first or t
            t_last = t
            for side, touch, sign in (("bid", pub[0], 1), ("ask", pub[1], -1)):
                q = s.slot[side]
                if q is None or q["cancelling"]:
                    near_state[side, "none"] += 1
                else:
                    d = sign * (q["px"] - touch)
                    near_state[side, "in front" if d > 0.05 else "joined" if d > -0.05 else "behind"] += 1
    elif r[0] == "T" and r[3] == QS:
        s.on_tick(NS(symbol=QS, ts_ns=r[2], side=Side.BUY if r[4] == "buy" else Side.SELL, price=Decimal(str(r[5])), size=Decimal(str(r[6]))))
    else:
        continue
    for a in ctx.log[n_log:]:
        w.append((t, 2 if a[0] == "order" else 1))
    n_log = len(ctx.log)

hours = (t_last - t_first) / 3.6e12
best = cur = k = 0
for t, x in w:
    cur += x
    while w[k][0] < t - 30_000_000_000:
        cur -= w[k][1]
        k += 1
    best = max(best, cur)
orders = [a for a in ctx.log if a[0] == "order"]
print("%s touch_mode=%s: %.2f h of recorded feed" % (os.path.basename(sys.argv[1]), P.get("touch_mode", "-"), hours))
print("  regime %s, switches %s, stats %s" % (s.__dict__.get("regime", "-"), s.stats.get("regime_switches", "-"), {k: v for k, v in s.stats.items() if v}))
print("  orders %d (%.0f / h), cancels %d, post-only rejections %d | largest rate-limit weight in 30 s: %d (our share %.0f, exchange limit %.0f)" % (
    len(orders), len(orders) / hours, sum(1 for a in ctx.log if a[0] == "cancel"), rejects, best, s.f["msg_limit_w30"] * s.f["msg_share"], s.f["msg_limit_w30"]))
for side in ("bid", "ask"):
    n = sum(v for (sd, _), v in near_state.items() if sd == side)
    print("  level-1 %s versus the public touch: " % side + "  ".join("%s %.1f%%" % (k, 100 * near_state[side, k] / n) for k in ("in front", "joined", "behind", "none")))
print("  largest order $%.0f" % max(float(a[4]) * 85000 for a in orders))
