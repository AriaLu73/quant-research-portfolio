#!/usr/bin/env python3
"""Data Audit + L1/top-5 状态抽取(KuCoin 永续 XBTUSDTM,Tardis 原始 L2 增量 + 逐笔成交)。

单遍扫描原始 CSV,全程维护完整订单簿(整数 tick 价位),输出:
  data/research/kucoin/l1_<day>.parquet     L1 变化事件(或 100ms 心跳)时的 top-5 状态
  data/research/kucoin/trades_<day>.parquet 逐笔成交(交易所事件时间)
  data/research/kucoin/audit_<day>.json     Data Audit 指标(缺失/重复/乱序/交叉/锁定/陈旧/非法值)
时间轴:交易所事件时间 timestamp(us)。张 -> BTC:x0.001(XBTUSDTM 合约乘数)。
用法:python scripts/research/extract_kucoin_tardis.py --days 20251001,... --workers 6
"""
import argparse
import json
import os
import time
from array import array
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research", "kucoin")
TICK = 0.1
MULT = 0.001          # 张 -> BTC
NLEV = 5
HEARTBEAT_US = 100_000
CHUNK = 2_000_000


def process_day(day: str) -> str:
    t0 = time.time()
    book_path = os.path.join(ROOT, "data", "tardis_kucoin", f"book-{day}.csv.gz")
    trades_path = os.path.join(ROOT, "data", "tardis_kucoin", f"trades-{day}.csv.gz")
    bids: dict = {}
    asks: dict = {}
    st = {"bb": -1, "ba": 1 << 60}
    au = dict(rows=0, frames=0, snapshot_blocks=0, ts_backward_frames=0, max_backward_us=0,
              gap_gt_1s=0, gap_gt_5s=0, max_gap_us=0, bad_price=0, neg_amount=0,
              crossed_frames=0, crossed_us=0, locked_frames=0, empty_side_frames=0,
              dup_rows_in_frame=0, hour_frames=[0] * 24, hour_l1_changes=[0] * 24,
              hour_crossed_us=[0] * 24, hour_max_gap_us=[0] * 24, first_ts=None, last_ts=None)
    lat_samples = []
    cols = {"ts": array("q")}
    for k in ("bb", "ba", "bp5", "ap5"):
        cols[k] = array("d")
    for k in range(NLEV):
        cols[f"bq{k+1}"] = array("d")
        cols[f"aq{k+1}"] = array("d")
    em = {"key": (-1, -1, -1.0, -1.0), "ts": -10**18, "crossed_since": -1}
    prev = {"ts": -1, "snap": False}
    frame_seen = set()

    def finish_frame(ts):
        au["frames"] += 1
        h = int((ts // 1_000_000) % 86400 // 3600)
        au["hour_frames"][h] += 1
        if not bids or not asks:
            au["empty_side_frames"] += 1
            return
        bb = st["bb"]
        ba = st["ba"]
        if bb >= ba:
            if bb == ba:
                au["locked_frames"] += 1
            else:
                au["crossed_frames"] += 1
            if em["crossed_since"] < 0:
                em["crossed_since"] = ts
        elif em["crossed_since"] >= 0:
            d = ts - em["crossed_since"]
            au["crossed_us"] += d
            au["hour_crossed_us"][h] += d
            em["crossed_since"] = -1
        bq = []
        p = bb
        steps = 0
        bp5 = bb
        while len(bq) < NLEV and steps < 60:
            q = bids.get(p)
            if q:
                bq.append(q)
                bp5 = p
            p -= 1
            steps += 1
        aq = []
        p = ba
        steps = 0
        ap5 = ba
        while len(aq) < NLEV and steps < 60:
            q = asks.get(p)
            if q:
                aq.append(q)
                ap5 = p
            p += 1
            steps += 1
        while len(bq) < NLEV:
            bq.append(0.0)
        while len(aq) < NLEV:
            aq.append(0.0)
        key = (bb, ba, bq[0], aq[0])
        if key != em["key"] or ts - em["ts"] >= HEARTBEAT_US:
            if key != em["key"]:
                au["hour_l1_changes"][h] += 1
            em["key"] = key
            em["ts"] = ts
            cols["ts"].append(ts)
            cols["bb"].append(bb * TICK)
            cols["ba"].append(ba * TICK)
            cols["bp5"].append(bp5 * TICK)
            cols["ap5"].append(ap5 * TICK)
            for k in range(NLEV):
                cols[f"bq{k+1}"].append(bq[k] * MULT)
                cols[f"aq{k+1}"].append(aq[k] * MULT)

    reader = pd.read_csv(book_path, chunksize=CHUNK,
                         usecols=["timestamp", "local_timestamp", "is_snapshot", "side", "price", "amount"],
                         dtype={"timestamp": "int64", "local_timestamp": "int64", "is_snapshot": "str",
                                "side": "str", "price": "float64", "amount": "float64"})
    for chunk in reader:
        ts_a = chunk["timestamp"].values
        loc_a = chunk["local_timestamp"].values
        snap_a = (chunk["is_snapshot"].values == "true")
        side_a = (chunk["side"].values == "bid")
        px_a = chunk["price"].values
        am_a = chunk["amount"].values
        n = len(ts_a)
        au["rows"] += n
        lat_samples.extend((loc_a[::5000] - ts_a[::5000]).tolist())
        for i in range(n):
            ts = int(ts_a[i])
            snap = bool(snap_a[i])
            if ts != prev["ts"]:
                if prev["ts"] >= 0:
                    finish_frame(prev["ts"])
                    if ts < prev["ts"]:
                        au["ts_backward_frames"] += 1
                        au["max_backward_us"] = max(au["max_backward_us"], prev["ts"] - ts)
                    else:
                        g = ts - prev["ts"]
                        if g > au["max_gap_us"]:
                            au["max_gap_us"] = g
                        hh = int((prev["ts"] // 1_000_000) % 86400 // 3600)
                        if g > au["hour_max_gap_us"][hh]:
                            au["hour_max_gap_us"][hh] = g
                        if g > 1_000_000:
                            au["gap_gt_1s"] += 1
                        if g > 5_000_000:
                            au["gap_gt_5s"] += 1
                else:
                    au["first_ts"] = ts
                prev["ts"] = ts
                frame_seen.clear()
            if snap and not prev["snap"]:
                au["snapshot_blocks"] += 1
                bids.clear()
                asks.clear()
                st["bb"] = -1
                st["ba"] = 1 << 60
            prev["snap"] = snap
            px = px_a[i]
            am = am_a[i]
            if not (px > 0):
                au["bad_price"] += 1
                continue
            if am < 0:
                au["neg_amount"] += 1
                continue
            pt = int(round(px / TICK))
            fk = (side_a[i], pt)
            if fk in frame_seen:
                au["dup_rows_in_frame"] += 1
            frame_seen.add(fk)
            if side_a[i]:
                if am > 0:
                    bids[pt] = am
                    if pt > st["bb"]:
                        st["bb"] = pt
                else:
                    if bids.pop(pt, None) is not None and pt == st["bb"]:
                        st["bb"] = max(bids) if bids else -1
            else:
                if am > 0:
                    asks[pt] = am
                    if pt < st["ba"]:
                        st["ba"] = pt
                else:
                    if asks.pop(pt, None) is not None and pt == st["ba"]:
                        st["ba"] = min(asks) if asks else (1 << 60)
    if prev["ts"] >= 0:
        finish_frame(prev["ts"])
    au["last_ts"] = prev["ts"]
    tbl = pa.table({k: np.frombuffer(v, dtype=np.int64 if k == "ts" else np.float64)
                    for k, v in cols.items()})
    pq.write_table(tbl, os.path.join(OUT, f"l1_{day}.parquet"), compression="zstd")
    # trades
    tr = pd.read_csv(trades_path, usecols=["timestamp", "local_timestamp", "id", "side", "price", "amount"])
    lat_t = (tr["local_timestamp"] - tr["timestamp"]).values
    tau = dict(rows=int(len(tr)), dup_ids=int(tr["id"].duplicated().sum()),
               ts_backward=int((tr["timestamp"].diff() < 0).sum()),
               bad_price=int((~(tr["price"] > 0)).sum()), bad_amount=int((~(tr["amount"] > 0)).sum()),
               hour_trades=[int(x) for x in np.bincount(((tr["timestamp"] // 1_000_000) % 86400 // 3600).astype(int), minlength=24)],
               lat_p50_us=float(np.percentile(lat_t, 50)), lat_p99_us=float(np.percentile(lat_t, 99)))
    tr = tr[(tr["price"] > 0) & (tr["amount"] > 0)].drop_duplicates("id").sort_values("timestamp", kind="stable")
    pq.write_table(pa.table({"ts": tr["timestamp"].values.astype(np.int64),
                             "side": np.where(tr["side"].values == "buy", 1, -1).astype(np.int8),
                             "price": tr["price"].values.astype(np.float64),
                             "qty": (tr["amount"].values * MULT).astype(np.float64),
                             "tid": tr["id"].values.astype(np.int64)}),
                   os.path.join(OUT, f"trades_{day}.parquet"), compression="zstd")
    lat = np.array(lat_samples)
    au["book_lat_p50_us"] = float(np.percentile(lat, 50)) if len(lat) else None
    au["book_lat_p99_us"] = float(np.percentile(lat, 99)) if len(lat) else None
    au["l1_rows_out"] = len(cols["ts"])
    au["trades"] = tau
    au["elapsed_s"] = round(time.time() - t0)
    json.dump(au, open(os.path.join(OUT, f"audit_{day}.json"), "w"), indent=1)
    return (f"{day}: rows {au['rows']:,} frames {au['frames']:,} l1_rows {au['l1_rows_out']:,} "
            f"trades {tau['rows']:,} {au['elapsed_s']}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="20251001,20260101,20260401,20260601,20260701,20260801")
    ap.add_argument("--workers", type=int, default=6)
    ns = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    days = ns.days.split(",")
    with ProcessPoolExecutor(ns.workers) as ex:
        for line in ex.map(process_day, days):
            print(line, flush=True)


if __name__ == "__main__":
    main()
