#!/usr/bin/env python3
"""research3 QMM-2: collect traces for the development day and the check day, one after the other (detached)."""
import os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
for day in sys.argv[1:]:
    print("START", day, flush=True)
    subprocess.run([sys.executable, "-X", "utf8", "scripts/research3/qmm_trace.py", day, "all", "2"], check=False)
print("CHAIN DONE", flush=True)
