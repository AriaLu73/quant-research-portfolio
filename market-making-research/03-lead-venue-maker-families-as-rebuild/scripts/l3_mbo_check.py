#!/usr/bin/env python3
"""Read-only: is the self-recorded level3v2 feed real market-by-order (MBO) data?
2026-10-28 用户:"检查一下数据是不是 L3 级别的 MBO 数据"。

Checks, on consecutive hourly files of one contract (first hour = warm-up, later hours = checked):
  1. sequence: level3v2 `sequence` contiguous? (gaps / duplicates / reorders)
  2. lifecycle: every order event carries orderId; adds carry side / price / size; fills carry maker + taker ids
     (remainSize = the taker's remaining size); a live orderId opened again = amend; how many fills hit a maker that was received but never opened (hidden) or never seen at all.
  3. book reconciliation: rebuild the book per order from L3 (open / match remainSize / update / done) and the
     aggregated book from L2 (REST snapshot + level2 increments, same contract, same hours). Every 30 s of exchange time,
     at the top K L2 price levels per side, compare L3 total vs L2 total. KuCoin has no L3 snapshot, so orders resting
     since before the first file are unknown: L3 < L2 is expected on old levels; L3 > L2 would mean the L3 feed is wrong.
Prices are compared in ticks; exchange timestamps (ms) only, never the recorder's receive time.
Usage: .venv/Scripts/python.exe -I scripts/research5/l3_mbo_check.py 20261027 13 14 [--sym XBTUSDTM --tick 0.1]
"""
import argparse, collections, gzip, os, sys
import orjson

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
L3DIR = os.path.join(ROOT, "data/research5/usdc_pairs_l3usdt")
L2DIR = os.path.join(ROOT, "data/research5/usdc_pairs")


def lines(path):
    with gzip.open(path, "rb") as fh:
        try:
            for ln in fh:
                t = ln.find(b"\t")
                if t > 0: yield ln[t + 1:]
        except EOFError:
            return


def l3_stream(day, hours, sym):
    for h in hours:
        for raw in lines(os.path.join(L3DIR, day, f"{h:02d}_{sym}_l3.jsonl.gz")):
            o = orjson.loads(raw)
            if "_marker" in o: continue
            d = o["data"]; yield d["ts"] // 1_000_000, o["subject"], d


def l2_stream(day, hours, sym):
    for h in hours:
        for raw in lines(os.path.join(L2DIR, day, f"{h:02d}_{sym}_l2.jsonl.gz")):
            o = orjson.loads(raw)
            if "_marker" in o: continue
            d = o["data"]; p, s, q = d["change"].split(","); yield d["timestamp"], d["sequence"], p, s, int(q)


