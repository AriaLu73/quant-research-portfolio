"""research3: what each live hedge cost on 2026-10-02 (own recording of BTC-USDT, exchange time).
cost = how much worse the hedge price was than the BTC-USDT mid at the moment the quote was filled, in bp (the strategy's own
definition of the cost of disposing a fill), before the OUR_FEE maker rebate. usage: uh_live_hedge_cost.py"""
import sys, io, contextlib, runpy, datetime as dt
import numpy as np
sys.argv = ["x", "20261002", "BTC"]
with contextlib.redirect_stdout(io.StringIO()):
    ns = runpy.run_path(__file__.replace("uh_live_hedge_cost.py", "uh_flow_now.py"))
ht, hmid, at = ns["ht"], ns["hmid"], ns["at"]
# (quote fill time, hedge side, hedge fill time, hedge price, hedge qty, version)
H = [("16:43:02.613", "buy", "16:43:04.713", 85112.0, 0.004, "v7"), ("17:11:23.953", "sell", "17:11:30.774", 85000.3, 0.001, "v7"),
     ("17:24:51.600", "buy", "17:24:51.816", 84714.7, 0.021, "v7"), ("19:11:07.180", "sell", "19:11:14.237", 84073.9, 0.004, "v7"),
     ("19:32:13.940", "sell", "19:32:16.150", 84088.9, 0.004, "v7"), ("19:36:36.270", "buy", "19:36:37.276", 84195.8, 0.003, "v7"),
     ("20:56:38.500", "sell", "20:57:21.085", 84337.0, 0.003, "v9"), ("20:59:17.400", "buy", "20:59:27.487", 84463.1, 0.008, "v9")]
def ms(hms):
    h, m, s = hms.split(":")
    return int(dt.datetime(2026, 10, 2, int(h), int(m), int(float(s)), int(round(float(s) % 1 * 1e6)), tzinfo=dt.timezone.utc).timestamp() * 1000)
tot_usd = tot_cost = 0.0
print("quote fill    hedge        wait s   mid at the quote fill   hedge price   cost bp (+ = worse than mid)   $")
for t0, side, t1, px, qty, ver in H:
    m0 = at(ht, hmid, ms(t0))
    sgn = 1 if side == "buy" else -1
    c = sgn * (px - m0) / m0 * 1e4
    usd = px * qty
    tot_usd += usd; tot_cost += c * usd / 1e4
    print("%s  %-4s %.3f  %6.1f   %10.1f              %9.1f     %+6.2f                        %+.3f   %s" % (t0, side, qty, (ms(t1) - ms(t0)) / 1000, m0, px, c, c * usd / 1e4, ver))
print("all 8 hedges: $%.0f hedged, cost $%.2f = %.2f bp of the hedged amount; after the OUR_FEE rebate %.2f bp" % (tot_usd, tot_cost, tot_cost / tot_usd * 1e4, tot_cost / tot_usd * 1e4 - 0.7))
costs = [(1 if s == "buy" else -1) * (p - at(ht, hmid, ms(a))) / at(ht, hmid, ms(a)) * 1e4 for a, s, b, p, q, v in H]
print("per hedge: median %.2f bp, mean %.2f bp, worse than mid in %d of %d" % (float(np.median(costs)), float(np.mean(costs)), sum(c > 0 for c in costs), len(costs)))
