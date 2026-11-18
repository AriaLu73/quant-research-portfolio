#!/usr/bin/env python3
"""H-W 保守口径(罕见量过滤、存活 3 ms、库存上限 $1k)的延迟敏感性:L = 0,3,4,6 ms(1、2 已跑)。"""
import glob, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tags = sorted({os.path.basename(p).split("-")[1] for d in ("tardis_kualt", "tardis_kualt2") for p in glob.glob(os.path.join(ROOT, "data", d, "quotes-ku_*-*.csv.gz"))})
env = dict(os.environ, PI_FR="0.005", PI_H_MS="3", PI_CAP_USD="1000")
subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "research3", "pair_intercept_sim.py"), "--syms", ",".join(tags),
                "--days", "20251001,20260101,20260401,20260601,20260701,20260801,20260901", "--L", "0,3,4,6", "--phi", "0", "--workers", "6", "--tag", "_fr_h3_cap1k_lat"],
               env=env, cwd=ROOT, stdout=subprocess.DEVNULL)
print("ALL DONE", flush=True)
