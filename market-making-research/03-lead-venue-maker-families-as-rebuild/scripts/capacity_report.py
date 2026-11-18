#!/usr/bin/env python3
"""research5 UH-C1: capacity table - one row per (contract, clip) result set on the same 32 training hours.

Columns: clip, net $, net per hour, USDC fill $, share of the real public taker flow of the contract in those hours
(prints at or through the touch; self-trades inside the spread excluded), net bp per USDC $, peak leg position $,
orders refused by the risk layer, peak 30 s message weight. "marginal" = extra net per extra $1,000 of clip vs the row above.
Real flow per contract is measured once with u15_fill_audit.tape_with_book and cached in data/research5/real_flow_train32.json.
Usage: python scripts/research5/capacity_report.py BTC=UH2h_c2500_train32:2500,UH2h_train32:5000,CAP_BTC_10000:10000 XRP=...   (Python314)
"""
import json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research2"))
CACHE = os.path.join(ROOT, "data", "research5", "real_flow_train32.json")


def real_flow(sym, feeds):
    """Real taker $ (at-touch + through-the-book prints) of `sym` summed over the slices in feeds; cached per contract."""
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    key = sym + "|" + str(len(feeds))
    if key not in cache:
        import u15_fill_audit as A
        tot = 0.0
        for feed in feeds:
            day = feed.split("/")[1][:8]
            d = os.path.join(ROOT, "data", "oos", feed, "kucoin", "swap", sym, "feed_raw")
            t = A.tape_with_book(d, day)
            tot += float(t.usd[t.cls.isin(["at_touch", "through"])].sum()) if len(t) else 0.0
        cache[key] = tot
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=1)
    return cache[key]


def row_for(tag, clip):
    import behaviour_audit as B, leverage_study as L, run_panel as RP
    rows = [r for r in json.load(open(os.path.join(ROOT, "data", "research5", "runs", tag + ".json"), encoding="utf-8")) if "net" in r]
    if not rows:
        return None
    sym = rows[0]["sym"]
    anchor = sym.split("-")[0] + "-USDT"
    peak, w30 = 0.0, 0
    for r in rows:
        a = B.audit_dir(r["out_dir"], anchor)
        w30 = max(w30, a["peak_w30"])
        if r["usdc_fills"]:
            fills = []
            with open(os.path.join(r["out_dir"], "broker_sim_wal.jsonl"), encoding="utf-8") as fh:
                orders = {}
                for line in fh:
                    m = json.loads(line)
                    if m["t"] == "order" and m["symbol"] == sym:
                        orders[m["id"]] = 1.0 if m["side"] == "buy" else -1.0
                    elif m["t"] == "fill" and m["id"] in orders:
                        fills.append((m["ts_ns"], orders[m["id"]] * float(m["qty"]), float(m["px"])))
            q = np.cumsum([f[1] for f in sorted(fills)])
            peak = max(peak, float(np.max(np.abs(q))) * fills[-1][2])
    net = sum(r["net_corr"] for r in rows)
    usdc = sum(r["usdc_usd"] for r in rows)
    return dict(tag=tag, sym=sym, clip=clip, hours=len(rows), net=net, usdc=usdc, real=real_flow(sym, [r["feed"] for r in rows]),
                bp=net / usdc * 1e4 if usdc else 0.0, peak=peak, blocked=sum(r.get("blocked") or 0 for r in rows), w30=w30,
                pos=sum(1 for r in rows if r["net_corr"] > 0), neg=sum(1 for r in rows if r["net_corr"] < 0), worst=min(r["net_corr"] for r in rows))


def main():
    for arg in sys.argv[1:]:
        coin, spec = arg.split("=")
        rows = []
        for item in spec.split(","):
            tag, clip = item.split(":")
            if os.path.exists(os.path.join(ROOT, "data", "research5", "runs", tag + ".json")):
                r = row_for(tag, float(clip))
                if r:
                    rows.append(r)
        rows.sort(key=lambda r: r["clip"])
        print(f"\n{coin}  (real public taker flow in these hours: ${rows[0]['real']:,.0f})" if rows else f"\n{coin}: no results yet")
        print("    clip   hours     net $   $/hour   USDC fill $  share of real flow  bp per USDC$  +/- hours  worst h   peak position $  blocked  peak w30   marginal $ per +$1k clip")
        prev = None
        for r in rows:
            marg = (r["net"] - prev["net"]) / ((r["clip"] - prev["clip"]) / 1000) if prev and r["hours"] == prev["hours"] else float("nan")
            print(f"  {r['clip']:6.0f}   {r['hours']:5d}  {r['net']:8.2f}  {r['net'] / r['hours']:7.2f}  {r['usdc']:12,.0f}  {r['usdc'] / r['real']:17.1%}  {r['bp']:12.2f}  "
                  f"{r['pos']:3d}/{r['neg']:<3d}  {r['worst']:7.2f}  {r['peak']:15,.0f}  {r['blocked']:7d}  {r['w30']:8d}   {marg:10.2f}")
            prev = r


if __name__ == "__main__":
    main()
