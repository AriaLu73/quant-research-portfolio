#!/usr/bin/env python3
"""Read-only: for every recorded BTC-USDT L3 hour (data/research5/usdc_pairs_l3usdt), what else was saved for the same
contract and hour? 2026-10-28 用户:"一小时数据时,有没有同时保存过 L3 初始快照,或者独立的 L2 最优买卖价数据"。

KuCoin publishes no L3 snapshot; the L3 recorder runs with --l2 none. A separate recorder (data/research5/usdc_pairs)
saves XBTUSDTM level2 increments, public trades and REST L2 snapshots (1000 levels per side, every 5 min and after each
reconnect). Per L3 hour this reports: which of those files exist, number of REST snapshots and how long after the hour
start the first one was taken, and the level2 file's coverage (first / last exchange ms inside the hour, silences > 5 s,
sequence gaps), all in exchange time.
Usage: .venv/Scripts/python.exe scripts/research5/l3_companion_check.py --from 20261013 --to 20261028 --upto 2026102812
"""
import argparse, calendar, csv, glob, gzip, os, sys, time, zlib
from multiprocessing import Pool
import orjson

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L3 = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt")
L2 = os.path.join(ROOT, "data", "research5", "usdc_pairs")
FIELDS = ["hour", "l2_file", "snap_file", "trades_file", "snaps", "first_snap_after_min", "snap_levels",
          "l2_msgs", "l2_covered_min", "l2_silences_5s", "l2_max_silence_s", "l2_seq_gaps", "l2_truncated"]


def below_normal():
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)       # 用户在这台机器打游戏
    except Exception:
        pass


def lines(path):
    with gzip.open(path, "rb") as fh:
        for ln in fh:
            i = ln.find(b"\t")
            if i > 0: yield orjson.loads(ln[i + 1:])


def check(key):
    day, hh = key
    h0 = calendar.timegm(time.strptime(day + hh, "%Y%m%d%H")) * 1000
    base = os.path.join(L2, day, f"{hh}_XBTUSDTM_")
    r = dict.fromkeys(FIELDS, 0); r["hour"] = f"{day}-{hh}"
    for k, suf in (("l2_file", "l2"), ("snap_file", "snap"), ("trades_file", "trades")):
        r[k] = int(os.path.exists(base + suf + ".jsonl.gz"))
    r["first_snap_after_min"] = ""
    if r["snap_file"]:
        first = None
        try:
            for o in lines(base + "snap.jsonl.gz"):
                d = o.get("data") or {}
                if o.get("code") != "200000" or "ts" not in d: continue
                ts = d["ts"] // 1_000_000
                if not h0 <= ts < h0 + 3_600_000: continue
                r["snaps"] += 1; r["snap_levels"] = max(r["snap_levels"], len(d.get("bids", [])), len(d.get("asks", [])))
                first = ts if first is None else min(first, ts)
        except (EOFError, OSError, zlib.error):
            pass
        if first is not None: r["first_snap_after_min"] = round((first - h0) / 60000, 1)
    if r["l2_file"]:
        first = last = prev = seq = None
        try:
            for o in lines(base + "l2.jsonl.gz"):
                d = o.get("data")
                if not d or "timestamp" not in d: continue
                ts = d["timestamp"]; r["l2_msgs"] += 1
                if seq is not None and d["sequence"] > seq + 1: r["l2_seq_gaps"] += 1
                seq = d["sequence"] if seq is None or d["sequence"] > seq else seq
                if not h0 <= ts < h0 + 3_600_000: continue
                if prev is not None and ts - prev > 5000:
                    r["l2_silences_5s"] += 1; r["l2_max_silence_s"] = max(r["l2_max_silence_s"], round((ts - prev) / 1000, 1))
                first = ts if first is None else first; last = ts; prev = ts if prev is None or ts > prev else prev
        except (EOFError, OSError, zlib.error):
            r["l2_truncated"] = 1
        if first is not None: r["l2_covered_min"] = round((last - first) / 60000, 1)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", required=True); ap.add_argument("--to", dest="d1", required=True)
    ap.add_argument("--upto", default="9999999999"); ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    keys = []
    for f in sorted(glob.glob(os.path.join(L3, "*", "*_XBTUSDTM_l3.jsonl.gz"))):
        day, hh = os.path.basename(os.path.dirname(f)), os.path.basename(f)[:2]
        if a.d0 <= day <= a.d1 and day + hh <= a.upto: keys.append((day, hh))
    with Pool(a.workers, initializer=below_normal) as pool:
        rows = list(pool.imap(check, keys))
    out = os.path.join(ROOT, "data", "research5", f"l3_companion_btc_{a.d0}_{a.d1}.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, FIELDS); w.writeheader(); w.writerows(rows)
    n = len(rows); s = lambda k: sum(1 for r in rows if r[k])
    print(f"{n} L3 hours -> {out}")
    print(f"same-hour files: level2 {s('l2_file')}, REST snapshot {s('snap_file')}, trades {s('trades_file')}")
    snaps = sorted(r["snaps"] for r in rows)
    fs = sorted(r["first_snap_after_min"] for r in rows if r["first_snap_after_min"] != "")
    print(f"REST snapshots per hour: min {snaps[0]}, median {snaps[n // 2]}, max {snaps[-1]}; hours with none: {sum(1 for x in snaps if not x)};"
          f" levels per side {max(r['snap_levels'] for r in rows)}; first snapshot after hour start: median {fs[len(fs) // 2]} min, max {fs[-1]} min")
    cov = [r for r in rows if r["l2_file"]]
    print(f"level2 coverage: hours < 55 min covered {sum(1 for r in cov if r['l2_covered_min'] < 55)};"
          f" silences > 5 s {sum(r['l2_silences_5s'] for r in cov)} in {sum(1 for r in cov if r['l2_silences_5s'])} hours;"
          f" sequence gaps {sum(r['l2_seq_gaps'] for r in cov)} in {sum(1 for r in cov if r['l2_seq_gaps'])} hours; truncated {s('l2_truncated')}")
    for r in rows:
        if not r["l2_file"] or not r["snaps"] or r["l2_covered_min"] < 55 or r["l2_seq_gaps"] or r["l2_truncated"]:
            print("  ", {k: r[k] for k in FIELDS if r[k] not in (0, "")})


if __name__ == "__main__":
    sys.exit(main())
