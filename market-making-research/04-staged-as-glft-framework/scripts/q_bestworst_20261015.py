#!/usr/bin/env python3
"""排队对照,只跑最好和最差的一小时(用户 10-15:"我说的最好的和最差的一个小时跑对比")。只在回测环境里跑。
最好 / 最差小时取自十天回测(实盘设定:BTC 实验 E = EXPE,ETH 实验 C + 上限 15 张 = EXPL)每小时盈亏。
队首 queue_cancel_bias 1.0 vs 队尾 0.0;冻结代码 frozen_v7,按小时口径,盘口按回测原规则,50 档,同撮合同种子。"""
import json, os, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
ON = dict(FAST_RETREAT=1, PULL_ON_TOUCH=1, LAT_K=1.0, VETO_BP=0.2, QUOTE_MODEL="as", GAMMA_METHOD="file", INV_ON=1)
CFG = {"BTC-USDT": dict(ON, INV_OVER={"hw_reduce_near": 0, "reduce_exempt": 0}),
       "ETH-USDT": dict(ON, INV_OVER={"pos_cap_lots": 15, "pos_age_s": 0, "hw_halflife_s": 0, "hw_reduce_near": 0, "reduce_exempt": 0})}
HOURS = (("BTC-USDT", "20260828", 14, "最差"), ("BTC-USDT", "20260918", 13, "最好"), ("ETH-USDT", "20260830", 23, "最差"), ("ETH-USDT", "20260924", 14, "最好"))
ps = []
for sym, day, hh, lab in HOURS:
    for qb, tag in (("1.0", "QB1"), ("0.0", "QB0")):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", HFT_BT_VIEW_LEVELS="50", AS_QUEUE_BIAS=qb, AS_CFG=json.dumps(CFG[sym]), AS_TAG="_" + tag)
        log = open(os.path.join(ROOT, "logs", "qc_bt", "bw_%s_%s_%02d_%s.log" % (sym, day, hh, tag)), "w", encoding="utf-8")
        ps.append(subprocess.Popen([PY, "research/as2008/frozen_v7_20261015/as_offline.py", "run", sym, day, str(hh), str(hh + 1), "all4"], cwd=ROOT, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=0x08000000))
for p in ps:
    p.wait()
for sym, day, hh, lab in HOURS:
    for tag, q in (("QB1", "队首"), ("QB0", "队尾")):
        f = os.path.join(ROOT, "data", "research7", "as2008_l3", "run_%s_%s_%02d_%02d_all4_%s.json" % (sym, day, hh, hh + 1, tag))
        if not os.path.exists(f):
            print(sym, day, hh, q, "失败"); continue
        r = json.load(open(f, encoding="utf-8"))["results"]["all4"]
        v = r["volume_usd"]
        print("%s %s %s %02d 时 %s:净 %+.2f,成交 %d 笔,成交额 $%.0f,每成交额 %s bp" % (sym, lab, day, hh, q, r["total"], r["fills"], v, ("%+.2f" % (r["total"] / v * 1e4)) if v else "—"))
