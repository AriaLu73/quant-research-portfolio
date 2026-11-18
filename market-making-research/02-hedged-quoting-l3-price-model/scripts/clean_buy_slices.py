#!/usr/bin/env python3
"""research3:把回测切片 data/oos/ku_buy 清洗成 data/oos/ku_buyc(不改原切片、不改原始购买数据、不改引擎)。

问题(2026-10-02 发现,scripts/research3/uh_book_quality_scan.py):购买的 KuCoin L2 增量里有"漏掉的删除":某价位挂上后没有对应的删除,
  市场走开后它一直留在簿里,重建出的盘口是交叉的(买一 ≥ 卖一)。例:BTC-USDC 09-23 14:13 的买单 84347.5 / 84292.3 再没被删,
  几分钟后同一价位出现卖单的挂与撤。每天的开盘快照也会带着前一天的残留。三个 USDC 合约和 USDT 合约都有。引擎的重建器不清理交叉。
规则(新消息为准):一帧里某一侧在价位 p 有新的挂单量(> 0)时,对侧所有"价格与 p 交叉(买 ≥ p / 卖 ≤ p)且不是本帧更新的"档位判为过期,
  在同一帧里补一条数量 0 的删除。真实的连续撮合里同价位不可能同时有买卖挂单,所以被删的只能是过期档位。
  每个小时切片开头的合成快照(原转换器按带残留的簿生成)换成清洗后的簿;供应商自己的快照(断线重连、每天开盘)照常清簿加载,
  其中的残留由随后的更新按同一规则清掉。
清不掉的:没有被对侧新挂单碰到的过期档位(例如价格还没回到那里)仍留在簿里——它不交叉,但可能冒充买一/卖一;逐小时统计里给出
  清洗后仍交叉的帧占比。成交文件(ticks)原样硬链接。
用法:.venv/Scripts/python.exe scripts/research3/clean_buy_slices.py --symbols BTC-USDC,BTC-USDT --days 20260901,... --workers 4
输出:data/oos/ku_buyc/<day>_<hh>/kucoin/swap/<合约>/feed_raw/…;统计 data/research3/uh_val/clean_stats/<合约>_<day>.csv"""
import argparse, csv, glob, gzip, heapq, os, shutil, sys
from concurrent.futures import ProcessPoolExecutor
import orjson

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC, DST = os.path.join(ROOT, "data", "oos", "ku_buy"), os.path.join(ROOT, "data", "oos", "ku_buyc")
STATS = os.path.join(ROOT, "data", "research3", "uh_val", "clean_stats")


class Side:
    """One side of the book: price -> [price string, amount string]; best price through a lazy heap."""

    def __init__(self, is_bid):
        self.lv, self.heap, self.sign = {}, [], (-1.0 if is_bid else 1.0)

    def clear(self):
        self.lv.clear(); self.heap.clear()

    def set(self, px, pxs, amt):
        if px not in self.lv:
            heapq.heappush(self.heap, self.sign * px)
        self.lv[px] = [pxs, amt]

    def drop(self, px):
        self.lv.pop(px, None)

    def best(self):
        h, lv, s = self.heap, self.lv, self.sign
        while h and (s * h[0]) not in lv:
            heapq.heappop(h)
        return s * h[0] if h else None


def clean_frame(o, bids, asks, st):
    """Apply one frame to the book and add the deletes of stale opposite levels to it. Returns nothing; `o` is edited."""
    tb, ta = set(), set()
    new_b = new_a = None                                   # most aggressive price newly quoted on each side in this frame
    for pxs, amt in o["bids"]:
        px = float(pxs); tb.add(px)
        if float(amt) == 0.0:
            bids.drop(px)
        else:
            bids.set(px, pxs, amt)
            if new_b is None or px > new_b:
                new_b = px
    for pxs, amt in o["asks"]:
        px = float(pxs); ta.add(px)
        if float(amt) == 0.0:
            asks.drop(px)
        else:
            asks.set(px, pxs, amt)
            if new_a is None or px < new_a:
                new_a = px
    if new_a is not None:                                  # a new ask at new_a: older bids at or above it cannot be there
        skipped = []
        while True:
            b = bids.best()
            if b is None or b < new_a:
                break
            if b in tb:                                    # updated in this very frame: not older, leave it (counted below)
                skipped.append(b); heapq.heappop(bids.heap); continue
            o["bids"].append([bids.lv[b][0], "0"]); bids.drop(b); st["ghost"] += 1
        for b in skipped:
            heapq.heappush(bids.heap, -b)
    if new_b is not None:
        skipped = []
        while True:
            a = asks.best()
            if a is None or a > new_b:
                break
            if a in ta:
                skipped.append(a); heapq.heappop(asks.heap); continue
            o["asks"].append([asks.lv[a][0], "0"]); asks.drop(a); st["ghost"] += 1
        for a in skipped:
            heapq.heappush(asks.heap, a)


