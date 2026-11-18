#!/usr/bin/env python3
"""ETH 实验 C vs 实验 E 对照,第二版(用户 10-15:回测要和实盘一样;"要啊不然你回测慢的要死")。只在回测环境里跑。
  C = all4 + 第 9–16 步(不贴盘口、信号撤单、拥堵加宽、因子点名不挂 0.2 bp),库存管理全关(允许逆风加仓)
  E = C + 逆风不加仓(第 17 步 ③:自己的失衡按 10 秒半衰期平滑,逆着仓位方向就不挂加仓侧);ETH 上只多这一条
  冻结代码 frozen_v7_20261015(= v6 + 负载门槛可外部指定)。回测引擎按实盘规则发盘口:前 50 档有变化才发一帧、1 毫秒合并
  (HFT_BT_DEPTH_TOPN=50、HFT_BT_DEPTH_CONFLATE_MS=1),盘口视图 50 档;负载门槛用回测引擎按同一规则实际发出的帧重标
  (data/research7/bt_load_edges_live.json,scripts/research7/bt_load_edges.py engine)。同撮合、同种子,十天全天。结果标签 C7 / E7。
  (第一版 C6 / E6 是旧发布规则下的,已停,完成的 22 段留作参照。)
并行:默认 12 个;空闲内存不足 800 MB 时不启动新的。按天排。
日志 logs/ce_bt7/;进度 logs/ce_bt7_progress.log。停:建文件 logs/ce_bt7.STOP(已启动的跑完即止)。"""
import json, os, subprocess, sys, time
import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
OFF = "research/as2008/frozen_v7_20261015/as_offline.py"
NOWIN = 0x08000000
PAR = int(sys.argv[1]) if len(sys.argv) > 1 else 12
LOGD = os.path.join(ROOT, "logs", "ce_bt7")
STOP = os.path.join(ROOT, "logs", "ce_bt7.STOP")
os.makedirs(LOGD, exist_ok=True)
prog = open(os.path.join(ROOT, "logs", "ce_bt7_progress.log"), "a", encoding="utf-8")
say = lambda m: (prog.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), m)), prog.flush())
env0 = dict(os.environ, PYTHONIOENCODING="utf-8", HFT_BT_VIEW_LEVELS="5", HFT_BT_DEPTH_TOPN="5", HFT_BT_DEPTH_CONFLATE_MS="1",
            AS_LOAD_EDGES_JSON=os.path.join(ROOT, "data", "research7", "bt_load_edges_live.json"))   # 用户 10-15:回测发盘口的规则和实盘一致
ON = dict(FAST_RETREAT=1, PULL_ON_TOUCH=1, LAT_K=1.0, VETO_BP=0.2, QUOTE_MODEL="as", GAMMA_METHOD="file")
GROUPS = {"C7": dict(ON), "E7": dict(ON, INV_ON=1, INV_OVER={"hw_reduce_near": 0, "reduce_exempt": 0})}
DAYS = ("20260918", "20260924", "20260923", "20260917", "20260901", "20260831", "20260830", "20260829", "20260828", "20260827")


def out(day, h0, tag):
    return os.path.join(ROOT, "data", "research7", "as2008_l3", "run_ETH-USDT_%s_%02d_%02d_all4_%s.json" % (day, h0, h0 + 6, tag))


jobs = [(day, h0, tag) for day in DAYS for tag in GROUPS for h0 in (12, 0, 6, 18) if not os.path.exists(out(day, h0, tag))]
say("START par=%d jobs=%d" % (PAR, len(jobs)))
running, fails = [], {}
while (jobs and not os.path.exists(STOP)) or running:
    for j, p in running:
        if p.poll() is not None:
            ok = p.returncode == 0 and os.path.exists(out(*j))
            say("done %s %s %s code=%s%s" % (j[0], j[1], j[2], p.returncode, "" if ok else " FAILED"))
            if not ok and fails.get(j, 0) < 1:                 # 失败的(多半是内存不够被挤掉)排到最后再跑一次
                fails[j] = fails.get(j, 0) + 1
                jobs.append(j)
    running = [(j, p) for j, p in running if p.poll() is None]
    if jobs and not os.path.exists(STOP) and len(running) < PAR and psutil.virtual_memory().available > 800 * 2**20:
        day, h0, tag = jobs.pop(0)
        env = dict(env0, AS_CFG=json.dumps(GROUPS[tag]), AS_TAG="_" + tag)
        log = open(os.path.join(LOGD, "ETH-USDT_%s_%02d_%s.log" % (day, h0, tag)), "w", encoding="utf-8")
        p = subprocess.Popen([PY, OFF, "run", "ETH-USDT", day, str(h0), str(h0 + 6), "all4"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, creationflags=NOWIN)
        running.append(((day, h0, tag), p))
        say("start %s %02d %s (running %d)" % (day, h0, tag, len(running)))
        time.sleep(8)
        continue
    time.sleep(15)
say("ALL_DONE")
