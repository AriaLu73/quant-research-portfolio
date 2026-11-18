#!/usr/bin/env python3
"""依次跑 H-W 的几个口径(环境变量传给子进程):fr=只跟罕见量;H=存活 ms;cap=库存上限 $。"""
import glob, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tags = sorted({os.path.basename(p).split("-")[1] for d in ("tardis_kualt", "tardis_kualt2") for p in glob.glob(os.path.join(ROOT, "data", d, "quotes-ku_*-*.csv.gz"))})
days = "20251001,20260101,20260401,20260601,20260701,20260801,20260901"
for name, fr, h, cap in (("_fr_h20", "0.005", "20", "3000"), ("_fr_h3", "0.005", "3", "3000"), ("_fr_h3_cap1k", "0.005", "3", "1000")):
    env = dict(os.environ, PI_FR=fr, PI_H_MS=h, PI_CAP_USD=cap)
    print("== variant", name, flush=True)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "research3", "pair_intercept_sim.py"), "--syms", ",".join(tags), "--days", days, "--L", "1,2", "--phi", "0",
                    "--workers", "6", "--tag", name], env=env, cwd=ROOT, stdout=subprocess.DEVNULL)
print("ALL DONE", flush=True)
