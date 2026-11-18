"""阶段 0 流水线:USDC 两合约 质量扫描(并行)→ trade_gaps → segments.py --cuts-from XBTUSDTM。
输出 research_mm/data/quality/<sym>_<day>.json、research_mm/data/market/<sym>_<day>_<hh>.npz、
     repro/config/splits/<sym>.yaml、research_mm/data/segments_<sym>.json
"""
import datetime as dt
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine_bridge as B   # noqa: E402

PY = os.path.join(B.ROOT, ".venv", "Scripts", "python.exe")
FLAGS = 0x08000000 | 0x00004000      # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS(用户规矩:后台任务不许弹窗)
HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(B.REPRO, "logs")
QDIR = os.path.join(B.ROOT, "research_mm", "data", "quality")
SEG = os.path.join(B.ROOT, "research_mm", "src", "analytics", "segments.py")
SYMS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["XBTUSDCM", "ETHUSDCM"]
PAR = int(sys.argv[2]) if len(sys.argv) > 2 else 8


def run_pool(jobs, par):
    running = []
    while jobs or running:
        while jobs and len(running) < par:
            name, cmd = jobs.pop(0)
            fh = open(os.path.join(LOGS, f"{name}.log"), "w", encoding="utf-8")
            p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, creationflags=FLAGS, cwd=B.ROOT)
            running.append((name, p, fh, time.time()))
            print(f"start {name}", flush=True)
        time.sleep(5)
        for x in running[:]:
            if x[1].poll() is not None:
                x[2].close()
                running.remove(x)
                print(f"end {x[0]} rc={x[1].returncode} t={time.time() - x[3]:.0f}s", flush=True)


if __name__ == "__main__":
    os.makedirs(LOGS, exist_ok=True)
    t0 = time.time()
    jobs = []
    for sym in SYMS:
        for day in B.days_of(sym):
            if os.path.exists(os.path.join(QDIR, f"{sym}_{day}.json")):
                continue
            jobs.append((f"quality_{sym}_{day}", [PY, os.path.join(HERE, "run_quality.py"), "scan", sym, day]))
    print(f"scan jobs: {len(jobs)}", flush=True)
    run_pool(jobs, PAR)
    run_pool([(f"trade_gaps_{sym}", [PY, os.path.join(HERE, "run_quality.py"), "trade_gaps", sym]) for sym in SYMS], PAR)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for sym in SYMS:
        out = os.path.join(B.REPRO, "config", "splits", f"{sym}.yaml")
        if os.path.exists(out):
            print(f"{sym}: split 已存在,跳过", flush=True)
            continue
        cmd = [PY, SEG, sym, "--cuts-from", os.path.join(B.REPRO, "config", "splits", "XBTUSDTM.yaml"), "--out", out, "--write", stamp]
        run_pool([(f"segments_{sym}", cmd)], 1)
    print(f"ALL_DONE t={time.time() - t0:.0f}s", flush=True)
