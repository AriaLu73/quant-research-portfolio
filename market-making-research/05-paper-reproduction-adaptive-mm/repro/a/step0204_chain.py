"""顺序跑 step02_batch → step04_batch(同一合约、同一 Δt 列表)。用法 python step0204_chain.py <sym> <V_LO> <dt_list> [step02 其它参数...]"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
sym, vlo, dts = sys.argv[1:4]
extra = sys.argv[4:]
tag = extra[extra.index("--tag") + 1] if "--tag" in extra else "base"
r = subprocess.run([PY, os.path.join(HERE, "step02_batch.py"), sym, vlo, dts] + extra)
print("step02 rc", r.returncode, flush=True)
if r.returncode == 0:
    r = subprocess.run([PY, os.path.join(HERE, "step04_batch.py"), sym, dts, "--tag", tag])
    print("step04 rc", r.returncode, flush=True)
print("CHAIN_DONE", flush=True)
