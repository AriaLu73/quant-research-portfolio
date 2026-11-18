#!/usr/bin/env python3
"""research3:回测切片(data/oos/ku_buy)的盘口质量扫描(只读)。起因:2026-10-02 发现 BTC-USDC 09-23 14:15 起买盘里卡着两档
过期价位(84347.5 / 84292.3,比市价高 20–60 bp),重建出的盘口一直是交叉的(买一 > 卖一);这类小时的回测结果是数据假象。
注意(2026-10-02):本脚本没有在快照帧处重置盘口(引擎会重置),交叉小时数被高估约十倍;准确口径见 clean_buy_slices.py 的 clean_stats。
逐小时重建买一卖一(增量:数量 0 = 删除),统计:交叉的记录占比、交叉幅度中位(bp)、点差中位(bp)。
用法:Python314/python.exe -X utf8 scripts/research3/uh_book_quality_scan.py <合约,如 BTC-USDC> [day1,day2,...]
输出:data/research3/uh_val/book_quality_<合约>.csv(每小时一行)"""
import csv, glob, gzip, json, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sym = sys.argv[1]
days = sys.argv[2].split(",") if len(sys.argv) > 2 else sorted({os.path.basename(p).split("_")[0] for p in glob.glob(os.path.join(ROOT, "data", "oos", "ku_buy", "2026*_00"))})
out = os.path.join(ROOT, "data", "research3", "uh_val", f"book_quality_{sym}.csv")
rows = []
for day in days:
    for h in range(24):
        p = os.path.join(ROOT, "data", "oos", "ku_buy", f"{day}_{h:02d}", "kucoin", "swap", sym, "feed_raw", f"depth_deltas-{day}.jsonl.gz")
        if not os.path.exists(p):
            continue
        B, A, n, sp = {}, {}, 0, []
        with gzip.open(p, "rt") as f:
            for l in f:
                o = json.loads(l); n += 1
                for side, book in (("bids", B), ("asks", A)):
                    for px, q in o.get(side, ()):
                        if float(q) == 0:
                            book.pop(float(px), None)
                        else:
                            book[float(px)] = 1
                if B and A:
                    b, a = max(B), min(A); sp.append((a - b) / a * 1e4)
        sp = np.array(sp); cr = sp <= 0
        rows.append(dict(day=day, hh=f"{h:02d}", records=n, crossed_pct=round(float(cr.mean() * 100), 2), crossed_med_bp=round(float(-np.median(sp[cr])), 1) if cr.any() else 0.0,
                         spread_med_bp=round(float(np.median(sp)), 2)))
    bad = [(r["hh"], r["crossed_pct"]) for r in rows if r["day"] == day and r["crossed_pct"] > 1.0]
    print(day, sym, "交叉占比 > 1% 的小时:", bad, flush=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