def one(args):
    sym, day = args
    os.makedirs(STATS, exist_ok=True)
    stat_path = os.path.join(STATS, f"{sym}_{day}.csv")
    if os.path.exists(stat_path):
        return f"{sym} {day}: skip (done)"
    bids, asks, rows = Side(True), Side(False), []
    for h in range(24):
        sdir = os.path.join(SRC, f"{day}_{h:02d}", "kucoin", "swap", sym, "feed_raw")
        src = os.path.join(sdir, f"depth_deltas-{day}.jsonl.gz")
        if not os.path.exists(src):
            return f"{sym} {day}: missing hour {h:02d}"
        ddir = os.path.join(DST, f"{day}_{h:02d}", "kucoin", "swap", sym, "feed_raw")
        os.makedirs(ddir, exist_ok=True)
        dst = os.path.join(ddir, f"depth_deltas-{day}.jsonl.gz")
        st = dict(day=day, hh=f"{h:02d}", frames=0, ghost=0, crossed_before=0, crossed_after=0, snap_frames=0)
        raw_b, raw_a = {}, {}                              # the uncleaned book of this hour, only to count how often it was crossed
        with gzip.open(src, "rb") as fi, gzip.open(dst + ".tmp", "wb", compresslevel=4) as fo:
            for n, line in enumerate(fi):
                o = orjson.loads(line); st["frames"] += 1
                if o.get("snapshot"):
                    st["snap_frames"] += 1
                    raw_b.clear(); raw_a.clear()
                for pxs, amt in o["bids"]:
                    if float(amt) == 0.0:
                        raw_b.pop(float(pxs), None)
                    else:
                        raw_b[float(pxs)] = 1
                for pxs, amt in o["asks"]:
                    if float(amt) == 0.0:
                        raw_a.pop(float(pxs), None)
                    else:
                        raw_a[float(pxs)] = 1
                if n == 0 and o.get("snapshot") and h > 0 and (bids.lv or asks.lv):
                    o["bids"] = list(bids.lv.values()); o["asks"] = list(asks.lv.values())      # hour start: our cleaned book
                else:
                    if o.get("snapshot"):
                        bids.clear(); asks.clear()
                    clean_frame(o, bids, asks, st)
                if n % 50 == 0:
                    if raw_b and raw_a and max(raw_b) >= min(raw_a):
                        st["crossed_before"] += 1
                    b, a = bids.best(), asks.best()
                    if b is not None and a is not None and b >= a:
                        st["crossed_after"] += 1
                fo.write(orjson.dumps(o) + b"\n")
        os.replace(dst + ".tmp", dst)
        t_src, t_dst = os.path.join(sdir, f"ticks-{day}.jsonl.gz"), os.path.join(ddir, f"ticks-{day}.jsonl.gz")
        if os.path.exists(t_src) and not os.path.exists(t_dst):
            try:
                os.link(t_src, t_dst)
            except OSError:
                shutil.copyfile(t_src, t_dst)
        k = max(1, (st["frames"] + 49) // 50)
        st["crossed_before_pct"] = round(st.pop("crossed_before") / k * 100, 2); st["crossed_after_pct"] = round(st.pop("crossed_after") / k * 100, 2)
        rows.append(st)
    with open(stat_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return (f"{sym} {day}: frames {sum(r['frames'] for r in rows):,} ghosts removed {sum(r['ghost'] for r in rows):,}  hours crossed>1% before "
            f"{sum(r['crossed_before_pct'] > 1 for r in rows)} after {sum(r['crossed_after_pct'] > 1 for r in rows)}  worst after {max(r['crossed_after_pct'] for r in rows)}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--days", default="")
    ap.add_argument("--workers", type=int, default=3)
    ns = ap.parse_args()
    days = ns.days.split(",") if ns.days else sorted({os.path.basename(p).split("_")[0] for p in glob.glob(os.path.join(SRC, "2026*_00"))})
    jobs = [(s, d) for d in days for s in ns.symbols.split(",")]
    with ProcessPoolExecutor(ns.workers) as ex:
        for msg in ex.map(one, jobs):
            print(msg, flush=True)
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    main()
