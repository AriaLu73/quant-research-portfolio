#!/usr/bin/env python3
"""research3: v9 (book-regime switch, touch regime for level 1) against v7 on the NARROW hours of the purchased data.
Written before any result was seen (2026-10-02, user: "用9月的窄时段跑一下v9"):
  hours     every purchased BTC-USDC hour (data/oos/ku_buyc, 20 days x 24 h) whose median public spread is <= 1.0 bp
            (data/research3/uh_val/spread_hours_BTC-USDC.csv, scripts/research3/uh_spread_scan.py); if there are more than
            48, the 48 narrowest (machine time). The live book of 2026-10-02 has a median spread of 0.3-OUR_FEE.
  runs      same engine, data and parameters (S15 full size: near $7,500, far $37,500) for both versions; the only
            difference is touch_mode (v9: 1). Engine latency 1.8 ms (the setting of every earlier run), queue-front matching.
            Hour by hour, v9 then v7, so that a partial result is already a like-for-like comparison.
  reading   v9 "does better than v7 in narrow books" if, over these hours, its total net is above zero and above v7's.
            Reported with it: quote fills and volume, level-1 touch posts, regime switches, hedge orders at market.
  caveats   the backtest fills a resting order as if it were first in its queue and fills the passive hedge the same way:
            exactly the two things the touch regime depends on. A good result here is necessary, not sufficient.
Start: .venv/Scripts/python.exe scripts/detach.py --log logs/r3_v9_narrow.log -- .venv/Scripts/python.exe -X utf8 scripts/research3/uh_v9_narrow_chain.py"""
import csv, datetime as dt, json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
rows = list(csv.DictReader(open("data/research3/uh_val/spread_hours_BTC-USDC.csv", encoding="utf-8")))
narrow = sorted((r for r in rows if float(r["median_spread_bp"]) <= 1.0), key=lambda r: float(r["median_spread_bp"]))[:48]
narrow.sort(key=lambda r: r["hour"])
jobs = []
for r in narrow:
    d, h = r["hour"].split("_")
    t0 = dt.datetime.strptime(d + h, "%Y%m%d%H")
    jobs.append(["ku_buyc/" + r["hour"], "BTC-USDC", t0.strftime("%Y-%m-%dT%H:00:00"), (t0 + dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:00:00")])
M = "data/research3/uh_val/btcusdc_narrow_hours.json"
json.dump(jobs, open(M, "w", encoding="utf-8"))
print("narrow hours:", len(jobs), "of", len(rows), flush=True)
RUNS = (("R3V9N_S15", "strategies/research3/versions/mm_uh_fv2_v9.py", "data/research3/uh_val/params_v9_S15_bt.json"),
        ("R3V7N_S15", "strategies/research3/versions/mm_uh_fv2_v7.py", "data/research3/uh_val/params_v7_S15_bt.json"))
for feed, *_ in jobs:
    for tag, strat, params in RUNS:
        subprocess.run([sys.executable, "-X", "utf8", "scripts/research5/run_hours.py", "--tag", tag, "--strategy", strat, "--params", params,
                        "--manifest", M, "--only", feed, "--capital", "5000000"], check=False)
print("CHAIN DONE", flush=True)
