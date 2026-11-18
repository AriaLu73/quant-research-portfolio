#!/usr/bin/env python3
"""急跌对照(用户 10-15:"不行啊这种急跌要想办法改善"),只在回测环境里跑,不碰实盘。
ETH 实验C + 上限 15 张(= 实盘 MM_AS_ETH_v2 的设定),冻结副本 frozen_v6_20261014,同撮合、同种子。
组(每组相对 L0 只改一处):
  L0 = 实盘现状(all4,拥堵加宽 lat_k = 0;实盘部署文件里就是 0)
  L1 = 拥堵加宽打开(lat_k = 1;之前的十天回测用的就是这个)
  R1 = σ 用实时预测值 rv_ewm_10s(方案 all4_rv,第 8 步;lat_k = 0)
时段:回测十天里 10 分钟变动最大、且不在每天停机时段(16–24 UTC)里的 6 个小时。
内存只剩 2 GB 左右(用户这台机器同时在用),最多并行 3 个,空闲内存不足 1.5 GB 时不启动新的。
日志 logs/crash_bt/;进度 logs/crash_bt_progress.log。"""
import json, os, subprocess, time
import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
OFF = "research/as2008/frozen_v6_20261014/as_offline.py"
NOWIN, PAR = 0x08000000, 3
LOGD = os.path.join(ROOT, "logs", "crash_bt")
os.makedirs(LOGD, exist_ok=True)
prog = open(os.path.join(ROOT, "logs", "crash_bt_progress.log"), "a", encoding="utf-8")
say = lambda m: (prog.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), m)), prog.flush())
env0 = dict(os.environ, PYTHONIOENCODING="utf-8")
EXPL = dict(FAST_RETREAT=1, PULL_ON_TOUCH=1, VETO_BP=0.2, QUOTE_MODEL="as", GAMMA_METHOD="file", INV_ON=1,
            INV_OVER={"pos_cap_lots": 15, "pos_age_s": 0, "hw_halflife_s": 0, "hw_reduce_near": 0, "reduce_exempt": 0})
GROUPS = {"L0": ("all4", dict(EXPL, LAT_K=0.0)), "L1": ("all4", dict(EXPL, LAT_K=1.0)), "R1": ("all4_rv", dict(EXPL, LAT_K=0.0))}
HOURS = (("20260923", 14), ("20260918", 13), ("20260828", 14), ("20260827", 10), ("20260924", 14), ("20260828", 13))

jobs = [(day, h, tag) for day, h in HOURS for tag in GROUPS]
running = []
while jobs or running:
    for j, p in running:
        if p.poll() is not None:
            say("done %s code=%s" % (j, p.returncode))
    running = [(j, p) for j, p in running if p.poll() is None]
    if jobs and len(running) < PAR and psutil.virtual_memory().available > 1.5 * 2**30:
        day, h, tag = jobs.pop(0)
        var, cfg = GROUPS[tag]
        out = os.path.join(ROOT, "data", "research7", "as2008_l3", "run_ETH-USDT_%s_%02d_%02d_%s_%s.json" % (day, h, h + 1, var, tag))
        if os.path.exists(out):
            say("skip %s %s %s (已有结果)" % (day, h, tag))
            continue
        env = dict(env0, AS_CFG=json.dumps(cfg), AS_TAG="_" + tag)
        log = open(os.path.join(LOGD, "ETH-USDT_%s_%02d_%s.log" % (day, h, tag)), "w", encoding="utf-8")
        p = subprocess.Popen([PY, OFF, "run", "ETH-USDT", day, str(h), str(h + 1), var], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, creationflags=NOWIN)
        running.append(((day, h, tag), p))
        say("start %s %s %s" % (day, h, tag))
    time.sleep(10)
say("ALL_DONE")
