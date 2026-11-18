"""research3: the pick-off loss table R(d) of scripts/research5/uh2b_prep.py for other reaction times (same method, same
September training days, same input files; only tau changes). Why: the table in the strategy assumes our cancel takes effect
1.8 ms after a reference move; on 2026-10-02 we measured, live, exchange push delay p50 1.4 / p90 5.6 ms, our pipeline
p50 0.2 / p90 1.0 ms, cancel request -> cancelled at the exchange p50 3.9 / p90 18.9 ms (docs/research3, memory
live-burst-latency-backlog). Output: data/research3/uh_val/pick_BTC_B_tau<us>.json (same fields as the research5 file).
usage: Python314/python.exe scripts/research3/uh_pick_tau.py BTC_B 1800 6000 26000 50000"""
import json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research5"))
import uh2b_prep as U

sym = sys.argv[1]; taus = [int(x) for x in sys.argv[2:]]
OUT = os.path.join(ROOT, "data", "research3", "uh_val")
tabs = {t: [] for t in taus}; sig = []
for d in U.DAYS:
    b = pd.read_parquet(os.path.join(U.EV, f"book_{sym}_{d}.parquet"), columns=["ts", "bb", "ba"])
    ok = ((b.bb > 0) & (b.ba > b.bb)).to_numpy()
    ts = b.ts.to_numpy().astype(np.int64)[ok]
    mid = ((b.bb.to_numpy() + b.ba.to_numpy()) / 2.0)[ok]
    ch = np.r_[True, np.diff(mid) != 0]
    t, m = ts[ch], mid[ch]
    secs = (ts[-1] - ts[0]) / 1e6
    for tau in taus:
        dn, up = U.loss_increments(t, m, tau, U.GRID)
        tabs[tau].append((dn + up) / 2 / secs)
    g = np.arange(ts[0], ts[-1], 1_000_000)
    a = mid[np.clip(np.searchsorted(ts, g, side="right") - 1, 0, len(mid) - 1)]
    sig.append(float(np.abs(np.diff(np.log(a))).mean() * 1e4 * np.sqrt(np.pi / 2)))
    print(d, "done", flush=True)
print("R(d) bp/s at d = 0, 0.5, 1, 2, 3, 4, 6, 8 bp:")
for tau in taus:
    r = np.mean(tabs[tau], axis=0)
    json.dump(dict(sym=sym, tau_s=tau / 1e6, days=U.DAYS, step_bp=0.05, sigma_ref=float(np.mean(sig)), loss_rate=r.tolist()),
              open(os.path.join(OUT, f"pick_{sym}_tau{tau}.json"), "w"), indent=1)
    print("  tau %6.1f ms: " % (tau / 1e3) + "  ".join("%.3g" % r[i] for i in (0, 10, 20, 40, 60, 80, 120, 160)))
