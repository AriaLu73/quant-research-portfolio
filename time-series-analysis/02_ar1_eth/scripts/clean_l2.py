"""Clean local Binance spot ETHUSD L2 message logs into OBI-ready snapshots.

Input  : one JSON-lines message log per UTC day (header line + messages).
         Message layout: [type, instrument_id, prev_u, u, local_ns, exchange_ns, payload]
           type 5 = feed status, 0 = full book snapshot, 1 = incremental depth update,
           6 = best bid/offer, 2 = trades. Side 0 = bid, 1 = ask; quantity 0 deletes a level.
Output : per UTC day
           eth_l2_YYYY-MM-DD.csv  - one row per applied depth update (top-N levels, mid, spread)
           trades_YYYY-MM-DD.csv  - trade prints
         plus cleaning_audit.json with per-day integrity checks.

Only the data needed for order book imbalance and price changes are kept.
The book is rebuilt from the snapshot; every update must continue the
update-id sequence, otherwise the file is rejected (no silent repair).
"""
from __future__ import annotations

import argparse
import heapq
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

SNAPSHOT, UPDATE, TRADE, STATUS, BBO = 0, 1, 2, 5, 6
FILE_PATTERN = re.compile(r"binance_spot-ETHUSD-(\d{4}-\d{2}-\d{2})\.txt$")
PROJECT_DIR = Path(__file__).resolve().parents[1]


def find_logs(source: Path):
    """Return {date: file}; directories named *.txt contain the real file."""
    logs = {}
    for path in sorted(source.rglob("*.txt")):
        match = FILE_PATTERN.search(path.name)
        if match and path.is_file():
            logs[match.group(1)] = path
    return logs


def top_levels(book: dict, depth: int, highest: bool):
    keys = heapq.nlargest(depth, book) if highest else heapq.nsmallest(depth, book)
    return [(float(p), float(book[p])) for p in keys]


def to_frame(rows, depth):
    n = len(rows)
    cols = {"local_time_ns": np.empty(n, np.int64), "exchange_time_ns": np.empty(n, np.int64),
            "update_id": np.empty(n, np.int64)}
    levels = {f"{side}_{field}_{i}": np.full(n, np.nan)
              for side in ("bid", "ask") for field in ("price", "qty")
              for i in range(1, depth + 1)}
    for r, (local_ns, exch_ns, u, bid_lv, ask_lv) in enumerate(rows):
        cols["local_time_ns"][r] = local_ns
        cols["exchange_time_ns"][r] = exch_ns
        cols["update_id"][r] = u
        for side, lv in (("bid", bid_lv), ("ask", ask_lv)):
            for i, (p, q) in enumerate(lv, start=1):
                levels[f"{side}_price_{i}"][r] = p
                levels[f"{side}_qty_{i}"][r] = q
    frame = pd.DataFrame({**cols, **levels})
    frame["mid_price"] = (frame.bid_price_1 + frame.ask_price_1) / 2
    frame["spread"] = frame.ask_price_1 - frame.bid_price_1
    return frame


def apply_levels(bids, asks, levels):
    for side, price, qty, *_ in levels:
        book = bids if side == 0 else asks
        q = Decimal(qty)
        if q < 0:
            raise ValueError(f"Negative quantity at {price}")
        if q == 0:
            book.pop(Decimal(price), None)
        else:
            book[Decimal(price)] = q


