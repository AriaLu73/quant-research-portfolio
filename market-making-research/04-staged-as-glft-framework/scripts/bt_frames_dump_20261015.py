#!/usr/bin/env python3
"""回测负载门槛标定的第一步:让回测引擎按实盘规则发盘口(前 5 档变化才发、1 毫秒合并;10-15 更正:实盘 depth_publish_levels = 5),在估计日 12–18 时 UTC 跑一遍,
记下实际发给策略的盘口帧和逐笔成交时刻(HFT_BT_FRAME_DUMP=1 → 每小时一个 frames.npz)。
策略行为不影响发了哪些帧(只取决于行情和发布规则),所以用实验 C 的设定跑即可;负载门槛暂用参数文件里的(不影响帧)。
第二步:scripts/research7/bt_load_edges.py engine <日期...> 读这些 frames.npz 算门槛。"""
import json, os, subprocess, sys, time
import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
OFF = "research/as2008/frozen_v7_20261015/as_offline.py"
NOWIN = 0x08000000
DAYS = ("20260917", "20260923", "20260918", "20260914", "20260831", "20260830", "20260829", "20260828", "20260827", "20260826")
env0 = dict(os.environ, PYTHONIOENCODING="utf-8", HFT_BT_VIEW_LEVELS="5", HFT_BT_DEPTH_TOPN="5", HFT_BT_DEPTH_CONFLATE_MS="1", HFT_BT_FRAME_DUMP="1",
            AS_CFG=json.dumps(dict(FAST_RETREAT=1, PULL_ON_TOUCH=1, LAT_K=1.0, VETO_BP=0.2, QUOTE_MODEL="as", GAMMA_METHOD="file")), AS_TAG="_FRM")
LOGD = os.path.join(ROOT, "logs", "bt_frames")
os.makedirs(LOGD, exist_ok=True)
prog = open(os.path.join(LOGD, "progress.log"), "a", encoding="utf-8")
say = lambda m: (prog.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), m)), prog.flush())

for day in ("20260914", "20260826"):                      # 这两天不是回测日,缺 SOL 清洗切片和币安成交回放文件
    if not os.path.isdir(os.path.join(ROOT, "data", "oos", "ku_buyc", day + "_12", "kucoin", "swap", "SOL-USDT")):
        r = subprocess.run([PY, "scripts/research3/clean_buy_slices.py", "--symbols", "SOL-USDT", "--days", day, "--workers", "3"],
                           cwd=ROOT, env=env0, capture_output=True, creationflags=NOWIN)
        say("prep SOL %s code=%s" % (day, r.returncode))
    if not os.path.exists(os.path.join(ROOT, "data", "research7", "as2008_bnflow", "binance_flow_ETHUSDT_%s.parquet" % day)):
        r = subprocess.run([PY, OFF, "bnflow", "ETH-USDT", day], cwd=ROOT, env=env0, capture_output=True, creationflags=NOWIN)
        say("prep bnflow %s code=%s %s" % (day, r.returncode, r.stderr.decode("utf-8", "replace")[-200:].replace("\n", " ")))

running = []
jobs = list(DAYS)
while jobs or running:
    for d, p in running:
        if p.poll() is not None:
            say("done %s code=%s" % (d, p.returncode))
    running = [(d, p) for d, p in running if p.poll() is None]
    if jobs and len(running) < 10 and psutil.virtual_memory().available > 800 * 2**20:
        d = jobs.pop(0)
        log = open(os.path.join(LOGD, "ETH-USDT_%s.log" % d), "w", encoding="utf-8")
        envd = dict(env0, AS_PARAMS_DAY="20260827") if d == "20260826" else env0   # 08-26 参数文件里没有,借 08-27 的策略参数(不影响发了哪些帧)
        running.append((d, subprocess.Popen([PY, OFF, "run", "ETH-USDT", d, "12", "18", "all4"], cwd=ROOT, env=envd, stdout=log,
                                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=NOWIN)))
        say("start %s" % d)
        time.sleep(8)
        continue
    time.sleep(15)
say("ALL_DONE")
