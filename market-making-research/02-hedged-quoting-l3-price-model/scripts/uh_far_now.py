"""research3: what a far quote would have earned on our own recording (rough bound, not a backtest).
A quote resting d bp from fair value with size S is hit by every real (non-paired) taker order whose worst price is at least
d bp beyond fair; it is filled for min(order $, S) at d bp; the fair value then moves against it by (depth - edge5) bp within
5 s (measured); income = d - adverse move + 1.2 (USDC rebate) + 0.7 (USDT rebate, passive hedge). One fill per order,
queue front, no pick-off losses, no inventory limits: an upper bound on the benign side only.
usage: uh_far_now.py <day> [coin=BTC]"""
import sys, runpy, io, contextlib
import numpy as np
sys.argv = [sys.argv[0]] + sys.argv[1:]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    ns = runpy.run_path(__file__.replace("uh_far_now.py", "uh_flow_now.py"))
o = ns["o"]; real = o[~o.pair]
hours = real.hour.nunique() if len(real) else 1
print("%s %s: %d hours, real taker orders %d ($%.0f)" % (sys.argv[2] if len(sys.argv) > 2 else "BTC", sys.argv[1], o.hour.nunique(), len(real), real.usd.sum()))
for d, S in ((2.5, 7500), (4.0, 37500), (6.0, 37500), (10.0, 37500)):
    s = real[real.depth >= d]
    if not len(s):
        print("  quote at %4.1f bp, $%d: no order reached it" % (d, S)); continue
    fill = np.minimum(s.usd.to_numpy(), S)
    adverse = np.maximum(0.0, (s.depth - s.edge5).to_numpy())
    inc = fill * (d - adverse + 1.9) / 1e4
    print("  quote at %4.1f bp, $%-6d: hit %3d times (%.1f / hour), filled $%-8.0f, income $%7.2f (%.2f / hour); adverse move after 5 s: median %.1f bp; share of income from the best 3 hits %.0f%%" % (
        d, S, len(s), len(s) / o.hour.nunique(), fill.sum(), inc.sum(), inc.sum() / o.hour.nunique(), np.median(adverse),
        100 * np.sort(inc)[-3:].sum() / inc.sum() if inc.sum() > 0 else 0))
