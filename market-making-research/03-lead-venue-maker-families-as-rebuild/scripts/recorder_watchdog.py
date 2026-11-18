#!/usr/bin/env python3
"""research5: restart a public-data recorder when its output has gone stale.

Why (2026-10-02): the two-venue recorders stopped twice in one afternoon (13:29 and 14:40 UTC) with nothing in their logs;
the cause is unknown. Each stop cost data until someone noticed. This watchdog looks at the newest file under each recorder's
output folder once a minute and relaunches the recorder through scripts/detach.py when nothing was written for STALE_S
seconds. It starts nothing else, sends no orders and touches no existing file; every action is logged.
A recorder that is alive but stuck is NOT killed here: each recorder holds a lock on its folder (a second copy exits at once)
and has its own stall rule (reconnect, or exit so that the next poll starts a fresh one). See rec_common.py.
Stop: create data/research5/WATCHDOG_STOP (the recorders keep running; only the watchdog exits).
The watchdog itself needs only the standard library: run it with Python314 (on 2026-10-02 every .venv process on the
machine disappeared at once, three times; the two Python314 recorders survived each time).
Usage: Python314/python.exe scripts/detach.py --log logs/r5_recorder_watchdog.log -- Python314/python.exe scripts/research5/recorder_watchdog.py
"""
import os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
STOP = os.path.join(ROOT, "data", "research5", "WATCHDOG_STOP")
STALE_S, COOLDOWN_S, POLL_S = 240, 420, 60
ALTS = ("ZECUSDTM,NEARUSDTM,DOGEUSDTM,HYPEUSDTM,PEPEUSDTM,SUIUSDTM,LTCUSDTM,UNIUSDTM,TAOUSDTM,ADAUSDTM,ARBUSDTM,AKEUSDTM,ENAUSDTM,ONDOUSDTM,"
        "LINKUSDTM,XMRUSDTM,ONEUSDTM,PUMPUSDTM,DOTUSDTM,WLDUSDTM,USELESSUSDTM,INJUSDTM")
USDC = "XBTUSDCM,ETHUSDCM,SOLUSDCM,XRPUSDCM,SUIUSDCM"
RECORDERS = (
    dict(name="usdc_pairs", out="data/research5/usdc_pairs", log="logs/r5_usdc_pair_recorder.log",
         cmd=["scripts/research5/usdc_pair_recorder.py", "--hours", "240", "--l3", USDC, "--guard"]),
    dict(name="usdc_pairs_l3usdt", out="data/research5/usdc_pairs_l3usdt", log="logs/r5_usdc_pair_recorder_l3usdt.log",
         cmd=["scripts/research5/usdc_pair_recorder.py", "--hours", "240", "--l3", "XBTUSDTM", "--l2", "none", "--out", "data/research5/usdc_pairs_l3usdt", "--guard"]),
    dict(name="spot_perp", out="data/research5/spot_perp", log="logs/r5_spot_perp_recorder.log",
         cmd=["scripts/research5/spot_perp_recorder.py", "--hours", "240"]),
    dict(name="xvenue_bn", out="data/research5/xvenue_bn", log="logs/r5_xvenue_bn.log",
         cmd=["scripts/research5/binance_bookticker_recorder.py", "--hours", "240"]),
    dict(name="xvenue_ku", out="data/research5/xvenue_ku", log="logs/r5_xvenue_ku.log",
         cmd=["scripts/research5/usdc_pair_recorder.py", "--hours", "240", "--l3", "none", "--l2", ALTS, "--out", "data/research5/xvenue_ku", "--safe"]),
)


def newest_mtime(folder):
    """Modification time of the most recently written data file in the newest day folder under `folder` (0 if none)."""
    try:
        days = sorted(d for d in os.listdir(folder) if d.isdigit() and os.path.isdir(os.path.join(folder, d)))
    except OSError:
        return 0.0
    if not days:
        return 0.0
    best = 0.0
    day = os.path.join(folder, days[-1])
    for name in os.listdir(day):
        try:                                   # os.stat asks the file itself: the times cached in the directory listing
            best = max(best, os.stat(os.path.join(day, name)).st_mtime)   # (os.scandir) lag behind for files that are open for writing
        except OSError:
            continue
    return best


def is_stale(mtime, now, last_start, stale_s=STALE_S, cooldown_s=COOLDOWN_S):
    """Restart only when nothing was written for stale_s and the previous (re)start is at least cooldown_s old."""
    return now - mtime > stale_s and now - last_start > cooldown_s


def main():
    global RECORDERS
    if len(sys.argv) > 1:                                  # 2026-10-13:只看管列出的采集器,例 recorder_watchdog.py usdc_pairs,usdc_pairs_l3usdt
        only = set(sys.argv[1].split(","))
        RECORDERS = tuple(r for r in RECORDERS if r["name"] in only)
    started = {r["name"]: 0.0 for r in RECORDERS}
    print(time.strftime("%F %T"), "watchdog up for", [r["name"] for r in RECORDERS], flush=True)
    while not os.path.exists(STOP):
        now = time.time()
        for r in RECORDERS:
            m = newest_mtime(os.path.join(ROOT, r["out"]))
            if is_stale(m, now, started[r["name"]]):
                print(time.strftime("%F %T"), r["name"], "stale for", int(now - m), "s -> restart", flush=True)
                subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "detach.py"), "--log", os.path.join(ROOT, r["log"]), "--", PY] + r["cmd"],
                               cwd=ROOT, capture_output=True, timeout=120, creationflags=0x08000000)   # 不弹窗口
                started[r["name"]] = now
        time.sleep(POLL_S)
    print(time.strftime("%F %T"), "watchdog stopped by", STOP, flush=True)


if __name__ == "__main__":
    main()
