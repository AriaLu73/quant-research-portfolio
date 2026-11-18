#!/usr/bin/env python3
"""research3:冻结版 MM-UH(strategies/research5/versions/mm_uh_s2d.py,不改)在全部已有 BTC-USDC 数据上的全天回测,一天一个结果集。
用户 2026-10-01:"接下来用所有有的数据跑回测,跑完一天报告一次"。口径同 research5/run_hours.py 默认:队首排队、1.8 ms、clip $5,000。
每天 = 24 个一小时切片(data/oos/ku_buy/<day>_<hh>),标签 ALLs2d_<day> → data/research5/runs/ALLs2d_<day>.json;
跑完一天后做行为审计(logs/r3_ALLs2d_<day>_behaviour.txt)并在日志里写一行 DAYDONE <day>。切片还没生成的日期会等(每 2 分钟看一次)。
用法:python scripts/research3/uh_alldata_chain.py 20260901,20260902,...        (经 detach.py 启动;.venv 的 python)"""
import datetime as dt, json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STRAT = os.path.join("strategies", "research5", "versions", "mm_uh_s2d.py")
PY = sys.executable


def slices_ready(day):
    return all(os.path.exists(os.path.join(ROOT, "data", "oos", "ku_buy", f"{day}_{h:02d}", "kucoin", "swap", s, "feed_raw", f"ticks-{day}.jsonl.gz"))
               for h in (0, 23) for s in ("BTC-USDC", "BTC-USDT"))


def main():
    days = sys.argv[1].split(",")
    for day in days:
        tag = f"ALLs2d_{day}"
        while not slices_ready(day):
            time.sleep(120)
        d0 = dt.datetime.strptime(day, "%Y%m%d")
        man = [[f"ku_buy/{day}_{h:02d}", "BTC-USDC", (d0 + dt.timedelta(hours=h)).isoformat(), (d0 + dt.timedelta(hours=h + 1)).isoformat()] for h in range(24)]
        mp = os.path.join("data", "research3", "uh_val", f"manifest_{day}.json")
        os.makedirs(os.path.join(ROOT, os.path.dirname(mp)), exist_ok=True)
        json.dump(man, open(os.path.join(ROOT, mp), "w", encoding="utf-8"))
        subprocess.run([PY, os.path.join("scripts", "research5", "run_hours.py"), "--tag", tag, "--strategy", STRAT, "--params", "{}", "--manifest", mp], cwd=ROOT, check=False)
        with open(os.path.join(ROOT, "logs", f"r3_{tag}_behaviour.txt"), "w", encoding="utf-8") as fh:
            subprocess.run([PY, os.path.join("scripts", "research5", "behaviour_audit.py"), tag], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, check=False,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
        print("DAYDONE", day, time.strftime("%F %T"), flush=True)
    print("CHAINDONE", flush=True)


if __name__ == "__main__":
    main()
