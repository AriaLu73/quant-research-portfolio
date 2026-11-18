#!/usr/bin/env python3
"""BTC 实盘那套策略(实验 E:上限 3 张、300 秒不加仓、逆风不加仓)搬到 BTC-USDC 上能不能用(用户 10-15)。只在回测环境里跑。
  对照:同一天 09-18 全天,BTC-USDT 和 BTC-USDC 各跑一遍,同一份冻结代码 frozen_v7、实盘发盘口规则(前 50 档、1 毫秒合并)、50 档、同种子。
  参数:BTC-USDC 沿用 BTC-USDT 上估的(同一份 params_daily.json,"一样的策略");每张 0.03 BTC(USDC 合约 300 张)。
  返佣:USDT 我方费率,USDC 我方费率(我方费率档)。币安参考行情同为 BTCUSDT。
  负载门槛:各自按回测引擎实际发出的帧标(估计日 09-17);BTC-USDT 取自 ETH 那轮记下的帧,BTC-USDC 先单独跑一遍 09-17 12–18 时记帧。
  结果标签 BU7(USDT)/ BC7(USDC)。日志 logs/usdc_bt/;进度 logs/usdc_bt/progress.log。"""
import json, os, subprocess, time
import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
OFF = "research/as2008/frozen_v7_20261015/as_offline.py"
NOWIN = 0x08000000
LOGD = os.path.join(ROOT, "logs", "usdc_bt")
os.makedirs(LOGD, exist_ok=True)
prog = open(os.path.join(LOGD, "progress.log"), "a", encoding="utf-8")
say = lambda m: (prog.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), m)), prog.flush())
EXPE = dict(FAST_RETREAT=1, PULL_ON_TOUCH=1, LAT_K=1.0, VETO_BP=0.2, QUOTE_MODEL="as", GAMMA_METHOD="file", INV_ON=1,
            INV_OVER={"hw_reduce_near": 0, "reduce_exempt": 0})
BASE = dict(os.environ, PYTHONIOENCODING="utf-8", HFT_BT_VIEW_LEVELS="5", HFT_BT_DEPTH_TOPN="5", HFT_BT_DEPTH_CONFLATE_MS="1", AS_CFG=json.dumps(EXPE))
EDGES = os.path.join(ROOT, "data", "research7", "bt_load_edges_live.json")
FEE = {"BTC-USDT": "OUR_FEE", "BTC-USDC": "OUR_FEE"}
TAG = {"BTC-USDT": "BU5", "BTC-USDC": "BC5"}   # 10-15 更正:按实盘前 5 档规则重跑(BU7 / BC7 是错按 50 档跑的)


def start(sym, day, h0, h1, tag, extra):
    env = dict(BASE, AS_MAKER_FEE=FEE[sym], AS_TAG="_" + tag, **extra)
    log = open(os.path.join(LOGD, "%s_%s_%02d_%s.log" % (sym, day, h0, tag)), "w", encoding="utf-8")
    return subprocess.Popen([PY, OFF, "run", sym, day, str(h0), str(h1), "all4"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=NOWIN)


procs = []
for h0 in (0, 6, 12, 18):                                   # BTC-USDT 的门槛已经有了,直接开跑(已有结果就跳过)
    if os.path.exists(os.path.join(ROOT, "data", "research7", "as2008_l3", "run_BTC-USDT_20260918_%02d_%02d_all4_BU5.json" % (h0, h0 + 6))):
        continue
    procs.append((("BTC-USDT", h0), start("BTC-USDT", "20260918", h0, h0 + 6, TAG["BTC-USDT"], dict(AS_LOAD_EDGES_JSON=EDGES))))
    say("start BTC-USDT 0918 %02d" % h0)
    time.sleep(5)
dump = start("BTC-USDC", "20260917", 12, 18, "FRMC", dict(HFT_BT_FRAME_DUMP="1"))     # BTC-USDC 估计日 09-17 记帧
say("start dump BTC-USDC 0917 12-18")
dump.wait()
say("dump done code=%s" % dump.returncode)
r = subprocess.run([r"Python314/python.exe", "scripts/research7/bt_load_edges.py", "engine", "XBTUSDCM", "20260917"], cwd=ROOT,
                   capture_output=True, creationflags=NOWIN)
say("edges XBTUSDCM: " + r.stdout.decode("utf-8", "replace").strip()[-200:] + r.stderr.decode("utf-8", "replace").strip()[-300:])
for h0 in (0, 6, 12, 18):
    while psutil.virtual_memory().available < 800 * 2**20:
        time.sleep(15)
    procs.append((("BTC-USDC", h0), start("BTC-USDC", "20260918", h0, h0 + 6, TAG["BTC-USDC"], dict(AS_LOAD_EDGES_JSON=EDGES))))
    say("start BTC-USDC 0918 %02d" % h0)
    time.sleep(5)
for j, p in procs:
    p.wait()
    say("done %s code=%s" % (j, p.returncode))
say("ALL_DONE")
