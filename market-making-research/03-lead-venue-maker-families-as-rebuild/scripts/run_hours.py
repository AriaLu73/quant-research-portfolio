#!/usr/bin/env python3
"""research5: run one strategy over a list of one-hour slices with the project backtest engine, one slice at a time.

Thin wrapper around the same engine call as scripts/research2/run_panel.py (scenario file, fees, latency model come
from run_panel.scenario_for), with three differences: the engine's stdout is kept (the strategy prints its behaviour
counters there on stop), every slice is gated by the machine budget (scripts/research2/budget.py), and results go to
data/research5/runs/<tag>.json (one row per slice) so research2's files are not touched.

Matching and latency are fixed (user rulings 2026-09-30 and 2026-10-01: develop only at the colo latency): queue matching
with our order at the front (bias 1.0), 1.8 ms from market event to our order at the exchange (0.3 ms feed + 1.5 ms order).
There is no switch for the old "fill only when the price trades through" mode or for other latencies, on purpose.
--capital N (optional) runs the same scenario with a larger simulated account (default: the 500,000 of the base scenario).
It only moves the risk layer's "20 % of equity per contract" line (PT-05) out of the way for capacity tests with large
clips; the per-order limit (50,000, PT-01) and the position limit (500,000, PT-04) of config/backtest/risk_swap.yaml stay.
Fees: maker OUR_FEE for every contract inside the engine, taker OUR_FEE; the USDC leg actually earns OUR_FEE, so
net_corr = net + 0.5 bp x USDC fill notional.
Usage: python scripts/detach.py --log logs/r5_<tag>.log -- .venv/Scripts/python.exe scripts/research5/run_hours.py
           --tag T --strategy strategies/research5/mm_uh.py --params '{}' --manifest data/research2/btcusdc_sep_train32.json
"""
import argparse, json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research2"))
import run_panel as RP

RUNS = os.path.join(ROOT, "data", "research5", "runs")
COLO_LATENCY_NS = 1_800_000          # feed 0.3 ms + order 1.5 ms (measured on the colo instance)
QUEUE_BIAS = "1.0"                   # cancels at our price level are ahead of us: we are at the front of the queue


def wait_budget(first=False):
    """Wait for a free engine slot. Several chains share the machine (often a single slot): a chain that has just finished
    a slice steps back for a moment before asking again, and waiting chains ask every 10 s, so the slot goes round instead
    of staying with whoever holds it (2026-10-01: a queued chain got no slice in 11 minutes with the old 120 s poll)."""
    if not first:
        time.sleep(12)
    while subprocess.run([RP.PY, os.path.join("scripts", "research2", "budget.py"), "--need", "1"], cwd=ROOT, capture_output=True).returncode != 0:
        time.sleep(10)


def usdc_fill_usd(out_dir, sym):
    import pyarrow.parquet as pq
    p = os.path.join(out_dir, "fills.parquet")
    if not os.path.exists(p):
        return 0.0, 0
    t = pq.read_table(p, columns=["symbol", "price", "qty"]).to_pylist()
    v = [float(r["price"]) * float(r["qty"]) for r in t if r["symbol"] == sym]
    return sum(v), len(v)


def with_capital(scen, capital):
    """Copy of scenario `scen` with another simulated account size; returns the new scenario name."""
    src = open(os.path.join(ROOT, "config", "backtest", scen + ".yaml"), encoding="utf-8").read()
    name = f"{scen}_cap{capital}"
    lines = src.split(chr(10))
    assert lines.count(f"scenario: {scen}") == 1 and src.count('initial_capital: "500000"') == 1
    lines[lines.index(f"scenario: {scen}")] = f"scenario: {name}"
    y = chr(10).join(lines).replace('initial_capital: "500000"', f'initial_capital: "{capital}"')
    p = os.path.join(ROOT, "config", "backtest", name + ".yaml")
    if not os.path.exists(p) or open(p, encoding="utf-8").read() != y:
        with open(p, "wb") as fh:
            fh.write(y.encode("utf-8"))
    return name


