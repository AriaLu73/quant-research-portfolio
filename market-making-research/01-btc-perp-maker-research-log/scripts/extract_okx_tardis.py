#!/usr/bin/env python3
"""OKX 永续 BTC-USDT-SWAP(Tardis quotes 100ms BBO + trades)-> parquet,供跨所因子研究。"""
import os, sys
import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research", "okx"); os.makedirs(OUT, exist_ok=True)
for day in ("20260401", "20260601", "20260701", "20260801"):
    q = pd.read_csv(os.path.join(ROOT, "data", "tardis_okx", f"quotes-{day}.csv.gz"))
    q = q.sort_values("timestamp", kind="stable")
    pq.write_table(pa.table({"ts": q["timestamp"].values.astype(np.int64), "bb": q["bid_price"].values.astype(np.float64),
                             "ba": q["ask_price"].values.astype(np.float64), "bq": q["bid_amount"].values.astype(np.float64),
                             "aq": q["ask_amount"].values.astype(np.float64)}), os.path.join(OUT, f"quotes_{day}.parquet"), compression="zstd")
    t = pd.read_csv(os.path.join(ROOT, "data", "tardis_okx", f"trades-{day}.csv.gz")).sort_values("timestamp", kind="stable")
    pq.write_table(pa.table({"ts": t["timestamp"].values.astype(np.int64), "side": np.where(t["side"].values == "buy", 1, -1).astype(np.int8),
                             "price": t["price"].values.astype(np.float64), "qty": t["amount"].values.astype(np.float64)}),
                   os.path.join(OUT, f"trades_{day}.parquet"), compression="zstd")
    print(day, "quotes", len(q), "trades", len(t), "quote dt median us", int(np.median(np.diff(q["timestamp"].values))), flush=True)
