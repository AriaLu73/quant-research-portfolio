#!/usr/bin/env python3
"""参数冻结后抽取 5 个互不重叠、相互独立的随机 1 小时 OOS 切片(prompt §20/§24)。

池:OOS 池日(2026-06-01、2026-07-01、2026-08-01)× 24 小时,剔除 Data Audit 标记小时;
固定随机种子;抽样后写入 data/research/oos_slices_<version>.json 并记录 seed/slice_start/slice_end/exchange/symbol。
一旦生成即固定,策略修改后必须用新的 version 名(生成新的独立集合)。
"""
import argparse
import json
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POOL_DAYS = ["20260601", "20260701", "20260801"]
FLAGGED = {"20260701_18", "20260801_13"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--n", type=int, default=5)
    ns = ap.parse_args()
    out = os.path.join(ROOT, "data", "research", f"oos_slices_{ns.version}.json")
    if os.path.exists(out):
        raise SystemExit(f"{out} 已存在:同一版本的 OOS 集合一旦生成即固定,禁止重抽")
    pool = [f"{d}_{h:02d}" for d in POOL_DAYS for h in range(24) if f"{d}_{h:02d}" not in FLAGGED]
    rng = random.Random(ns.seed)
    pick = sorted(rng.sample(pool, ns.n))
    rows = []
    for p in pick:
        d, h = p.split("_")
        s = f"{d[:4]}-{d[4:6]}-{d[6:]}T{int(h):02d}:00:00"
        e = f"{d[:4]}-{d[4:6]}-{d[6:]}T{int(h) + 1:02d}:00:00" if int(h) < 23 else None
        if e is None:
            import datetime as dt
            e = (dt.datetime.strptime(d, "%Y%m%d") + dt.timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
        rows.append([f"ku_td/{p}", "BTC-USDT", s, e])
    meta = {"version": ns.version, "seed": ns.seed, "pool_size": len(pool), "exchange": "kucoin", "symbol": "BTC-USDT (XBTUSDTM)",
            "slices": [{"dataset_id": f"ku_{p}", "slice_start": r[2], "slice_end": r[3]} for p, r in zip(pick, rows)],
            "manifest": rows}
    json.dump(meta, open(out, "w", encoding="utf-8"), indent=1)
    json.dump(rows, open(out.replace(".json", "_manifest.json"), "w", encoding="utf-8"), indent=0)
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
