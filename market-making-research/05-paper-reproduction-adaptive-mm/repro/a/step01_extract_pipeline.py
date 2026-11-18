"""Step 1 提取批跑:10 月 L3(sim_l3/l3_extract.py)与 9 月 L2(a/l2_extract.py)按 (合约, 日, 小时) 并行;已有产物跳过。
final_test 锁:L3 只提取起点 < validation_test 切点的小时(config/train_days.yaml cuts_utc)。
用法  python step01_extract_pipeline.py <sym>[,<sym>] [l3|l2|both] [par]
"""
import datetime as dt
import os
import subprocess
import sys
import time

import yaml

REPRO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = r""
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
FLAGS = 0x08000000 | 0x00004000
LOGS = os.path.join(REPRO, "logs")
OUT = os.path.join(REPRO, "data", "step01")
with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as _fh:
    CONTRACTS = yaml.safe_load(_fh)
with open(os.path.join(REPRO, "config", "train_days.yaml"), encoding="utf-8") as _fh:
    TD = yaml.safe_load(_fh)
CUT = dt.datetime.strptime(TD["cuts_utc"]["validation_test"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.timezone.utc)


def l3_jobs(sym):
    root = CONTRACTS[sym]["l3_dir"]
    jobs = []
    for day in [str(d) for d in TD["l3_days_oct"]]:
        p = os.path.join(root, day)
        if not os.path.isdir(p):
            continue
        for f in sorted(os.listdir(p)):
            if not f.endswith(f"_{sym}_l3.jsonl.gz"):
                continue
            hh = f[:2]
            if dt.datetime.strptime(day + hh, "%Y%m%d%H").replace(tzinfo=dt.timezone.utc) >= CUT:
                continue                                                  # final_test 锁
            if os.path.exists(os.path.join(OUT, sym, f"{day}_{hh}.npz")):
                continue
            jobs.append((f"x_l3_{sym}_{day}_{hh}", [PY, os.path.join(REPRO, "sim_l3", "l3_extract.py"), sym, day, hh]))
    return jobs


def l2_jobs(sym):
    jobs = []
    for day in [str(d) for d in TD["train_days_sept"]]:
        for h in range(24):
            hh = f"{h:02d}"
            if os.path.exists(os.path.join(OUT, sym, f"{day}_{hh}.npz")):
                continue
            jobs.append((f"x_l2_{sym}_{day}_{hh}", [PY, os.path.join(REPRO, "a", "l2_extract.py"), sym, day, hh]))
    return jobs


def run_pool(jobs, par):
    running, t0, done = [], time.time(), 0
    while jobs or running:
        while jobs and len(running) < par:
            name, cmd = jobs.pop(0)
            fh = open(os.path.join(LOGS, "extract", f"{name}.log"), "w", encoding="utf-8")
            running.append((name, subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, creationflags=FLAGS, cwd=ROOT), fh, time.time()))
        time.sleep(2)
        for x in running[:]:
            if x[1].poll() is not None:
                x[2].close()
                running.remove(x)
                done += 1
                if x[1].returncode != 0 or done % 25 == 0:
                    print(f"end {x[0]} rc={x[1].returncode} t={time.time() - x[3]:.0f}s  done={done} left={len(jobs)} elapsed={time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    syms = sys.argv[1].split(",")
    mode = sys.argv[2] if len(sys.argv) > 2 else "both"
    par = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    os.makedirs(os.path.join(LOGS, "extract"), exist_ok=True)
    jobs = []
    for s in syms:
        if mode in ("l3", "both"):
            jobs += l3_jobs(s)
        if mode in ("l2", "both"):
            jobs += l2_jobs(s)
    print(f"jobs={len(jobs)} syms={syms} mode={mode} par={par}", flush=True)
    run_pool(jobs, par)
    print("ALL_DONE", flush=True)
