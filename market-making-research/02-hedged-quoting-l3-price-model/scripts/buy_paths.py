#!/usr/bin/env python3
"""购买数据的盘口文件定位(只读,不移动任何文件)。2026-10-01 重下的数据落在三种位置:
  ① data/book_l2/YYYY/MM/DD/<合约>.csv.gz(标准布局)
  ② data/kucoin-futures/incremental_book_L2/YYYY/MM/DD/<合约>.csv.gz
  ③ data/<DD>/<合约>.csv(1).gz 或 <合约>.csv.gz(网盘把同名的成交与盘口下到同一目录,盘口被改名带 (1);靠表头里有 is_snapshot 判别;月份按 9 月)
成交一律用 data/trades/YYYY/MM/DD/<合约>.csv.gz。"""
import glob, gzip, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data")


def _is_book(path):
    try:
        with gzip.open(path, "rt") as fh:
            return "is_snapshot" in fh.readline()
    except Exception:  # noqa: BLE001
        return False


def day_dirs(day):
    y, m, d = day[:4], day[4:6], day[6:]
    out = [os.path.join(DATA, "book_l2", y, m, d), os.path.join(DATA, "kucoin-futures", "incremental_book_L2", y, m, d)]
    if (y, m) == ("2026", "09"):
        out.append(os.path.join(DATA, d))
    return [p for p in out if os.path.isdir(p)]


def book_file(sym, day):
    for dd in day_dirs(day):
        for nm in (f"{sym}.csv(1).gz", f"{sym}.csv.gz"):
            p = os.path.join(dd, nm)
            if os.path.exists(p) and not glob.glob(glob.escape(os.path.join(dd, sym)) + ".csv*downloading") and (os.path.basename(dd) != day[6:] or "book_l2" in dd or "incremental" in dd or _is_book(p)):
                return p
    return None


def trade_file(sym, day):
    p = os.path.join(DATA, "trades", day[:4], day[4:6], day[6:], sym + ".csv.gz")
    return p if os.path.exists(p) else None


def symbols(day):
    s = set()
    for dd in day_dirs(day):
        for p in glob.glob(os.path.join(dd, "*.gz")):
            s.add(os.path.basename(p).split(".csv")[0])
    return sorted(x for x in s if book_file(x, day) and trade_file(x, day))


def downloading(day):
    return sum(len(glob.glob(os.path.join(dd, "*downloading"))) for dd in day_dirs(day))


if __name__ == "__main__":
    import sys
    for d in sys.argv[1:]:
        print(d, "dirs", day_dirs(d), "books", len(symbols(d)), "downloading", downloading(d))
