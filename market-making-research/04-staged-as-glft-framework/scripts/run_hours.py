#!/usr/bin/env python3
"""research7 按小时并行运行某个回放脚本的调度器(可续跑:已有输出文件的小时跳过)。

用途      回放脚本都是 `<脚本> run <YYYYMMDD> <HH>` 的形式、每个小时一个输出文件。会话或程序退出时由会话启动的进程会被一并终止
          (2026-10-08 阶段 5 的回放因此中断),所以改由本调度器经 scripts/detach.py 脱离会话启动,并且重启后只补没跑完的小时。
所属阶段  基础设施;不属于研究模块,不对应报价公式中的某一项。
实现      用 subprocess 逐个启动子进程(不用 multiprocessing 进程池:项目记录 research6 里它在脱离会话后报过 WinError 5)。
用法      python scripts/detach.py --log data/research7/logs/<名字>.log -- .venv/Scripts/python.exe scripts/research7/run_hours.py <脚本名> <输出目录名> <并行数>
          例:... run_hours.py stage6_replay stage6 8
"""
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
L3 = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt")
DAYS = ("20261001", "20261002")       # 有逐笔委托的两天(预登记第 2 节)


def main(script, outdir, par):
    out = os.path.join(ROOT, "data", "research7", outdir)
    todo = []
    for d in DAYS:
        for f in sorted(glob.glob(os.path.join(L3, d, "??_XBTUSDTM_l3.jsonl.gz"))):
            hh = os.path.basename(f)[:2]
            if not os.path.exists(os.path.join(out, f"fills_{d}_{hh}.npz")):
                todo.append((d, hh))
    print(f"[run_hours] {script}: 待跑 {len(todo)} 个小时,并行 {par}", flush=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    running = []
    while todo or running:
        running = [p for p in running if p.poll() is None]
        while todo and len(running) < par:
            d, hh = todo.pop(0)
            running.append(subprocess.Popen([sys.executable, os.path.join(HERE, script + ".py"), "run", d, hh], cwd=ROOT, env=env,
                                            stdout=sys.stdout, stderr=subprocess.STDOUT))
        time.sleep(2)
    print(f"[run_hours] {script}: ALL_DONE", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]))
