"""research3: what the reference (BTC-USDT mid) did around each live quote fill of 2026-10-02 (own recording, exchange time).
usage: uh_live_fill_markout.py"""
import sys, io, contextlib, runpy, datetime as dt
import numpy as np
sys.argv = ["x", "20261002", "BTC"]
with contextlib.redirect_stdout(io.StringIO()):
    ns = runpy.run_path(__file__.replace("uh_live_fill_markout.py", "uh_flow_now.py"))
ht, hmid, qt, qmid, at, g, basis = ns["ht"], ns["hmid"], ns["qt"], ns["qmid"], ns["at"], ns["g"], ns["basis"]
FILLS = [("16:43:02.613", "sell", 85117.5, 0.0044, "near"), ("17:11:23.953", "buy", 85102.0, 0.0022, "near"), ("17:24:51.600", "sell", 84754.8, 0.0221, "far (cancel refused)"),
         ("19:11:07.180", "buy", 84121.1, 0.0044, "near"), ("19:32:13.940", "buy", 84154.0, 0.0044, "near"), ("19:36:36.270", "sell", 84229.5, 0.0044, "near")]
print("fill                         level                 depth vs fair bp | USDT mid move in our favour after 1 s / 5 s / 30 s / 60 s bp | before the fill 0.1 s / 1 s")
tot = 0.0
for hms, side, px, qty, lvl in FILLS:
    h, m, s = hms.split(":")
    t = int(dt.datetime(2026, 10, 2, int(h), int(m), int(float(s)), int(float(s) % 1 * 1e6), tzinfo=dt.timezone.utc).timestamp() * 1000)
    sgn = 1 if side == "buy" else -1
    m0 = at(ht, hmid, t)
    b = basis[np.clip(np.searchsorted(g, t, side="right") - 1, 0, len(g) - 1)]
    depth = sgn * (m0 * (1 + b) - px) / px * 1e4                      # > 0: we were filled beyond fair value (good price)
    after = [sgn * (at(ht, hmid, t + int(x * 1000)) / m0 - 1) * 1e4 for x in (1, 5, 30, 60)]
    before = [sgn * (m0 / at(ht, hmid, t - int(x * 1000)) - 1) * 1e4 for x in (0.1, 1)]
    e5 = depth + after[1]
    tot += e5 * px * qty / 1e4
    print("%s %-4s %.4f @ %.1f  %-21s %+6.2f           | %+6.2f %+6.2f %+6.2f %+6.2f                              | %+6.2f %+6.2f" % (
        hms, side, qty, px, lvl, depth, *after, *before))
print("edge against fair value 5 s after the fill, all six: $%.3f (before rebates and hedge costs)" % tot)
