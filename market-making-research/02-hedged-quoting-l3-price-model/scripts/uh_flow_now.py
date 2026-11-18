"""research3: hour-by-hour flow on a KuCoin USDC contract from our own public recording (data/research5/usdc_pairs, read-only).
What the USDC-maker / USDT-hedge strategy needs is real taker orders that reach d bp beyond fair value. Per UTC hour:
  spread        median public spread of the USDC contract
  paired        prints where the maker order was at most 20 ms old when the taker arrived (a participant trading with itself;
                rule of scripts/research5/kucoin_trades.py) - not flow a resting quote can take
  real          the other taker orders; depth = how far beyond fair value the order's worst price was, in bp,
                fair = USDT mid x (1 + median basis of the last 60 s, 1 s samples)
  reach d       real orders with depth >= d (a quote resting d bp from fair would have been hit)
  edge 5 s      maker's edge on real orders at their worst price, measured against fair value 5 s later
Exchange timestamps are used throughout (the recording PC's clock is off). No cache is written.
usage: Python314/python.exe scripts/research3/uh_flow_now.py <day> [coin=BTC]"""
import glob, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research4"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research5"))
import stale_take_replay as S   # noqa: E402  (read-only helpers)
import kucoin_trades as KT      # noqa: E402
import l3_parse as LP           # noqa: E402
import active_mm_study as AM    # noqa: E402  (parse helpers only; its cache is not used)

SRC = os.path.join(ROOT, "data", "research5", "usdc_pairs")
PAIRS = {"BTC": ("XBTUSDCM", "XBTUSDTM", 0.0001), "ETH": ("ETHUSDCM", "ETHUSDTM", 0.01), "SOL": ("SOLUSDCM", "SOLUSDTM", 0.1),
         "XRP": ("XRPUSDCM", "XRPUSDTM", 10.0), "SUI": ("SUIUSDCM", "SUIUSDTM", 1.0)}
day = sys.argv[1]; coin = sys.argv[2] if len(sys.argv) > 2 else "BTC"
uc, ut, mult = PAIRS[coin]


def bbo(sym):
    files = AM.hour_files(day, sym, "l2", SRC)
    snaps = []
    for f in AM.hour_files(day, sym, "snap", SRC):
        for m in AM.json_lines(f):
            d = m.get("data")
            if d and d.get("bids") and d.get("asks"):
                snaps.append((int(d["sequence"]), d["bids"], d["asks"]))
    return S.bbo_from_events(sorted(snaps, key=lambda x: x[0]), AM.l2_events(files), LP.Book())


Q, H = bbo(uc), bbo(ut)
qt, ht = Q.t.to_numpy(np.int64), H.t.to_numpy(np.int64)
qmid = ((Q.bb + Q.ba) / 2).to_numpy(); hmid = ((H.bb + H.ba) / 2).to_numpy()
qsp = ((Q.ba - Q.bb) / qmid * 1e4).to_numpy()
at = lambda ts, v, x: v[np.clip(np.searchsorted(ts, x, side="right") - 1, 0, len(ts) - 1)]
g = np.arange(max(qt[0], ht[0]) // 1000 * 1000 + 1000, min(qt[-1], ht[-1]), 1000, dtype=np.int64)       # 1 s grid, ms
basis = pd.Series(at(qt, qmid, g) / at(ht, hmid, g) - 1.0).rolling(60, min_periods=30).median().to_numpy()

rows = [r for f in AM.hour_files(day, uc, "trades", SRC) for r in map(KT.parse_line, AM.gz_lines(f)) if r]
prints = pd.DataFrame(rows, columns=["sym", "ts", "sgn", "px", "size", "tid", "age_ms", "liq"])
o = KT.to_orders(prints, {uc: mult})
o["t"] = o.ts // 1_000_000
o = o[(o.t > g[0] + 60_000) & (o.t < g[-1] - 30_000)].copy()
k = np.clip(np.searchsorted(g, o.t.to_numpy(), side="right") - 1, 0, len(g) - 1)
b = basis[k]
F0 = at(ht, hmid, o.t.to_numpy()) * (1 + b)
F5 = at(ht, hmid, o.t.to_numpy() + 5000) * (1 + b)
o["depth"] = o.sgn * (o.px_last - F0) / F0 * 1e4             # taker buy above fair / taker sell below fair
o["edge5"] = o.sgn * (o.px_last - F5) / F5 * 1e4
o["hour"] = (o.t // 3_600_000) % 24
o = o[np.isfinite(o.depth)]
sp_h = pd.Series(at(qt, qsp, g), index=(g // 3_600_000) % 24).groupby(level=0).median()

print(f"{coin}-USDC {day}: hour | spread bp | paired n $ | real n $ | real depth median bp | reach >=0.25 / >=1 / >=2 bp: n ($) | edge 5 s on reach>=1")
tot = []
for h, d in o.groupby("hour"):
    real, pair = d[~d.pair], d[d.pair]
    r1 = real[real.depth >= 1.0]
    tot.append((len(pair), pair.usd.sum(), len(real), real.usd.sum(), (real.depth >= 0.25).sum(), (real.depth >= 1).sum(), (real.depth >= 2).sum(),
                real[real.depth >= 2].usd.sum()))
    print("  %02d | %5.2f | %5d %8.0f | %4d %7.0f | %+6.2f | %3d ($%6.0f) / %3d ($%6.0f) / %3d ($%6.0f) | %s" % (
        h, sp_h.get(h, float("nan")), len(pair), pair.usd.sum(), len(real), real.usd.sum(), real.depth.median() if len(real) else float("nan"),
        (real.depth >= 0.25).sum(), real[real.depth >= 0.25].usd.sum(), len(r1), r1.usd.sum(), (real.depth >= 2).sum(), real[real.depth >= 2].usd.sum(),
        "%+.2f" % np.average(r1.edge5, weights=r1.usd) if len(r1) >= 3 else "-"))
T = np.array(tot, dtype=float); n = len(tot)
print("per hour over %d hours: paired %.0f ($%.0f) | real %.0f ($%.0f) | reach >=0.25: %.1f, >=1: %.1f, >=2: %.1f ($%.0f)" % (
    n, T[:, 0].mean(), T[:, 1].mean(), T[:, 2].mean(), T[:, 3].mean(), T[:, 4].mean(), T[:, 5].mean(), T[:, 6].mean(), T[:, 7].mean()))
real = o[~o.pair]
for d in (0.25, 1.0, 2.0):
    s = real[real.depth >= d]
    if len(s) >= 5:
        print("real orders reaching >= %.2f bp: n %d, $%.0f, mean depth %+.2f, edge after 5 s %+.2f bp (size-weighted)" % (
            d, len(s), s.usd.sum(), np.average(s.depth, weights=s.usd), np.average(s.edge5, weights=s.usd)))
