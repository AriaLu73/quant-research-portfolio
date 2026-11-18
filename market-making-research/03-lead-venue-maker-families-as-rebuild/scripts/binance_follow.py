#!/usr/bin/env python3
"""research5: keep a rolling copy of Binance USD-M aggregated trades for a list of TradFi perps.

Why: the public endpoint only serves the most recent ~2 days, so the lead-venue reference for a KuCoin day is lost
unless it is copied in time. Public REST, read-only, no key (same endpoint and file format as fetch_binance_aggtrades.py).
Each cycle pages every symbol forward from the last aggregate-trade id we hold, then sleeps.
Output: data/research5/binance_agg/<SYM>_follow.csv.gz (append-only rows T_ms,price,qty,buyer_is_maker) + <SYM>_follow.lastid
Stop: create an empty file data/research5/binance_agg/STOP, or let --hours run out.
Usage: python scripts/research5/binance_follow.py --hours 192 --start 2026-10-01T11:00 SYM1,SYM2,...
"""
import argparse, gzip, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_binance_aggtrades as F  # noqa: E402

CYCLE_SLEEP_S = 900


def follow_once(sym, start_ms):
    """Page forward from the stored id (or from start_ms the first time). Returns rows written."""
    path = os.path.join(F.OUT, f"{sym}_follow.csv.gz")
    idp = os.path.join(F.OUT, f"{sym}_follow.lastid")
    last_id = int(open(idp).read().strip()) if os.path.exists(idp) else None
    n = 0
    while True:
        rows, used = F.get(F.next_url(sym, start_ms, last_id))
        if not rows:
            break
        with gzip.open(path, "at") as fh:  # one gzip member per page: the file stays readable while we append
            for x in rows:
                fh.write(f"{x['T']},{x['p']},{x['q']},{1 if x['m'] else 0}\n")
        n += len(rows)
        last_id = rows[-1]["a"]
        with open(idp, "w") as f:
            f.write(str(last_id))
        if len(rows) < 1000:
            break
        if used > F.WEIGHT_SOFT_CAP:
            time.sleep(15)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=192)
    ap.add_argument("--start", required=True)
    ap.add_argument("symbols")
    a = ap.parse_args()
    os.makedirs(F.OUT, exist_ok=True)
    start_ms, t_end = F.utc_ms(a.start), time.time() + a.hours * 3600
    syms = a.symbols.split(",")
    while time.time() < t_end and not os.path.exists(os.path.join(F.OUT, "STOP")):
        tot = 0
        for s in syms:
            try:
                tot += follow_once(s, start_ms)
            except Exception as e:  # noqa: BLE001
                print(time.strftime("%Y-%m-%d %H:%M:%S"), s, "ERR", repr(e)[:160], flush=True)
        print(time.strftime("%Y-%m-%d %H:%M:%S"), "cycle done, rows", tot, flush=True)
        time.sleep(CYCLE_SLEEP_S)
    print("STOPPED", flush=True)


if __name__ == "__main__":
    main()
