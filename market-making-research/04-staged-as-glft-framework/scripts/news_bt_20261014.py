#!/usr/bin/env python3
"""第 21 步(新闻停机)回测对照,只在回测环境里跑(用户 10-14 批准用考卷日 09-04 非农、09-10 PPI、09-11 CPI)。
每天 12 时这一小时(发布 12:30 UTC,停机窗口 12:20–12:40 全在里面),BTC 实验E、ETH 实验C + 上限 15 张,
对照组 = 现在实盘的 v4 逻辑(frozen_v5),实验组 = 加新闻停机(frozen_v6,NEWS_TIMES = 当天 12:30)。同撮合、同种子。
日志 logs/news_bt/;进度 logs/news_bt_progress.log。"""
import json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
NOWIN = 0x08000000
LOGD = os.path.join(ROOT, "logs", "news_bt")
os.makedirs(LOGD, exist_ok=True)
prog = open(os.path.join(ROOT, "logs", "news_bt_progress.log"), "a", encoding="utf-8")
say = lambda m: (prog.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), m)), prog.flush())
env0 = dict(os.environ, PYTHONIOENCODING="utf-8")
DAYS = {"20260904": "非农", "20260910": "PPI", "20260911": "CPI"}
ON = dict(FAST_RETREAT=1, PULL_ON_TOUCH=1, LAT_K=1.0, VETO_BP=0.2, QUOTE_MODEL="as", GAMMA_METHOD="file", INV_ON=1)
CFG = {"BTC-USDT": dict(ON, INV_OVER={"hw_reduce_near": 0, "reduce_exempt": 0}),
       "ETH-USDT": dict(ON, INV_OVER={"pos_cap_lots": 15, "pos_age_s": 0, "hw_halflife_s": 0, "hw_reduce_near": 0, "reduce_exempt": 0})}
V5, V6 = "research/as2008/frozen_v5_20261014/as_offline.py", "research/as2008/frozen_v6_20261014/as_offline.py"

for day in DAYS:                                           # 缺什么补什么:SOL 清洗切片(ETH 因子要用)、币安成交量回放文件
    if not os.path.isdir(os.path.join(ROOT, "data", "oos", "ku_buyc", day + "_00", "kucoin", "swap", "SOL-USDT")):
        r = subprocess.run([PY, "scripts/research3/clean_buy_slices.py", "--symbols", "SOL-USDT", "--days", day, "--workers", "3"],
                           cwd=ROOT, env=env0, capture_output=True, creationflags=NOWIN)
        say("prep SOL clean %s code=%s" % (day, r.returncode))
    for s in ("BTC-USDT", "ETH-USDT"):
        if not os.path.exists(os.path.join(ROOT, "data", "research7", "as2008_bnflow", "binance_flow_%s_%s.parquet" % (s.replace("-", ""), day))):
            r = subprocess.run([PY, V6, "bnflow", s, day], cwd=ROOT, env=env0, capture_output=True, creationflags=NOWIN)
            say("prep bnflow %s %s code=%s %s" % (s, day, r.returncode, r.stderr.decode("utf-8", "replace")[-200:].replace("\n", " ")))

procs = []
for day in DAYS:
    for s in ("BTC-USDT", "ETH-USDT"):
        for tag, off, extra in (("NB0", V5, {}), ("NB1", V6, {"NEWS_TIMES": "%s-%s-%sT12:30" % (day[:4], day[4:6], day[6:])})):
            env = dict(env0, AS_CFG=json.dumps(dict(CFG[s], **extra)), AS_TAG="_" + tag)
            log = open(os.path.join(LOGD, "%s_%s_12_%s.log" % (s, day, tag)), "w", encoding="utf-8")
            procs.append(((s, day, tag), subprocess.Popen([PY, off, "run", s, day, "12", "13", "all4"], cwd=ROOT, stdout=log,
                                                          stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, creationflags=NOWIN)))
            say("start %s %s %s" % (s, day, tag))
            time.sleep(3)
for j, p in procs:
    p.wait()
    say("done %s code=%s" % (j, p.returncode))
say("ALL_DONE")
