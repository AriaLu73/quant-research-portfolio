"""XBTUSDTM 后续链(用户 11-06 裁决照跑):等提取与 V_LO 两条流水线 ALL_DONE → Step 1 验证 → Step 2–4 批跑(V_LO 取 reports/step00/vlo_XBTUSDTM.json 中位数)
→ Step 2–4 报告 → 实验 A、B、C(1 s)。全部顺序执行,日志 logs/xbtusdtm_followup.log。
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
PY = sys.executable
LOGS = os.path.join(REPRO, "logs")
SYM = "XBTUSDTM"


def wait_for(log, token="ALL_DONE"):
    p = os.path.join(LOGS, log)
    while not (os.path.exists(p) and token in open(p, encoding="utf-8", errors="replace").read()):
        print(f"waiting {log}", flush=True)
        time.sleep(120)


def run(args):
    print(">>", " ".join(args), flush=True)
    r = subprocess.run([PY] + args, cwd=REPRO)
    print("rc", r.returncode, flush=True)
    return r.returncode


if __name__ == "__main__":
    start = sys.argv[sys.argv.index("--from") + 1] if "--from" in sys.argv else "extract"   # 续跑起点:extract | expA
    if start == "extract":
        wait_for("step01_extract_XBTUSDTM.log")
        wait_for("step00_vlo_XBTUSDTM.log")
    vlo = json.load(open(os.path.join(REPRO, "reports", "step00", f"vlo_{SYM}.json"), encoding="utf-8"))["V_LO"]["x1"]
    print("V_LO", vlo, flush=True)
    if start == "extract":
        run([os.path.join(HERE, "step01_validate.py"), SYM, "100,250,500,1000,2000"])
        run([os.path.join(HERE, "step0204_chain.py"), SYM, str(vlo), "1000,100,250,500,2000"])
        run([os.path.join(HERE, "step0204_report.py"), SYM, str(vlo), "--figday", "20261016"])
    run([os.path.join(HERE, "run_expA.py"), SYM, str(vlo), "1000"])
    run([os.path.join(HERE, "run_expB.py"), SYM, str(vlo), "1000"])
    run([os.path.join(HERE, "run_expA.py"), SYM, str(vlo), "1000", "--variant", "det"])
    run([os.path.join(HERE, "step11_report.py"), SYM, "1000"])
    print("FOLLOWUP_DONE", flush=True)
