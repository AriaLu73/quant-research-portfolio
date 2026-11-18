"""Step 1 提取(9 月购买数据 L2 + 成交):按 ladder_store 格式记录 50 ms 网格边界的盘口、每笔 MO 到达前的盘口与成交量。
MO = 同 ts_ms 同方向打印合并(EC-03);同毫秒内成交排在盘口更新之前,所以第一笔打印到来时的 Book 就是 MO 到达前的盘口。
用法  python l2_extract.py <sym> <YYYYMMDD> <HH>   → data/step01/<sym>/<day>_<hh>.npz
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPRO, "data"))
import ladder_store as LS          # noqa: E402
import load_l2buy as LB            # noqa: E402
from stream import Book            # noqa: E402

OUT = os.path.join(REPRO, "data", "step01")


def extract(sym, day, hh):
    ev, meta = LB.load_hour(sym, day, hh)
    w = LS.LadderWriter("l2buy", sym)
    book = Book()
    seen_snapshot = False
    cur_mo, cur = None, None       # cur = [ts, side, vol, n, first, last, pre_levels]
    for e in ev:
        ts = int(e["ts"])
        if e["kind"] == 0 and not seen_snapshot:
            seen_snapshot = True
        if seen_snapshot:
            w.on_time(ts, book.levels)
        if e["kind"] == 1:
            mo = int(e["mo_id"])
            if mo != cur_mo:
                if cur is not None:
                    w.on_sweep(*cur)
                side = int(e["side"])
                hit = 1 - side                                   # 吃单买 → 打卖单
                cur_mo = mo
                cur = [ts, side, 0, 0, int(e["tick"]), int(e["tick"]), book.levels(hit, LS.K)]
            cur[2] += int(e["qty"])
            cur[3] += 1
            cur[5] = int(e["tick"])
        else:
            book.apply(e)
    if cur is not None:
        w.on_sweep(*cur)
    return w, meta


if __name__ == "__main__":
    sym, day, hh = sys.argv[1:4]
    w, meta = extract(sym, day, hh)
    r = w.save(os.path.join(OUT, sym, f"{day}_{hh}.npz"), day=day, hh=hh, l2_meta=meta,
               tick=LB.CONTRACTS[sym]["tick"], mult=LB.CONTRACTS[sym]["mult"])
    print(f"{sym} {day} {hh}: bnd={r['n_bnd']:,} mos={r['n_sw']:,} deep={r['n_deep']} seq_breaks={meta.get('seq_breaks')} EXTRACT_DONE", flush=True)
