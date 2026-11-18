#!/usr/bin/env python3
"""research3:任一冻结策略文件在某个 USDC 合约上的全天回测,一天一个结果集 <prefix>_<day>(data/research5/runs/)。
每个品种一个子账户(限频各自独立),所以各品种分开跑、事后用 uh_portfolio_report.py 相加。
用法:python uh_sym_chain.py <prefix> <策略文件> <params.json 路径> <品种,如 XRP-USDC> day1,day2,...   (.venv 的 python,经 detach.py)
口径同 research5/run_hours.py 默认:队首排队、1.8 ms。每天跑完做行为审计并写一行 DAYDONE。"""
import datetime as dt, json, os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
prefix, STRAT, params, SYM, days = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5].split(",")
FEED = sys.argv[6] if len(sys.argv) > 6 else "ku_buyc"            # 清洗后的切片(clean_buy_slices.py);旧的带过期档位的是 ku_buy
for day in days:
    tag = f"{prefix}_{day}"
    d0 = dt.datetime.strptime(day, "%Y%m%d")
    man = [[f"{FEED}/{day}_{h:02d}", SYM, (d0 + dt.timedelta(hours=h)).isoformat(), (d0 + dt.timedelta(hours=h + 1)).isoformat()] for h in range(24)]
    mp = os.path.join("data", "research3", "uh_val", f"manifest_{FEED}_{SYM}_{day}.json")
    json.dump(man, open(os.path.join(ROOT, mp), "w", encoding="utf-8"))
    subprocess.run([sys.executable, os.path.join("scripts", "research5", "run_hours.py"), "--tag", tag, "--strategy", STRAT, "--params", params, "--manifest", mp], cwd=ROOT, check=False)
    with open(os.path.join(ROOT, "logs", f"r3_{tag}_behaviour.txt"), "w", encoding="utf-8") as fh:
        subprocess.run([sys.executable, os.path.join("scripts", "research5", "behaviour_audit.py"), tag], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, check=False,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
    print("DAYDONE", day, time.strftime("%F %T"), flush=True)
print("CHAINDONE", flush=True)
