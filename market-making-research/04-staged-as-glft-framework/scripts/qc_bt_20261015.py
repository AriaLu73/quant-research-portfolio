#!/usr/bin/env python3
"""回测口径对照(用户 10-15 最高优先级):① 持仓连续 vs 每小时清零;② 排队队首 vs 队尾。只在回测环境里跑。
  组(每组只改一处):QH1 = 每小时一个引擎进程、空仓起步、整点按中间价估值(以前所有回测的做法),排队队首(queue_cancel_bias 1.0)
                    QC1 = 整天一个引擎进程,持仓和策略状态跨小时延续(和实盘一样),排队队首
                    QC0 = 整天连续,排队队尾(queue_cancel_bias 0.0:价位上公共量减少全部算在我方后面,只有成交能让我方往前排)
  策略:BTC = 实盘设定实验 E;ETH = 实盘设定实验 C + 上限 15 张。冻结代码 frozen_v7,盘口发布按回测原规则(每条变化都发),50 档快照,
  负载门槛用参数文件里的(回测原办法),同撮合同种子。日子:09-18、09-24、09-23(整天数据目录 data/oos/ku_buycday,scripts/research7/build_day_feed.py 拼的)。
  并行 14;整天的长任务先排。日志 logs/qc_bt/;进度 logs/qc_bt/progress.log。停:logs/qc_bt.STOP。"""
import json, os, subprocess, time
import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
OFF = "research/as2008/frozen_v7_20261015/as_offline.py"
NOWIN, PAR = 0x08000000, 14
LOGD = os.path.join(ROOT, "logs", "qc_bt")
STOP = os.path.join(ROOT, "logs", "qc_bt.STOP")
os.makedirs(LOGD, exist_ok=True)
prog = open(os.path.join(LOGD, "progress.log"), "a", encoding="utf-8")
say = lambda m: (prog.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), m)), prog.flush())
ON = dict(FAST_RETREAT=1, PULL_ON_TOUCH=1, LAT_K=1.0, VETO_BP=0.2, QUOTE_MODEL="as", GAMMA_METHOD="file", INV_ON=1)
CFG = {"BTC-USDT": dict(ON, INV_OVER={"hw_reduce_near": 0, "reduce_exempt": 0}),
       "ETH-USDT": dict(ON, INV_OVER={"pos_cap_lots": 15, "pos_age_s": 0, "hw_halflife_s": 0, "hw_reduce_near": 0, "reduce_exempt": 0})}
GROUPS = {"QH1": dict(AS_QUEUE_BIAS="1.0"), "QC1": dict(AS_QUEUE_BIAS="1.0", AS_FEED="ku_buycday", AS_SPAN_HOURS="24"),
          "QC0": dict(AS_QUEUE_BIAS="0.0", AS_FEED="ku_buycday", AS_SPAN_HOURS="24")}
DAYS = ("20260918", "20260924", "20260923")


def out(sym, day, h0, h1, tag):
    return os.path.join(ROOT, "data", "research7", "as2008_l3", "run_%s_%s_%02d_%02d_all4_%s.json" % (sym, day, h0, h1, tag))


jobs = []
for tag in ("QC1", "QC0"):                                  # 整天的长任务先排:ETH 最慢
    for sym in ("ETH-USDT", "BTC-USDT"):
        for day in DAYS:
            jobs.append((sym, day, 0, 24, tag))
for day in DAYS:
    for sym in ("BTC-USDT", "ETH-USDT"):
        for h0 in (0, 6, 12, 18):
            jobs.append((sym, day, h0, h0 + 6, "QH1"))
jobs = [j for j in jobs if not os.path.exists(out(*j))]
say("START par=%d jobs=%d" % (PAR, len(jobs)))
running = []
while (jobs and not os.path.exists(STOP)) or running:
    for j, p in running:
        if p.poll() is not None:
            say("done %s %s %02d-%02d %s code=%s%s" % (j[0], j[1], j[2], j[3], j[4], p.returncode, "" if os.path.exists(out(*j)) else " FAILED"))
    running = [(j, p) for j, p in running if p.poll() is None]
    if jobs and not os.path.exists(STOP) and len(running) < PAR and psutil.virtual_memory().available > 800 * 2**20:
        sym, day, h0, h1, tag = j = jobs.pop(0)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", HFT_BT_VIEW_LEVELS="50", AS_CFG=json.dumps(CFG[sym]), AS_TAG="_" + tag, **GROUPS[tag])
        log = open(os.path.join(LOGD, "%s_%s_%02d_%s.log" % (sym, day, h0, tag)), "w", encoding="utf-8")
        running.append((j, subprocess.Popen([PY, OFF, "run", sym, day, str(h0), str(h1), "all4"], cwd=ROOT, env=env, stdout=log,
                                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=NOWIN)))
        say("start %s %s %02d-%02d %s (running %d)" % (sym, day, h0, h1, tag, len(running)))
        time.sleep(6)
        continue
    time.sleep(15)
say("ALL_DONE")
