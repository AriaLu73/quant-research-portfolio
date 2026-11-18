#!/usr/bin/env python3
"""research7 按天并行运行某个 L2 回放脚本的调度器(可续跑:已有输出文件的日期跳过)。与 run_hours.py 同理,经 detach.py 脱离会话启动。

用途      回放脚本形如 `<脚本> run <YYYYMMDD>`、每天一个输出文件 fills_<day>.npz。
所属阶段  基础设施;不属于研究模块,不对应报价公式中的某一项。
用法      python scripts/detach.py --log data/research7/logs/<名字>.log -- .venv/Scripts/python.exe scripts/research7/run_days.py <脚本名> <输出目录名> <并行数>
"""
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def main(script, outdir, par):
    out = os.path.join(ROOT, "data", "research7", outdir)
    days = sorted(os.path.basename(f)[9:17] for f in glob.glob(os.path.join(ROOT, "data", "research7", "l2", "XBTUSDTM_????????.npz")))
    todo = [d for d in days if not os.path.exists(os.path.join(out, f"fills_{d}.npz"))]
    print(f"[run_days] {script}: 待跑 {len(todo)} 天,并行 {par}", flush=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    running = []
    while todo or running:
        running = [p for p in running if p.poll() is None]
        while todo and len(running) < par:
            d = todo.pop(0)
            running.append(subprocess.Popen([sys.executable, os.path.join(HERE, script + ".py"), "run", d], cwd=ROOT, env=env, stdout=sys.stdout, stderr=subprocess.STDOUT))
        time.sleep(2)
    print(f"[run_days] {script}: ALL_DONE", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]))
