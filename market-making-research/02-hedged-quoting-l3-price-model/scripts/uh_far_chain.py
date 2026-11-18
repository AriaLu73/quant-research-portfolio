#!/usr/bin/env python3
"""research3 H-FAR (2026-10-02): far level only versus both levels, September training hours, engine latency 25 ms.
One process at a time (RAM budget). Start through scripts/detach.py:
  .venv/Scripts/python.exe scripts/detach.py --log logs/r3_FAR_chain.log -- .venv/Scripts/python.exe -X utf8 scripts/research3/uh_far_chain.py"""
import os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
M = "data/research3/uh_val/btcusdc_sep_train32_c.json"
S = "strategies/research3/versions/mm_uh_fv2_v7.py"
for tag, params in (("R3FARLAT25_train32", "data/research3/uh_val/params_v7_S15_faronly_bt.json"),
                    ("R3LAT25_S15_train32", "data/research3/uh_val/params_v7_S15_bt.json")):
    print("START", tag, flush=True)
    subprocess.run([sys.executable, "-X", "utf8", "scripts/research3/run_hours_latency.py", "25", "--tag", tag, "--strategy", S,
                    "--params", params, "--manifest", M, "--capital", "5000000"], check=False)
print("CHAIN DONE", flush=True)