def first_snapshot(day, h, sym):
    for raw in lines(os.path.join(L2DIR, day, f"{h:02d}_{sym}_snap.jsonl.gz")):
        o = orjson.loads(raw)
        if o.get("code") == "200000": return o["data"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day"); ap.add_argument("hours", nargs="+", type=int)
    ap.add_argument("--sym", default="XBTUSDTM"); ap.add_argument("--tick", type=float, default=0.1)
    ap.add_argument("--l2lag", type=int, default=0, help="compare L3 at T with L2 at T + lag ms (L2 is published ~1 ms after L3)")
    ap.add_argument("--diag", type=int, default=0, help="print N best-level mismatches with the L3 orders resting there")
    a = ap.parse_args()
    tk = lambda p: round(float(p) / a.tick)
    t_check0 = None                                                    # set at first event of the 2nd hour

    # L2 book from the first snapshot of the first hour
    snap = first_snapshot(a.day, a.hours[0], a.sym)
    l2 = {"buy": {tk(p): q for p, q in snap["bids"]}, "sell": {tk(p): q for p, q in snap["asks"]}}
    l2seq = snap["sequence"]; l2gen = l2_stream(a.day, a.hours, a.sym); l2next = next(l2gen, None)
    l2gaps = 0

    def l2_advance(T):                                                 # apply all L2 increments with timestamp < T
        nonlocal l2next, l2seq, l2gaps
        while l2next is not None and l2next[0] < T:
            ts, seq, p, s, q = l2next
            if seq > l2seq:
                if seq != l2seq + 1: l2gaps += 1
                l2seq = seq; book = l2[s]; k = tk(p)
                if q == 0: book.pop(k, None)
                else: book[k] = q
            l2next = next(l2gen, None)

    orders = {}                                                        # oid -> [side, tick, size]
    lvl = {"buy": collections.Counter(), "sell": collections.Counter()}
    received, opened = set(), set()
    c = collections.Counter(); seq_prev = None
    cmp = {K: collections.Counter() for K in (1, 5, 20, 50)}
    px_ex = []; next_cp = None; hour_ms = None; excess1 = []; mism = []
    meta = {}                                                          # oid -> [first open ms, last open ms, reopens, matched as taker]
    diag_left = a.diag; cur_ts = 0

    def diag(T, s, k, y):
        nonlocal diag_left
        diag_left -= 1; rest = sorted((meta[o][0], o) for o, v in orders.items() if v[0] == s and v[1] == k)
        print(f"DIAG T={T} {s} best {k * a.tick:.1f}: L2 {y}  L3 {lvl[s][k]}  orders {len(rest)}")
        for t0, o in rest[:8]:
            m = meta[o]; print(f"    {o} size {orders[o][2]} age {T - t0} ms since last open {T - m[1]} ms reopens {m[2]} taker-before {m[3]}")

    def checkpoint(T):
        l2_advance(T + a.l2lag)
        for s in ("buy", "sell"):
            book = l2[s]
            lv = sorted(book, reverse=(s == "buy"))
            for K in cmp:
                for k in lv[:K]:
                    x, y = lvl[s].get(k, 0), book[k]
                    cmp[K]["eq" if x == y else ("l3_more" if x > y else "l3_less")] += 1
            if lv:
                ex = lvl[s].get(lv[0], 0) - book[lv[0]]; excess1.append(ex)
                if ex > 0: mism.append((ex, [(o, v[2]) for o, v in orders.items() if v[0] == s and v[1] == lv[0]]))
            if diag_left and lv and lvl[s].get(lv[0], 0) != book[lv[0]]:
                diag(T, s, lv[0], book[lv[0]])
            for k, x in lvl[s].items():                                # L3 volume at a price L2 says is empty
                if x > 0 and k not in book: cmp[50]["l3_where_l2_empty"] += 1
        c["checkpoints"] += 1

    for ts, subj, d in l3_stream(a.day, a.hours, a.sym):
        seq = d.get("sequence")
        if seq is not None:
            if seq_prev is not None:
                if seq == seq_prev + 1: pass
                elif seq <= seq_prev: c["seq_dup_or_back"] += 1
                else: c["seq_gaps"] += 1; c["seq_missing"] += seq - seq_prev - 1
            seq_prev = seq
        if hour_ms is None: hour_ms = ts - ts % 3_600_000; t_check0 = hour_ms + 3_600_000; next_cp = t_check0
        while next_cp is not None and ts >= next_cp and ts >= t_check0:
            checkpoint(next_cp); next_cp += 30_000
        c[subj] += 1
        if subj == "received": received.add(d["orderId"])
        elif subj == "open":
            oid = d["orderId"]; s = d["side"]; k = tk(d["price"]); q = int(d["size"])
            o = orders.get(oid)
            if o is not None:                                          # 同一订单号再次 open = 改单(不换订单号)
                lvl[o[0]][o[1]] -= o[2]
                c["reopen_new_price" if o[1] != k else ("reopen_new_size" if o[2] != q else "reopen_same")] += 1
            opened.add(oid); orders[oid] = [s, k, q]; lvl[s][k] += q
            mm = meta.setdefault(oid, [ts, ts, 0, False]); mm[1] = ts; mm[2] += o is not None
        elif subj == "match":
            m = d.get("makerOrderId") or ""; t = d.get("takerOrderId") or ""
            if not m: c["match_no_maker_id"] += 1
            if not t: c["match_no_taker_id"] += 1
            if t in meta: meta[t][3] = True
            elif t: meta[t] = [ts, ts, 0, True]
            o = orders.get(m)
            if o is not None:
                q = int(d["size"]); lvl[o[0]][o[1]] -= q; o[2] -= q          # remainSize 是吃单方剩余,不是挂单方
                if o[2] < 0: c["match_maker_size_negative"] += 1
                if tk(d["price"]) != o[1]:
                    c["match_px_differs_from_maker_px"] += 1
                    if len(px_ex) < 3: px_ex.append((m, d["price"], o[1] * a.tick, d["side"], o[0]))
            elif m in received: c["match_maker_received_never_opened"] += 1
            else: c["match_maker_unknown(pre-window)"] += 1
        elif subj == "update":
            o = orders.get(d["orderId"])
            if o is not None:
                q = int(d["size"]); lvl[o[0]][o[1]] += q - o[2]; o[2] = q
            else: c["update_unknown_order"] += 1
        elif subj == "done":
            o = orders.pop(d["orderId"], None)
            if o is not None: lvl[o[0]][o[1]] -= o[2]
            c["done_" + d.get("reason", "?")] += 1

    print(f"== {a.sym} {a.day} hours {a.hours} L2 lag {a.l2lag} ms (first hour = warm-up; book compared from hour {a.hours[1]:02d}:00 every 30 s)")
    print("L3 events:", {k: c[k] for k in ("received", "open", "match", "update", "done_canceled", "done_filled")})
    print("L3 sequence: gaps", c["seq_gaps"], "missing", c["seq_missing"], "dup/back", c["seq_dup_or_back"],
          "| L2 seq gaps", l2gaps)
    print("matches:", {k: v for k, v in c.items() if k.startswith("match_")})
    print("re-open of a live orderId (amend):", {k: v for k, v in c.items() if k.startswith("reopen_")})
    print("match price != maker book price, examples (maker, match px, book px, taker side, maker side):", px_ex)
    print("update on unknown order:", c["update_unknown_order"], "| checkpoints:", c["checkpoints"])
    for K, v in cmp.items():
        n = v["eq"] + v["l3_more"] + v["l3_less"]
        if n: print(f"top {K:>2} levels/side: n={n}  L3==L2 {v['eq'] / n:.4%}  L3<L2 {v['l3_less'] / n:.4%}  "
                    f"L3>L2 {v['l3_more'] / n:.4%}")
    e = sorted(excess1)
    if e: print(f"best level L3 - L2 (contracts): median {e[len(e) // 2]}, p90 {e[int(len(e) * .9)]}, max {e[-1]}, min {e[0]}")
    # 撤单消息落在序号缺口里的单永远等不到 done,到最后还在簿里;有 done 的单生命周期完整
    if mism:
        st = sum(min(ex, sum(q for o, q in os_ if o in orders)) for ex, os_ in mism); tot = sum(ex for ex, _ in mism)
        print(f"best-level excess {tot} contracts over {len(mism)} mismatches: from orders never done by end (likely lost "
              f"cancel in a sequence gap) <= {st} ({st / tot:.1%}); rest {tot - st} ({1 - st / tot:.1%}) from orders with a complete "
              f"L3 lifecycle that L2 does not count")
    print("L3 volume at prices L2 shows empty (all levels, summed over checkpoints):", cmp[50]["l3_where_l2_empty"])


if __name__ == "__main__":
    sys.exit(main())
