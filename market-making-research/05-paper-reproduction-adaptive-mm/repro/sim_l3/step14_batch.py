"""Step 14 批跑:等 Step 13 给出 γ*(reports/step13/gamma_scan_<sym>_dt1000.md)与全部测试日的 P2 目录 → 每个测试日整天 l3sim 回放(1.8 / 3.8 ms)
→ 9 月三天自录 L3(附录第 5 条,单独一列,用 10-13 的目录作报价序列,EC-44)→ Table 10 / Figure 8。
用法  python step14_batch.py <sym> <V_LO>
"""
import datetime as dt
import glob
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
PY = sys.executable
SEPT = {"XBTUSDTM": [("20260922", r"data\kucoin_l3"), ("20260924", r"data\kucoin_l3_btc"), ("20260925", r"data\kucoin_l3_btc")],
        "XBTUSDCM": [("20260922", r"data\kucoin_l3"), ("20260924", r"data\kucoin_l3_btc"), ("20260925", r"data\kucoin_l3_btc")]}


def gamma_star(sym):
    p = os.path.join(REPRO, "reports", "step13", f"gamma_scan_{sym}_dt1000.md")
    while not os.path.exists(p):
        print("waiting gamma scan", flush=True); time.sleep(300)
    m = re.search(r"γ\* = ([0-9.e+-]+)", open(p, encoding="utf-8").read())
    return float(m.group(1))


def wait_catalog(sym, day, g, V_LO):
    p = os.path.join(REPRO, "data", "step13", sym, "dt1000", f"{day}_g{g:g}_e{V_LO:g}.npz")
    while not os.path.exists(p):
        print("waiting", p, flush=True); time.sleep(300)
    time.sleep(5)


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    g = gamma_star(sym)
    print("gamma*", g, flush=True)
    days = sorted({os.path.basename(p)[:8] for p in glob.glob(os.path.join(REPRO, "data", "step01", sym, "202610*.npz"))})
    for d in days:
        wait_catalog(sym, d, g, V_LO)
        subprocess.run([PY, os.path.join(HERE, "step14_run.py"), sym, str(V_LO), d, "--gamma", f"{g:g}"], cwd=REPRO)
    subprocess.run([PY, os.path.join(HERE, "step14_report.py"), sym, str(V_LO), "--gamma", f"{g:g}"], cwd=REPRO)
    print("STEP14_DONE", flush=True)