def clean_day(path: Path, day: str, depth: int):
    """Rebuild the book and keep rows whose local receive time lies in [day, day+1) UTC."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    lo = int(start.timestamp()) * 10**9
    hi = int((start + timedelta(days=1)).timestamp()) * 10**9
    bids, asks = {}, {}
    last_u, anchor, prev_local = None, None, -1
    rows, trades = [], []
    audit = {"file": str(path), "updates_applied": 0, "sequence_gaps": 0,
             "crossed_books": 0, "thin_book_rows": 0,
             "bbo_checked": 0, "bbo_mismatch": 0, "time_reversals": 0}

    def state(msg):
        return (msg[4], msg[5], last_u,
                top_levels(bids, depth, True), top_levels(asks, depth, False))

    with path.open(encoding="utf-8") as handle:
        instrument = json.loads(handle.readline())["instrument"]
        audit["instrument"] = {k: instrument.get(k) for k in
                               ("code", "exchange_code", "type", "ticksize", "lot_size", "id")}
        for line in handle:
            msg = json.loads(line)
            kind = msg[0]
            if kind == STATUS:
                continue
            if msg[4] < prev_local:
                audit["time_reversals"] += 1
            prev_local = msg[4]

            if kind == SNAPSHOT:
                if last_u is not None:
                    raise ValueError(f"{path}: unexpected second snapshot")
                apply_levels(bids, asks, msg[6])
                last_u = int(msg[3])
                audit["snapshot_levels"] = [len(bids), len(asks)]
                if msg[4] < lo:
                    anchor = state(msg)
            elif kind == UPDATE:
                if last_u is None:
                    raise ValueError(f"{path}: update before snapshot")
                if int(msg[2]) != last_u:
                    raise ValueError(f"{path}: sequence gap {last_u} -> {msg[2]}")
                apply_levels(bids, asks, msg[6])
                last_u = int(msg[3])
                audit["updates_applied"] += 1
                if bids and asks and max(bids) >= min(asks):
                    audit["crossed_books"] += 1
                if msg[4] < lo:
                    anchor = state(msg)   # latest pre-midnight book carries into the day
                elif msg[4] < hi:
                    row = state(msg)
                    if len(row[3]) < depth or len(row[4]) < depth:
                        audit["thin_book_rows"] += 1
                    rows.append(row)
            elif kind == BBO:
                # Cross-check only when the BBO refers to the same book version.
                if last_u is not None and int(msg[3]) == last_u and bids and asks:
                    audit["bbo_checked"] += 1
                    (_, bp, bq, _), (_, ap, aq, _) = msg[6]
                    bb, ba = max(bids), min(asks)
                    if not (Decimal(bp) == bb and Decimal(ap) == ba
                            and Decimal(bq) == bids[bb] and Decimal(aq) == asks[ba]):
                        audit["bbo_mismatch"] += 1
            elif kind == TRADE and lo <= msg[4] < hi:
                for side, price, qty, trade_id, exch_ts in msg[6]:
                    trades.append((msg[4], exch_ts, int(trade_id), side,
                                   float(price), float(qty)))
    return finalize_day(rows, anchor, trades, audit, depth)



def finalize_day(rows, anchor, trades, audit, depth):
    if anchor is not None:
        rows.insert(0, anchor)
    frame = to_frame(rows, depth)
    before = len(frame)
    # Several updates can share one receive nanosecond; the last one is the observable state.
    frame = frame.drop_duplicates("local_time_ns", keep="last").reset_index(drop=True)
    frame["mid_change"] = frame["mid_price"].diff()
    trades = pd.DataFrame(trades, columns=["local_time_ns", "exchange_time_ns", "trade_id",
                                           "side_code", "price", "qty"])
    gaps = np.diff(frame.local_time_ns.to_numpy())
    audit.update({
        "rows": len(frame), "same_ns_rows_dropped": before - len(frame), "trades": len(trades),
        "anchor_row_from_previous_day": anchor is not None,
        "first_time": str(pd.to_datetime(frame.local_time_ns.iloc[0], unit="ns", utc=True)),
        "last_time": str(pd.to_datetime(frame.local_time_ns.iloc[-1], unit="ns", utc=True)),
        "max_silence_s": float(gaps.max() / 1e9),
        "silences_over_10s": int((gaps > 10 * 10**9).sum()),
        "first_update_id": int(frame.update_id.iloc[0]),
        "last_update_id": int(frame.update_id.iloc[-1]),
        "spread_min": float(frame.spread.min()),
    })
    return frame, trades, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=Path("/Users/lujingyi/Desktop/样本"))
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "data" / "cleaned")
    parser.add_argument("--depth", type=int, default=10)
    args = parser.parse_args()

    logs = find_logs(args.source)
    if not logs:
        raise FileNotFoundError(f"No binance_spot-ETHUSD-*.txt logs under {args.source}")
    args.output.mkdir(parents=True, exist_ok=True)
    audits = {}
    for day, path in logs.items():
        frame, trades, audit = clean_day(path, day, args.depth)
        frame.to_csv(args.output / f"eth_l2_{day}.csv", index=False)
        trades.to_csv(args.output / f"trades_{day}.csv", index=False)
        audits[day] = audit
        print(day, {k: audit[k] for k in ("rows", "trades", "crossed_books", "bbo_checked",
                                          "bbo_mismatch", "max_silence_s")}, flush=True)

    days = sorted(audits)
    for prev, nxt in zip(days, days[1:]):
        # Each day must start from a book version no later than where the previous day ended.
        audits[nxt]["continues_previous_day"] = (
            audits[nxt]["first_update_id"] <= audits[prev]["last_update_id"] + 1)
    summary = {"source": str(args.source), "depth": args.depth,
               "excluded": ["binance_spot-ETHUSD-2026-10-10.csv: byte-identical to the "
                            "2026-10-10 .txt log (verified with cmp)"],
               "days": audits}
    (args.output / "cleaning_audit.json").write_text(json.dumps(summary, indent=2),
                                                     encoding="utf-8")
    print("Wrote", args.output)


if __name__ == "__main__":
    main()
