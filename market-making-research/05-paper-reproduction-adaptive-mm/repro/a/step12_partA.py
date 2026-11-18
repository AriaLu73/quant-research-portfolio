"""Step 12(Part A 列):对 Δt ∈ {100, 250, 500, 2000}(1000 已有)分别重建目录并回放实验 A(P1 策略 + Level 基准),每个 (合约, Δt) 一个子进程。
用法  python step12_partA.py <sym:V_LO>[,<sym:V_LO>] [dts] [par]
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
PY = sys.executable
FLAGS = 0x08000000 | 0x00004000
LOGS = os.path.join(REPRO, "logs")


def run_pool(jobs, par):
    running = []
    while jobs or running:
        while jobs and len(running) < par:
            name, cmd = jobs.pop(0)
            fh = open(os.path.join(LOGS, f"{name}.log"), "w", encoding="utf-8")
            running.append((name, subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, creationflags=FLAGS, cwd=REPRO), fh, time.time()))
            print("start", name, flush=True)
        time.sleep(10)
        for x in running[:]:
            if x[1].poll() is not None:
                x[2].close(); running.remove(x)
                print(f"end {x[0]} rc={x[1].returncode} t={time.time() - x[3]:.0f}s", flush=True)


if __name__ == "__main__":
    pairs = [p.split(":") for p in sys.argv[1].split(",")]
    dts = [int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else ["2000", "500", "250", "100"])]
    par = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    jobs = [(f"expA_{sym}_dt{dt}", [PY, os.path.join(HERE, "run_expA.py"), sym, vlo, str(dt)]) for dt in dts for sym, vlo in pairs]
    run_pool(jobs, par)
    print("STEP12A_DONE", flush=True)
