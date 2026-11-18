#!/usr/bin/env python3
"""AS 回测队列的调度(2026-10-13 夜):一个池子并行 PAR 个时段,已有结果的跳过,正在跑的(按进程命令行认)不重复启动。
可以随时被杀、随时重启:状态只在结果文件和进程表里。看门狗 scripts/research7/as_queue_watchdog.py 发现它不在就重启。
停:建文件 logs/as_queue.STOP(已启动的时段跑完即止,看门狗也不再重启)。
组:CTRL = AS 原版;EXPC = 实验C(ETH 不限仓);EXPE = BTC 实验E;EXPL = ETH 实验C + 持仓上限 15 张(实盘设定)。冻结副本 research/as2008/frozen_v3_20261013。
"""
import json, os, signal, subprocess, sys, time, traceback
import psutil
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
OFF = "research/as2008/frozen_v3_20261013/as_offline.py"
D = os.path.join(ROOT, "data", "research7", "as2008_l3")
LOGD = os.path.join(ROOT, "logs", "as_queue")
STOP = os.path.join(ROOT, "logs", "as_queue.STOP")
NOWIN, PAR = 0x08000000, 8
ON = dict(FAST_RETREAT=1, PULL_ON_TOUCH=1, LAT_K=1.0, VETO_BP=0.2, QUOTE_MODEL="as", GAMMA_METHOD="file")
CFG = {"CTRL": ("base", dict(FAST_RETREAT=0, PULL_ON_TOUCH=0, LAT_K=0.0, VETO_BP=0.0, QUOTE_MODEL="as", GAMMA_METHOD="file", INV_ON=0)),   # 10-15 as_offline 默认改成库存管理开,对照组显式关
       "EXPC": ("all4", ON),
       "EXPE": ("all4", dict(ON, INV_ON=1, INV_OVER={"hw_reduce_near": 0, "reduce_exempt": 0})),
       "EXPL": ("all4", dict(ON, INV_ON=1, INV_OVER={"pos_cap_lots": 15, "pos_age_s": 0, "hw_halflife_s": 0, "hw_reduce_near": 0, "reduce_exempt": 0}))}
CFG["EXP2"] = ("all4", dict(CFG["EXPL"][1], ORDER_QTY=2.0))     # 10-14 用户:ETH 实盘组只把每张从 1.0 改成 2.0(上限仍 15 张 = 30 ETH)
GROUPS = (("ETH-USDT", "EXPL"), ("BTC-USDT", "EXPE"), ("ETH-USDT", "CTRL"), ("BTC-USDT", "CTRL"), ("ETH-USDT", "EXPC"))
DAYS = ("20260923", "20260917", "20260901", "20260831", "20260827", "20260830", "20260829", "20260828")
DAYS2 = ("20260918", "20260924", "20260923", "20260917", "20260901", "20260831", "20260827", "20260830", "20260829", "20260828")   # 放大组,排在主队列之后
os.makedirs(LOGD, exist_ok=True)
env0 = dict(os.environ, PYTHONIOENCODING="utf-8")
prog = open(os.path.join(ROOT, "logs", "as_queue_progress.log"), "a", encoding="utf-8")


def say(s):
    prog.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), s))
    prog.flush()


def done(s, day, h0, tag):
    return os.path.exists(os.path.join(D, "run_%s_%s_%02d_%02d_%s_%s.json" % (s, day, h0, h0 + 6, CFG[tag][0], tag)))


def live_jobs():
    """正在跑的时段:(合约, 日期, 起始小时, 组)。组从进程环境变量 AS_TAG 读。"""
    out = set()
    for p in psutil.process_iter(["cmdline"]):
        c = p.info["cmdline"] or []
        if len(c) >= 7 and "as_offline.py" in c[1].replace("\\", "/") and c[2] == "run":
            try:
                out.add((c[3], c[4], int(c[5]), p.environ().get("AS_TAG", "").lstrip("_")))
            except Exception:  # noqa: BLE001
                pass
    return out


def prep(day):
    if not os.path.isdir(os.path.join(ROOT, "data", "oos", "ku_buyc", day + "_00", "kucoin", "swap", "SOL-USDT")):
        r = subprocess.run([PY, "scripts/research3/clean_buy_slices.py", "--symbols", "SOL-USDT", "--days", day, "--workers", "3"],
                           cwd=ROOT, env=env0, capture_output=True, creationflags=NOWIN)
        say("prep SOL clean %s code=%s" % (day, r.returncode))
    for s in ("BTC-USDT", "ETH-USDT"):
        if not os.path.exists(os.path.join(ROOT, "data", "research7", "as2008_bnflow", "binance_flow_%s_%s.parquet" % (s.replace("-", ""), day))):
            r = subprocess.run([PY, OFF, "bnflow", s, day], cwd=ROOT, env=env0, capture_output=True, creationflags=NOWIN)
            say("prep bnflow %s %s code=%s" % (s, day, r.returncode))


def start(s, day, h0, tag):
    variant, cfg = CFG[tag]
    env = dict(env0, AS_CFG=json.dumps(cfg), AS_TAG="_" + tag)
    log = open(os.path.join(LOGD, "%s_%s_%02d_%s.log" % (s, day, h0, tag)), "w", encoding="utf-8")
    subprocess.Popen([PY, OFF, "run", s, day, str(h0), str(h0 + 6), variant], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, env=env, creationflags=NOWIN | 0x00000200)


def main():
    for sg in (signal.SIGINT, signal.SIGTERM, signal.SIGBREAK):
        signal.signal(sg, lambda n, f: say("SIGNAL %s received (ignored)" % n))
    say("SCHEDULER_START pid=%d ppid=%d" % (os.getpid(), os.getppid()))
    prepped, reported, fails = set(), set(), {}
    while not os.path.exists(STOP):
        live = live_jobs()
        for day in DAYS:                                       # 一天的时段全部有结果 → 记一行,日报脚本据此出表
            if day not in reported and all(done(s, day, h0, t) for h0 in (0, 6, 12, 18) for s, t in GROUPS):
                reported.add(day)
                say("DAY_DONE %s" % day)
        for day in DAYS2:
            if "2_" + day not in reported and all(done("ETH-USDT", day, h0, "EXP2") for h0 in (0, 6, 12, 18)):
                reported.add("2_" + day)
                say("EXP2_DAY_DONE %s" % day)
        todo = [(s, day, h0, t) for day in DAYS for h0 in (12, 0, 6, 18) for s, t in GROUPS] +                [("ETH-USDT", day, h0, "EXP2") for day in DAYS2 for h0 in (12, 0, 6, 18)]
        todo = [j for j in todo if not done(*j) and j not in live and fails.get(j, 0) < 2]
        if not todo and not live:
            say("ALL_DONE")
            return
        for job in todo[:max(PAR - len(live), 0)]:
            if job[1] not in prepped:
                prep(job[1])
                prepped.add(job[1])
            start(*job)
            fails[job] = fails.get(job, 0) + 1                 # 同一个时段最多启动两次(第一次没出结果才有第二次)
            live.add(job)
            say("start %s %s %02d %s (running %d)" % (job + (len(live),)))
            time.sleep(8)
        time.sleep(30)
    say("STOP file found, scheduler exits")


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        say("SCHEDULER_DIED " + " | ".join(traceback.format_exc().splitlines()))
        raise
