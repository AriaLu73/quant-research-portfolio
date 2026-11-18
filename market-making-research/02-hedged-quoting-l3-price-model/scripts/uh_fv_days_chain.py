#!/usr/bin/env python3
"""research3:MM-UH-FV 指定参数的全天回测(一天一个结果集 FVD<label>_<day>),用于把"抽样小时外推"换成全天口径。
用法:python uh_fv_days_chain.py <label> '<params json>' day1,day2,...   (.venv 的 python,经 detach.py)"""
import datetime as dt, json, os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
label, params, days = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
for day in days:
    tag = f"FVD{label}_{day}"
    d0 = dt.datetime.strptime(day, "%Y%m%d")
    man = [[f"ku_buy/{day}_{h:02d}", "BTC-USDC", (d0 + dt.timedelta(hours=h)).isoformat(), (d0 + dt.timedelta(hours=h + 1)).isoformat()] for h in range(24)]
    mp = os.path.join("data", "research3", "uh_val", f"manifest_{day}.json")
    json.dump(man, open(os.path.join(ROOT, mp), "w", encoding="utf-8"))
    subprocess.run([sys.executable, os.path.join("scripts", "research5", "run_hours.py"), "--tag", tag, "--strategy", os.path.join("strategies", "research3", "mm_uh_fv.py"),
                    "--params", params, "--manifest", mp], cwd=ROOT, check=False)
    with open(os.path.join(ROOT, "logs", f"r3_{tag}_behaviour.txt"), "w", encoding="utf-8") as fh:
        subprocess.run([sys.executable, os.path.join("scripts", "research5", "behaviour_audit.py"), tag], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, check=False,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
    print("DAYDONE", day, time.strftime("%F %T"), flush=True)
print("CHAINDONE", flush=True)
