#!/usr/bin/env python3
"""Read-only quality sweep of the self-recorded BTC-USDT level3v2 hour files (data/research5/usdc_pairs_l3usdt).
2026-10-28 用户:"数据质量怎么样"——对 10-13…10-28 上传到 GitHub 的 248 个小时文件逐个检查。

Per file: truncated gzip, reconnects, sequence gaps split into
  internal  = one missing number right after a match and right before done(filled) (exchange-internal, not lost; see
              docs/research5/experiments.md 2026-10-06 数据完整性核对)
  lost      = every other gap (messages really missing)
exchange-time regressions, broken life cycles of orders created inside the file (creation ms = orderId >> 22 + offset), covered minutes
(first..last exchange ts inside the hour) and silences > 2 s (BTC L3 normally has thousands of messages per second).
Usage: .venv/Scripts/python.exe scripts/research5/l3_quality_sweep.py --from 20261013 --to 20261028 --upto 2026102812
Writes data/research5/l3_quality_btc_<from>_<to>.csv and prints a summary.
"""
import argparse, csv, glob, gzip, os, sys, zlib
from multiprocessing import Pool
import orjson

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt")
FIELDS = ["file", "msgs", "truncated", "reconnects", "gaps_internal", "gaps_lost", "msgs_lost", "max_lost_run",
          "ts_back", "max_back_ms", "open_wo_recv", "match_maker_unknown", "done_wo_recv", "covered_min",
          "silences_2s", "silence_s_total", "max_silence_s"]


def below_normal():
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)       # 用户在这台机器打游戏
    except Exception:
        pass


def audit(path):
    r = dict.fromkeys(FIELDS, 0); r["file"] = os.path.relpath(path, SRC).replace("\\", "/")
    day, hh = r["file"].split("/")[0], int(r["file"].split("/")[1][:2])
    import calendar, time
    h0 = calendar.timegm(time.strptime(day + f"{hh:02d}", "%Y%m%d%H")) * 1000
    last_sn = last_ts = prev_subj = None
    received, opened = set(), set(); off = None; born_after = None   # 订单号高位 = 创建毫秒(另有固定偏移,从 received 求)
    first_ts = last_ts_in_hour = None; prev_t = None
    try:
        with gzip.open(path, "rb") as fh:
            for line in fh:
                i = line.find(b"\t")
                if i <= 0: continue
                m = orjson.loads(line[i + 1:])
                if "_marker" in m:
                    if m["_marker"].get("event") == "connect": r["reconnects"] += 1; last_sn = None
                    continue
                d = m.get("data"); s = m.get("subject")
                if not d or not s: continue
                r["msgs"] += 1
                ts = int(d["ts"]) // 1_000_000; sn = d.get("sequence", m.get("sn"))
                if sn is not None and last_sn is not None and sn > last_sn + 1:
                    gap = sn - last_sn - 1                             # 单个缺号:缺口前是 match、缺口后是 done filled → 内部序号
                    if gap == 1 and prev_subj == "match" and s == "done" and d.get("reason") == "filled":
                        r["gaps_internal"] += 1
                    else:
                        r["gaps_lost"] += 1; r["msgs_lost"] += gap; r["max_lost_run"] = max(r["max_lost_run"], gap)
                if sn is not None and (last_sn is None or sn > last_sn): last_sn = sn
                if last_ts is not None and ts < last_ts:
                    r["ts_back"] += 1; r["max_back_ms"] = max(r["max_back_ms"], last_ts - ts)
                else:
                    last_ts = ts
                if h0 <= ts < h0 + 3_600_000:
                    if first_ts is None: first_ts = ts
                    last_ts_in_hour = ts
                    if prev_t is not None and ts - prev_t > 2000:
                        r["silences_2s"] += 1; r["silence_s_total"] += (ts - prev_t) / 1000
                        r["max_silence_s"] = max(r["max_silence_s"], (ts - prev_t) / 1000)
                    prev_t = ts if prev_t is None or ts > prev_t else prev_t
                oid = d.get("orderId")
                if s == "received":
                    received.add(oid)
                    if off is None and oid: off = ts - (int(oid) >> 22); born_after = ts + 2000
                new = lambda o: off is not None and o and o.isdigit() and (int(o) >> 22) + off > born_after
                if s == "open":                                        # 只算文件开始 2 秒后才创建的订单,之前就挂着的不算错
                    if oid not in received and new(oid): r["open_wo_recv"] += 1
                    opened.add(oid)
                elif s == "match":
                    mk = d.get("makerOrderId")
                    if mk not in opened and new(mk): r["match_maker_unknown"] += 1
                elif s == "done":
                    if oid not in received and new(oid): r["done_wo_recv"] += 1
                    received.discard(oid); opened.discard(oid)
                prev_subj = s
    except (EOFError, OSError, zlib.error):
        r["truncated"] = 1                                                # 没有 gzip 结束标记 / 中间损坏,读到这里为止
    if first_ts is not None: r["covered_min"] = round((last_ts_in_hour - first_ts) / 60000, 1)
    r["silence_s_total"] = round(r["silence_s_total"], 1); r["max_silence_s"] = round(r["max_silence_s"], 1)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", required=True); ap.add_argument("--to", dest="d1", required=True)
    ap.add_argument("--upto", default="9999999999", help="last YYYYMMDDHH to include (skip the hour still being written)")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    files = []
    for f in sorted(glob.glob(os.path.join(SRC, "*", "*_XBTUSDTM_l3.jsonl.gz"))):
        day = os.path.basename(os.path.dirname(f)); hh = os.path.basename(f)[:2]
        if a.d0 <= day <= a.d1 and day + hh <= a.upto: files.append(f)
    print(f"{len(files)} files", flush=True)
    out = os.path.join(ROOT, "data", "research5", f"l3_quality_btc_{a.d0}_{a.d1}.csv")
    rows = []
    with Pool(a.workers, initializer=below_normal) as pool:
        for r in pool.imap(audit, files):
            rows.append(r); print(r["file"], {k: r[k] for k in FIELDS[1:] if r[k]}, flush=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, FIELDS); w.writeheader(); w.writerows(rows)
    tot = lambda k: sum(r[k] for r in rows)
    print("== summary", len(rows), "files ->", out)
    print("messages", tot("msgs"), "| truncated files", tot("truncated"), "| reconnects", tot("reconnects"))
    print("gaps internal", tot("gaps_internal"), "| gaps lost", tot("gaps_lost"), "messages lost", tot("msgs_lost"),
          f"({tot('msgs_lost') / max(1, tot('msgs')):.2e} of messages)", "| files with lost gaps", sum(1 for r in rows if r["gaps_lost"]))
    print("ts regressions", tot("ts_back"), "max", max((r["max_back_ms"] for r in rows), default=0), "ms")
    print("life-cycle breaks: open w/o received", tot("open_wo_recv"), "| match maker unknown", tot("match_maker_unknown"),
          "| done w/o received", tot("done_wo_recv"))
    cov = sorted(r["covered_min"] for r in rows)
    print("covered minutes per file: <55 min:", sum(1 for c in cov if c < 55), "files; total covered hours",
          round(sum(cov) / 60, 1), "| silences > 2 s", tot("silences_2s"), "total", round(tot("silence_s_total") / 60, 1), "min")


if __name__ == "__main__":
    sys.exit(main())
