#!/usr/bin/env python3
"""等上一段(日志里出现"结论"或"没有可检验")结束后,依次对给定日期跑 hw_sep_oos(抽帧 + 回放)。用法:python hw_chain.py <等待的日志> <日1,日2,...>"""
import os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
wait_log, days = sys.argv[1], sys.argv[2].split(",")
marks = sys.argv[3].split("|") if len(sys.argv) > 3 else ["结论", "没有可检验", "Traceback"]
while True:
    txt = open(wait_log, encoding="utf-8", errors="ignore").read()
    if any(m in txt for m in marks):
        break
    time.sleep(20)
for d in days:
    print("== chain start", d, flush=True)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "research3", "hw_sep_oos.py"), "--days", d, "--workers", "4"], cwd=ROOT, check=False)
print("CHAIN DONE", flush=True)
