#!/usr/bin/env python3
"""research5 X-2: audit of the existing U15 exam backtests (read-only; no backtest is run).

Question: how much of the public USDC tape did the simulated U15 trade against, and what kind of public print triggered
each simulated USDC fill?

Inputs
  data/backtest_results/r2_ku_buy_<day>_<hh>_..._(EX7|B2D)_U15_s1_..._0/{fills.parquet,report.json}   36 one-hour runs
  data/oos/ku_buy/<day>_<hh>/kucoin/swap/BTC-USDC/feed_raw/{ticks,depth_deltas}-<day>.jsonl.gz        purchased tape + L2
Definitions
  tape print "inside"  : price strictly between the best bid and best ask standing just before the print. A resting order
                         cannot be hit at a price where nothing rests, so such a print is a participant taking its own
                         just-posted order (paired print; in our id-carrying recordings these have maker age <= 20 ms).
  tape print "at_touch": price == best bid (sell) or best ask (buy) just before the print.
  tape print "through" : beyond the touch on the taker's side (walked the book).
  trigger of a fill    : public USDC prints with ts in [fill_ts - WINDOW_MS, fill_ts], taker side opposite to our side,
                         price at or through our fill price. The fill is "inside-triggered" if every trigger is "inside".
Output: per-hour table and totals -> logs/r5_u15_fill_audit.txt (stdout), data/research5/u15_fill_audit.csv
Usage: python scripts/research5/u15_fill_audit.py
"""
import glob, gzip, json, os, re
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WINDOW_MS = 200
MULT = 1.0     # BTC-USDC slices carry size in BTC


def classify(px, side, bb, ba):
    """Position of a taker print relative to the book standing before it."""
    if not (bb == bb and ba == ba) or ba <= bb:
        return "nobook"
    if bb < px < ba:
        return "inside"
    if (side == "buy" and px == ba) or (side == "sell" and px == bb):
        return "at_touch"
    if (side == "buy" and px > ba) or (side == "sell" and px < bb):
        return "through"
    return "other"        # e.g. a taker buy printed at the bid: book and tape out of order


class L2:
    """Minimal L2 book from snapshot/delta messages ({"bids": [[px, sz]], "asks": ..., "snapshot": bool})."""

    def __init__(self):
        self.b, self.a = {}, {}

    def apply(self, m):
        if m.get("snapshot"):
            self.b, self.a = {}, {}
        for book, key in ((self.b, "bids"), (self.a, "asks")):
            for p, s in m.get(key) or ():
                p, s = float(p), float(s)
                if s == 0:
                    book.pop(p, None)
                else:
                    book[p] = s

    def best(self):
        return (max(self.b) if self.b else np.nan), (min(self.a) if self.a else np.nan)


def tape_with_book(feed_dir, day):
    """Public prints of one slice with the best bid/ask standing before each (book events with ts <= print ts - 1 ms)."""
    def rd(name):
        with gzip.open(os.path.join(feed_dir, f"{name}-{day}.jsonl.gz"), "rt") as fh:
            return [json.loads(x) for x in fh]
    ticks, deltas = rd("ticks"), rd("depth_deltas")
    book, k, rows = L2(), 0, []
    for t in sorted(ticks, key=lambda x: x["ts_ns"]):
        while k < len(deltas) and deltas[k]["ts_ms"] < t["ts_ms"]:
            book.apply(deltas[k])
            k += 1
        bb, ba = book.best()
        px, sz = float(t["price"]), float(t["size"])
        rows.append((t["ts_ms"], t["side"], px, sz * px * MULT, bb, ba, classify(px, t["side"], bb, ba)))
    return pd.DataFrame(rows, columns=["ts", "side", "px", "usd", "bb", "ba", "cls"])


def fill_triggers(fills, tape):
    """For each simulated USDC maker fill: class of the public prints that could have triggered it."""
    out = []
    ts, side, px, cls = tape.ts.to_numpy(), tape.side.to_numpy(), tape.px.to_numpy(), tape.cls.to_numpy()
    for f in fills.itertuples():
        t = f.ts_ns // 1_000_000
        lo, hi = np.searchsorted(ts, t - WINDOW_MS, "left"), np.searchsorted(ts, t, "right")
        taker = "sell" if f.side == "buy" else "buy"
        ok = [i for i in range(lo, hi) if side[i] == taker and (px[i] <= f.px if taker == "sell" else px[i] >= f.px)]
        kinds = {cls[i] for i in ok}
        out.append("none" if not ok else "inside" if kinds == {"inside"} else "mixed" if "inside" in kinds else "book")
    return out