def run_slice(feed, sym, start, end, strategy, params, tag, capital=None):
    scen = RP.scenario_for(feed, "OUR_FEE", COLO_LATENCY_NS, QUEUE_BIAS, "", 10_000_000, sym, "OUR_FEE")
    if capital:
        scen = with_capital(scen, capital)
    grid = {k: [v] for k, v in params.items()}
    grid["symbols"] = [sym]
    anchor = params.get("anchor_symbol", sym.split("-")[0] + "-USDT")
    grid["anchor_symbol"] = [anchor]
    run_tag = f"{tag}_{feed.replace('/', '_')}"
    cmd = [RP.PY, "-m", "engine.backtest.runner", "--scenario", scen, "--exchange", RP._exchange_of(feed), "--product", "swap_usdt",
           "--symbols", f"{sym},{anchor}", "--strategy", strategy, "--mode", "grid", "--param-grid", json.dumps(grid),
           "--run-tag", run_tag, "--start-ns", str(RP.ns_of(start)), "--end-ns", str(RP.ns_of(end)), "--integrity-check", "loose"]
    env = dict(os.environ, HFT_ENV="backtest", PYTHONPATH=ROOT, PYTHONIOENCODING="utf-8", HFT_BT_VIEW_LEVELS="5")
    env.pop("HFT_BT_THROUGH_ONLY", None)          # never inherit the old trade-through-only mode from the caller's environment
    out_dir = os.path.join(ROOT, "data", "backtest_results", f"{scen}_{run_tag}_0")
    if os.path.isdir(out_dir):
        # A finished run leaves a watermark; the engine then treats a new run into the same folder as already done
        # (0 events) and the old fills file stays (2026-10-02: a re-run of CAP_BTC_20000 reported the previous version's
        # fills with 0 orders). Always start a slice from an empty folder.
        import shutil
        shutil.rmtree(out_dir)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, timeout=6 * 3600)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    row = dict(feed=feed, sym=sym, out_dir=out_dir, elapsed=round(time.time() - t0))
    rep_path = os.path.join(out_dir, "report.json")
    if not os.path.exists(rep_path):
        row["error"] = out[-600:] + (proc.stderr or b"").decode("utf-8", "replace")[-600:]
        return row
    rep = json.load(open(rep_path, encoding="utf-8"))
    if not rep.get("events"):
        row["error"] = "engine processed 0 events"
        return row
    mm = rep.get("mm", {})
    usd, n = usdc_fill_usd(out_dir, sym)
    row.update(net=float(mm.get("pnl_total", 0)), vol=float(mm.get("volume_notional", 0)), fills=rep.get("fills"), usdc_usd=usd, usdc_fills=n,
               orders=rep.get("tracker_orders"), inv_end=float(mm.get("inventory_end_qty", 0)), blocked=rep.get("risk_blocked"),
               blocked_by=rep.get("risk_blocked_by_rule"))
    row["net_corr"] = row["net"] + 0.5e-4 * usd
    for line in out.splitlines():
        if line.startswith("UH_STATS "):
            import ast
            row["stats"] = ast.literal_eval(line[9:])
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--params", default="{}", help="JSON text or path of a JSON file")
    ap.add_argument("--manifest", required=True, help="JSON list [[feed, symbol, start_iso, end_iso], ...] (path) ")
    ap.add_argument("--only", default="", help="comma list of feed names to keep, e.g. ku_buy/20260918_13")
    ap.add_argument("--capital", type=int, default=0, help="simulated account size for capacity tests (0 = base scenario)")
    ns = ap.parse_args()
    params = json.load(open(os.path.join(ROOT, ns.params), encoding="utf-8")) if os.path.exists(os.path.join(ROOT, ns.params)) else json.loads(ns.params)
    jobs = json.load(open(os.path.join(ROOT, ns.manifest), encoding="utf-8"))
    if ns.only:
        keep = set(ns.only.split(","))
        jobs = [j for j in jobs if j[0] in keep]
    os.makedirs(RUNS, exist_ok=True)
    path = os.path.join(RUNS, ns.tag + ".json")
    rows = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    done = {r["feed"] for r in rows if "net" in r}
    first = True
    for feed, sym, s, e in jobs:
        if feed in done:
            continue
        wait_budget(first)
        first = False
        row = run_slice(feed, sym, s, e, ns.strategy, params, ns.tag, ns.capital or None)
        rows = [r for r in rows if r["feed"] != feed] + [row]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=1)
        print(time.strftime("%F %T"), feed, {k: row.get(k) for k in ("net_corr", "usdc_usd", "usdc_fills", "orders", "elapsed", "error")}, flush=True)
    print("DONE", ns.tag, flush=True)


if __name__ == "__main__":
    main()
