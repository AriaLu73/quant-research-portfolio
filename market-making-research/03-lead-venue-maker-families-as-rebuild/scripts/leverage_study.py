#!/usr/bin/env python3
"""research5: what leverage does to a result set of the USDC-maker / USDT-hedge strategy (read-only).

The two legs sit in two separate margin wallets on KuCoin (USDC-margined and USDT-margined contracts): a gain on one
leg cannot pay for a loss on the other. So the quantity that matters for leverage is per wallet:
  peak notional of the leg          -> margin it needs = notional / leverage
  worst mark-to-market loss of the leg alone inside a slice (its fills marked at its own mid on a 1 s grid, fees ignored)
  BTC move that would empty the wallet at the peak position: wallet equity / peak notional (before maintenance margin)
Combined: net P&L of the slice, worst combined drawdown, largest unhedged net position.
Usage: python scripts/research5/leverage_study.py TAG [TAG ...] [--capital 10000] [--leverage 5]     (Python314)
"""
import json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research2"))


def leg_paths(fills, grid, ts, mid):
    """fills: [(ts_ns, signed_qty, price)] of one leg; grid: ns times; (ts, mid): the leg's mid series.
    Returns (position in coin, mark-to-market P&L in quote) on the grid; fees are not included."""
    f = sorted(fills)
    ft = np.array([x[0] for x in f], dtype=np.int64)
    q = np.cumsum([x[1] for x in f]) if f else np.zeros(0)
    cash = np.cumsum([-x[1] * x[2] for x in f]) if f else np.zeros(0)
    i = np.searchsorted(ft, grid, side="right") - 1
    pos = np.where(i >= 0, q[np.clip(i, 0, None)] if len(q) else 0.0, 0.0) if len(q) else np.zeros(len(grid))
    csh = np.where(i >= 0, cash[np.clip(i, 0, None)] if len(cash) else 0.0, 0.0) if len(cash) else np.zeros(len(grid))
    m = mid[np.clip(np.searchsorted(ts, grid, side="right") - 1, 0, len(mid) - 1)]
    return pos, csh + pos * m, m


def max_drawdown(x):
    """Largest fall from a running peak (>= 0)."""
    return float(np.max(np.maximum.accumulate(x) - x)) if len(x) else 0.0


def main():
    import run_panel as RP
    args = sys.argv[1:]
    cap = float(args[args.index("--capital") + 1]) if "--capital" in args else 10000.0
    lev = float(args[args.index("--leverage") + 1]) if "--leverage" in args else 5.0
    tags = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1].startswith("--"))]
    wallet = cap / 2.0
    print(f"capital ${cap:,.0f} split evenly: ${wallet:,.0f} per wallet; at {lev:g}x each leg may hold up to ${wallet * lev:,.0f} notional")
    for tag in tags:
        rows = [r for r in json.load(open(os.path.join(ROOT, "data", "research5", "runs", tag + ".json"), encoding="utf-8")) if "net" in r]
        pk = {"usdc": [], "usdt": []}
        dd = {"usdc": [], "usdt": [], "both": []}
        lows, net_unh, nets, held = {"usdc": [], "usdt": []}, [], [], []
        for r in rows:
            anchor = r["sym"].split("-")[0] + "-USDT"
            orders, fills = {}, {"usdc": [], "usdt": []}
            with open(os.path.join(r["out_dir"], "broker_sim_wal.jsonl"), encoding="utf-8") as fh:
                for line in fh:
                    m = json.loads(line)
                    if m["t"] == "order":
                        orders[m["id"]] = ("usdt" if m["symbol"] == anchor else "usdc", 1.0 if m["side"] == "buy" else -1.0)
                    elif m["t"] == "fill" and m["id"] in orders:
                        leg, sg = orders[m["id"]]
                        fills[leg].append((m["ts_ns"], sg * float(m["qty"]), float(m["px"])))
            nets.append(r["net_corr"])
            if not fills["usdc"]:
                continue
            tsu, midu = RP.mid_series(r["feed"], r["sym"])
            tst, midt = RP.mid_series(r["feed"], anchor)
            grid = np.arange(int(tst[0]), int(tst[-1]), 1_000_000_000, dtype=np.int64)
            pu, vu, mu = leg_paths(fills["usdc"], grid, tsu, midu)
            pt, vt, mt = leg_paths(fills["usdt"], grid, tst, midt)
            pk["usdc"].append(float(np.max(np.abs(pu) * mu)))
            pk["usdt"].append(float(np.max(np.abs(pt) * mt)))
            dd["usdc"].append(max_drawdown(vu)); dd["usdt"].append(max_drawdown(vt)); dd["both"].append(max_drawdown(vu + vt))
            lows["usdc"].append(float(np.min(vu))); lows["usdt"].append(float(np.min(vt)))
            net_unh.append(float(np.max(np.abs(pu + pt) * mt)))
            held.append(float(np.mean(np.abs(pu) * mu)))
        if not pk["usdc"]:
            print(tag, "no fills")
            continue
        peak = max(max(pk["usdc"]), max(pk["usdt"]))
        print(f"\n{tag}: {len(rows)} h, {len(pk['usdc'])} with fills; net ${sum(nets):.2f}; worst hour ${min(nets):.2f}")
        print(f"  peak leg notional: USDC ${max(pk['usdc']):,.0f}  USDT ${max(pk['usdt']):,.0f}   (median of active hours ${np.median(pk['usdc']):,.0f}; average held ${np.mean(held):,.0f})")
        print(f"  margin needed at {lev:g}x for the peak: ${peak / lev:,.0f} per wallet = {peak / lev / wallet:.0%} of the wallet")
        print(f"  largest unhedged net position ${max(net_unh):,.0f}")
        print(f"  worst loss of one leg alone inside an hour (mark-to-market, what its wallet must absorb): USDC ${-min(lows['usdc']):,.2f}  USDT ${-min(lows['usdt']):,.2f}"
              f"  = {max(-min(lows['usdc']), -min(lows['usdt'])) / wallet:.2%} of the wallet")
        print(f"  worst drawdown inside an hour: USDC leg ${max(dd['usdc']):,.2f}  USDT leg ${max(dd['usdt']):,.2f}  both legs together ${max(dd['both']):,.2f}")
        print(f"  BTC move that empties a wallet at the peak position (before maintenance margin): {wallet / peak:.1%}")


if __name__ == "__main__":
    main()