def main():
    rows, alltape, allfills = [], [], []
    for d in sorted(glob.glob(os.path.join(ROOT, "data", "backtest_results", "r2_ku_buy_*_U15_s1_ku_buy_*_0"))):
        m = re.search(r"r2_ku_buy_(\d{8})_(\d\d)_.*_(EX7|B2D)_U15", os.path.basename(d))
        if not m:
            continue
        day, hh, tag = m.groups()
        fp = os.path.join(d, "fills.parquet")          # an hour without any fill has no fills file
        f = pd.read_parquet(fp) if os.path.exists(fp) else pd.DataFrame(columns=["symbol", "side", "price", "qty", "maker", "ts_ns"]).astype({"maker": bool})
        f["px"], f["usd"] = f.price.astype(float), f.price.astype(float) * f.qty.astype(float)
        rep = json.load(open(os.path.join(d, "report.json")))["mm"]
        tape = tape_with_book(os.path.join(ROOT, "data", "oos", "ku_buy", f"{day}_{hh}", "kucoin", "swap", "BTC-USDC", "feed_raw"), day)
        uc = f[(f.symbol == "BTC-USDC") & f.maker].copy()
        uc["trig"] = fill_triggers(uc, tape)
        pnl = float(rep["pnl_total"]) + 0.5e-4 * uc.usd.sum()          # engine pays OUR_FEE on USDC; our tier pays OUR_FEE
        rows.append(dict(day=day, hh=hh, tag=tag, pnl=pnl, usdc_fill=uc.usd.sum(), n_fill=len(uc), usdt=f.usd[f.symbol == "BTC-USDT"].sum(),
                         tape=tape.usd.sum(), tape_inside=tape.usd[tape.cls == "inside"].sum(), tape_book=tape.usd[tape.cls.isin(["at_touch", "through"])].sum(),
                         fill_inside=uc.usd[uc.trig == "inside"].sum(), fill_book=uc.usd[uc.trig.isin(["book", "mixed"])].sum(), fill_none=uc.usd[uc.trig == "none"].sum()))
        alltape.append(tape.assign(day=day, hh=hh))
        allfills.append(uc.assign(day=day, hh=hh))
    r = pd.DataFrame(rows)
    r.to_csv(os.path.join(ROOT, "data", "research5", "u15_fill_audit.csv"), index=False)
    pd.set_option("display.width", 250)
    print(r.round(2).to_string(index=False))
    t = pd.concat(alltape)
    print("\npublic USDC tape by class ($ share):", (t.groupby("cls").usd.sum() / t.usd.sum()).round(3).to_dict(), "total $", round(t.usd.sum()))
    s = r[["pnl", "usdc_fill", "usdt", "tape", "tape_inside", "tape_book", "fill_inside", "fill_book", "fill_none"]].sum()
    print("totals over", len(r), "hours:", s.round(0).to_dict())
    print(f"simulated USDC fills / public tape = {s.usdc_fill / s.tape:.2f};  / book-resting tape (at_touch+through) = {s.usdc_fill / s.tape_book:.2f}")
    print(f"simulated USDC fill $ by trigger: inside-only {s.fill_inside / s.usdc_fill:.2f}, book or mixed {s.fill_book / s.usdc_fill:.2f}, no print found {s.fill_none / s.usdc_fill:.2f}")
    top = r.sort_values("pnl", ascending=False)
    print("pnl concentration: top 3 hours =", round(top.pnl.head(3).sum(), 2), "of", round(r.pnl.sum(), 2), "| hours with pnl > 0:", int((r.pnl > 0).sum()), "/", len(r))
    print("hours with < $1,000 of simulated USDC fills:", int((r.usdc_fill < 1000).sum()), "| median USDC fill $/h", round(r.usdc_fill.median()), "| mean", round(r.usdc_fill.mean()))


if __name__ == "__main__":
    main()
