#!/usr/bin/env python3
"""等网盘下载:每 60 s 看一次,某个 9 月交易日的全合约盘口下完(无 .downloading、盘口数 ≥ 97% 的成交合约数、3 分钟内无文件变动)就打印并退出;
全部安静 20 分钟(没有任何下载中的文件、没有新文件)也退出。只读。用法:python watch_download.py --done 20260910,20260918"""
import argparse, glob, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buy_paths as BP
SPECS = json.load(open(os.path.join(BP.ROOT, "data", "research2", "kc_contract_specs.json")))
ap = argparse.ArgumentParser(); ap.add_argument("--done", default=""); ap.add_argument("--max-hours", type=float, default=12)
ns = ap.parse_args(); done = set(x for x in ns.done.split(",") if x)
DAYS = [f"202609{d:02d}" for d in range(1, 25)] + [f"202608{d:02d}" for d in range(26, 32)]


def latest_mtime(day):
    m = 0.0
    for dd in BP.day_dirs(day):
        m = max(m, os.path.getmtime(dd))
        for p in glob.glob(os.path.join(dd, "*")):
            try:
                m = max(m, os.path.getmtime(p))
            except OSError:
                pass
    return m


def any_downloading():
    return len(glob.glob(os.path.join(BP.DATA, "*", "*downloading"))) + len(glob.glob(os.path.join(BP.DATA, "kucoin-futures", "*", "*", "*", "*", "*downloading")))


t0 = time.time(); last_activity = time.time()
while time.time() - t0 < ns.max_hours * 3600:
    now = time.time(); status = []
    for day in DAYS:
        if day in done:
            continue
        dirs = BP.day_dirs(day)
        if len(dirs) < 2 and not any("kucoin-futures" in d or os.path.basename(d) == day[6:] for d in dirs):
            continue                                    # 只有旧的 14 合约目录,没有新下载
        n_dl = BP.downloading(day); lm = latest_mtime(day)
        if now - lm < 180 or n_dl:
            last_activity = now; status.append(f"{day}: 下载中({n_dl} 个进行中)"); continue
        exp = sum(1 for p in glob.glob(os.path.join(BP.DATA, "trades", day[:4], day[4:6], day[6:], "*.csv.gz")) if os.path.basename(p)[:-7] in SPECS)
        n = len(BP.symbols(day))
        if exp and n >= 0.97 * exp:
            print(f"COMPLETE {day} books {n}/{exp}", flush=True); sys.exit(0)
        status.append(f"{day}: 不完整 {n}/{exp}(已停止变动)")
    if any_downloading():
        last_activity = now
    if now - last_activity > 1200:
        print("QUIET 20 分钟无下载活动;" + ";".join(status), flush=True); sys.exit(0)
    time.sleep(60)
print("TIMEOUT", flush=True)
