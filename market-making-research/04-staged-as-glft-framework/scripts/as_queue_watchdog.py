#!/usr/bin/env python3
"""看门狗:每 60 秒看一次 AS 回测队列的调度进程(as_queue.py)在不在,不在且队列没跑完就重新启动,并记日志。
不依赖任何会话。停:建文件 logs/as_queue.STOP。日志 logs/as_queue_watchdog.log。"""
import os, subprocess, sys, time
import psutil
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(ROOT, "logs", "as_queue_watchdog.log")
PROG = os.path.join(ROOT, "logs", "as_queue_progress.log")
STOP = os.path.join(ROOT, "logs", "as_queue.STOP")
FLAGS = 0x00000008 | 0x00000200 | 0x01000000        # 无控制台、独立信号组、脱离作业


def say(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), s))


def alive():
    for p in psutil.process_iter(["cmdline"]):
        c = p.info["cmdline"] or []
        if any(x.replace("\\", "/").endswith("research7/as_queue.py") for x in c):
            return p.pid
    return None


def all_done():
    try:
        return "ALL_DONE" in open(PROG, encoding="utf-8").read().splitlines()[-1]
    except Exception:  # noqa: BLE001
        return False


say("WATCHDOG_START pid=%d" % os.getpid())
last = alive()
while not os.path.exists(STOP) and not all_done():
    pid = alive()
    if pid is None:
        say("scheduler not running (last seen pid %s) -> restart" % last)
        cmd = [sys.executable, os.path.join(ROOT, "scripts", "research7", "as_queue.py")]
        out = open(os.path.join(ROOT, "logs", "as_queue_stderr.log"), "ab")
        try:
            p = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, creationflags=FLAGS, close_fds=True)
        except OSError:
            p = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                 creationflags=FLAGS & ~0x01000000, close_fds=True)
        say("started pid %d" % p.pid)
        time.sleep(20)
        pid = alive()
    last = pid or last
    time.sleep(60)
say("WATCHDOG_EXIT (stop file or all done)")
