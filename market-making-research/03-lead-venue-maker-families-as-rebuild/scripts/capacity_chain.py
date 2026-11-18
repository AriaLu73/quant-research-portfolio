#!/usr/bin/env python3
"""research5 UH-C1: capacity of the USDC-maker / USDT-hedge strategy - the same frozen rules at growing clip sizes.

User 2026-10-01: "never mind how much capital goes in, measure the maximum capacity". One run_hours.py job per
(contract, clip), one after another (each job waits for the machine budget itself), on the September training hours,
colo matching and latency (fixed inside run_hours.py). Simulated account 5,000,000 so that the risk layer's
"20 % of equity per contract" rule does not cap the test; the 50,000 per-order limit stays, so clip <= 25,000
(level 2 is two clips).
Usage: python scripts/detach.py --log logs/r5_capacity_chain.log -- .venv/Scripts/python.exe scripts/research5/capacity_chain.py
"""
import json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STRAT = os.path.join("strategies", "research5", "versions", "mm_uh_s2j.py")
CAPITAL = OUR_CAPITAL
JOBS = [("BTC", 20000), ("BTC", 25000), ("XRP", 20000), ("XRP", 2500)]
MANIFEST = {"BTC": "data/research2/btcusdc_sep_train32.json", "XRP": "data/research5/xrpusdc_sep_train32.json"}


def main():
    for coin, clip in JOBS:
        base = json.load(open(os.path.join(ROOT, "data", "research5", "params_UH_XRP_s1.json"), encoding="utf-8")) if coin == "XRP" else {}
        params = dict(base, clip_usd=clip)
        pp = os.path.join("data", "research5", f"params_cap_{coin}_{clip}.json")
        json.dump(params, open(os.path.join(ROOT, pp), "w", encoding="utf-8"), indent=1)
        tag = f"CAP_{coin}_{clip}"
        subprocess.run([sys.executable, os.path.join("scripts", "research5", "run_hours.py"), "--tag", tag, "--strategy", STRAT, "--params", pp,
                        "--manifest", MANIFEST[coin], "--capital", str(CAPITAL)], cwd=ROOT, check=False)
        print("JOBDONE", tag, time.strftime("%F %T"), flush=True)
    print("CHAINDONE", flush=True)


if __name__ == "__main__":
    main()
