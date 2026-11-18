#!/usr/bin/env python3
"""research5: how long does the EXCHANGE take to put an order into the book - for us and for everybody else?

Public order-by-order feed (level3v2, our own recording): every `open` message carries orderTime (ns: when the exchange
received the order) and ts (when it was resting in the book). ts - orderTime is measured on the exchange's own clock for
every participant, so it shows whether our slow orders are slow because of us or because of the exchange, and whether
other participants are treated differently. `received` messages give each order's clientOid; its pattern (digits collapsed)
identifies the program that sent it. Our own orders are found by their exchange order ids from the live journal.
Usage: Python314/python.exe scripts/research5/l3_entry_delay.py <folder> <SYMBOL> <hours e.g. 18,19,20> [trade_events.jsonl]
"""
import collections, glob, gzip, json, os, re, sys, zlib
import numpy as np

_DIG = re.compile(r"\d+")


def family(client_oid):
    """clientOid -> sender fingerprint: digit runs collapsed, first 16 characters, plus the total length."""
    if not client_oid:
        return "none"
    return _DIG.sub("#", client_oid)[:16] + "|%d" % len(client_oid)


def entry_delay_ms(order_time_ns, ts_ns):
    """Time from the exchange receiving an order to the order resting in the book, ms."""
    return (ts_ns - order_time_ns) / 1e6


def pct(v, ps=(50, 75, 90, 95, 99)):
    v = np.asarray(v, float)
    return "  ".join(f"p{p} {np.percentile(v, p):6.2f}" for p in ps)


def main():
    folder, sym, hours = sys.argv[1], sys.argv[2], {"%02d" % int(h) for h in sys.argv[3].split(",")}
    ours = set()
    if len(sys.argv) > 4:
        for line in open(sys.argv[4], encoding="utf-8"):
            e = json.loads(line)
            if e["type"] == "OrderReport" and e["msg"].get("exchange_order_id"):
                ours.add(e["msg"]["exchange_order_id"])
    fam_of, by_fam, all_d, our_d, per_min = {}, collections.defaultdict(list), [], [], collections.defaultdict(list)
    for f in sorted(glob.glob(os.path.join(folder, f"??_{sym}_l3.jsonl.gz"))):
        if os.path.basename(f)[:2] not in hours:
            continue
        try:
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    i = line.find("\t")
                    if i <= 0:
                        continue
                    if '"subject":"received"' in line:
                        d = json.loads(line[i + 1:])["data"]
                        fam_of[d["orderId"]] = family(d.get("clientOid"))
                    elif '"subject":"open"' in line:
                        d = json.loads(line[i + 1:])["data"]
                        dl = entry_delay_ms(int(d["orderTime"]), int(d["ts"]))
                        if -5 < dl < 500:
                            oid = d["orderId"]
                            all_d.append(dl)
                            fam = "OURS" if oid in ours else fam_of.pop(oid, "unknown")
                            by_fam[fam].append(dl)
                            if oid in ours:
                                our_d.append(dl)
                            per_min[int(d["ts"]) // 60_000_000_000].append(dl)
        except (EOFError, OSError, zlib.error):
            pass
    print(f"{sym} hours {sorted(hours)}: {len(all_d)} orders entered the book; exchange receive -> resting, ms (exchange clock; ts has ms resolution)")
    print(f"  everybody : n {len(all_d):8d} | {pct(all_d)} | slower than 5 ms {np.mean(np.asarray(all_d) > 5):.1%}, 10 ms {np.mean(np.asarray(all_d) > 10):.1%}, 20 ms {np.mean(np.asarray(all_d) > 20):.1%}")
    if our_d:
        o = np.asarray(our_d)
        print(f"  our orders: n {len(o):8d} | {pct(o)} | slower than 5 ms {np.mean(o > 5):.1%}, 10 ms {np.mean(o > 10):.1%}, 20 ms {np.mean(o > 20):.1%}")
    print("  by sender pattern (the 12 busiest):")
    for fam, v in sorted(by_fam.items(), key=lambda kv: -len(kv[1]))[:12]:
        v = np.asarray(v)
        print(f"    {fam:24s} n {len(v):8d} | {pct(v)} | >10 ms {np.mean(v > 10):.1%}")
    # is the delay a property of the moment (everybody slow together)?
    mins = sorted(per_min)
    med = np.array([np.median(per_min[m]) for m in mins]); p90 = np.array([np.percentile(per_min[m], 90) for m in mins])
    print(f"  per minute: median of the minute medians {np.median(med):.2f} ms; minutes whose p90 exceeds 10 ms: {np.mean(p90 > 10):.0%} of {len(mins)}")


if __name__ == "__main__":
    main()
