"""V_LO 批跑:等 config/splits/<sym>.yaml 出现 → 对 train 区间覆盖的每个 (日, 小时) 跑 vlo_collect.py(并行)→ vlo_aggregate.py。
用法  python step00_vlo_pipeline.py <sym>[,<sym>] [par]
"""
import datetime as dt
import os
import subprocess
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine_bridge as B   # noqa: E402

PY = os.path.join(B.ROOT, ".venv", "Scripts", "python.exe")
FLAGS = 0x08000000 | 0x00004000      # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS
HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(B.REPRO, "logs")
HOUR_NS = 3_600_000_000_000


def hours_for(sym, iv):
    want = {}
    for a, b in iv:
        t = (a // HOUR_NS) * HOUR_NS
        while t < b:
            d = dt.datetime.fromtimestamp(t / 1e9, dt.timezone.utc)
            want.setdefault(d.strftime("%Y%m%d"), set()).add(d.strftime("%H"))
            t += HOUR_NS
    out = []
    root = B.CONTRACTS[sym]["l3_dir"]
    for day, hs in sorted(want.items()):
        p = os.path.join(root, day)
        have = {f[:2] for f in os.listdir(p) if f.endswith(f"_{sym}_l3.jsonl.gz")} if os.path.isdir(p) else set()
        out += [(day, h) for h in sorted(hs & have)]
    return out


def run_pool(jobs, par):
    running = []
    while jobs or running:
        while jobs and len(running) < par:
            name, cmd = jobs.pop(0)
            fh = open(os.path.join(LOGS, f"{name}.log"), "w", encoding="utf-8")
            running.append((name, subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, creationflags=FLAGS, cwd=B.ROOT), fh, time.time()))
        time.sleep(3)
        for x in running[:]:
            if x[1].poll() is not None:
                x[2].close()
                running.remove(x)
                print(f"end {x[0]} rc={x[1].returncode} t={time.time() - x[3]:.0f}s", flush=True)


if __name__ == "__main__":
    syms = sys.argv[1].split(",")
    par = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    os.makedirs(LOGS, exist_ok=True)
    for sym in syms:
        sp = os.path.join(B.REPRO, "config", "splits", f"{sym}.yaml")
        while not os.path.exists(sp):
            print(f"waiting for {sp}", flush=True)
            time.sleep(60)
        with open(sp, encoding="utf-8") as fh:
            iv = [(x["start_ns"], x["end_ns"]) for x in yaml.safe_load(fh)["split"]["train"]["intervals"]]
        jobs = []
        for day, hh in hours_for(sym, iv):
            if os.path.exists(os.path.join(B.REPRO, "_tmp", "vlo", f"{sym}_{day}_{hh}.npz")):
                continue
            jobs.append((f"vlo_{sym}_{day}_{hh}", [PY, os.path.join(HERE, "vlo_collect.py"), sym, day, hh]))
        print(f"{sym}: {len(jobs)} hour jobs, train {sum(b - a for a, b in iv) / 3.6e12:.1f} h", flush=True)
        run_pool(jobs, par)
        run_pool([(f"vlo_aggregate_{sym}", [PY, os.path.join(HERE, "vlo_aggregate.py"), sym])], 1)
    print("ALL_DONE", flush=True)
