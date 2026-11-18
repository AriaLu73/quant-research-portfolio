#!/usr/bin/env python3
"""research3:把购买数据(data/book_l2 + data/trades)里任意合约抽成 research2 事件 parquet(盘口帧 + 成交),复用 extract_events.process。
SYM 标签 = 原生合约名(如 XAUTUSDTM);规格取自 data/research2/kc_contract_specs.json。已存在的输出跳过(可断点续跑)。
用法:python scripts/research3/extract_buy_tob.py --syms XAUTUSDTM,PAXGUSDTM --workers 3"""
import argparse, glob, json, os, sys
from concurrent.futures import ProcessPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research2"))
import extract_events as ee
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buy_paths as BP


class PathFmt:
    """让 extract_events 按 (kind) 取到我们定位好的绝对路径(它调用 fmt.format(kind=..., day=...))。"""
    def __init__(self, book, trades):
        self.book, self.trades = book, trades

    def format(self, kind, day):
        return self.book if kind == "book" else self.trades

SPECS = json.load(open(os.path.join(ROOT, "data", "research2", "kc_contract_specs.json")))
for s, sp in SPECS.items():
    ee.SPEC[s] = dict(tick=float(sp["tick"]), mult=float(sp["mult"]), buy=s)


def job(a):
    try:
        s, d = a; sp = SPECS[s]
        ee.SPEC[s] = dict(tick=float(sp["tick"]), mult=float(sp["mult"]), src="", fmt=PathFmt(BP.book_file(s, d), BP.trade_file(s, d)))
        return ee.process(a)
    except Exception as e:  # noqa: BLE001
        return f"{a}: ERROR {e!r}"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--syms", required=True); ap.add_argument("--workers", type=int, default=3); ap.add_argument("--days", default="")
    ns = ap.parse_args()
    days = ns.days.split(",") if ns.days else sorted(p.replace("\\", "/").split("/")[-3] + p.replace("\\", "/").split("/")[-2] + p.replace("\\", "/").split("/")[-1]
                                                      for p in glob.glob(os.path.join(ROOT, "data", "book_l2", "2026", "*", "*")))
    jobs = [(s, d) for d in days for s in ns.syms.split(",")
            if s in SPECS and BP.book_file(s, d) and BP.trade_file(s, d)
            and not os.path.exists(os.path.join(ee.OUT, f"audit_{s}_{d}.json"))]
    print(f"{len(jobs)} jobs", flush=True)
    with ProcessPoolExecutor(ns.workers) as ex:
        for r in ex.map(job, jobs):
            print(r, flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
