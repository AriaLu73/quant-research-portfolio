#!/usr/bin/env python3
"""用项目回测引擎(engine/backtest/runner,与实盘同一代码路径)按 1 小时切片跑策略,汇总 NET PNL。

切片清单 JSON:[[feed_root_rel, symbol, start_iso, end_iso], ...],feed_root_rel 相对 data/oos/。
场景:复制 config/backtest/glft_kucoin_colo.yaml(KuCoin OUR_FEE_TIER 费率、colo 延迟、L3 队列、撤单归因 0.5),仅改 feed_root。
用法:
  python scripts/research/run_slices.py --manifest data/research/train_slices.json --strategy strategies/research/mm_state_maker.py \
      --params-json '{"imb_post":"0.0"}' --tag v1 --workers 3
输出:data/research/runs/<tag>.json + 汇总打印(每切片 net/gross/fees/fills/vol/inventory/mdd)。
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
BASE_YAML = open(os.path.join(ROOT, "config", "backtest", "glft_kucoin_colo.yaml"), encoding="utf-8").read()


def ns_of(s: str) -> int:
    return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp() * 1_000_000_000)


def scenario_for(feed: str, fee_maker: str, latency_ns: int) -> str:
    name = "rs_" + feed.replace("/", "_") + f"_m{fee_maker.replace('-', 'n').replace('.', '')}_l{latency_ns // 1000}"
    y = BASE_YAML.replace("scenario: glft_kucoin_colo", f"scenario: {name}")
    y = y.replace("feed_root: data/oos/kucoin_day", f"feed_root: data/oos/{feed}")
    y = y.replace('commission: {maker: "OUR_FEE"', f'commission: {{maker: "{fee_maker}"')
    y = y.replace("mean_ns: 1500000, std_ns: 500000", f"mean_ns: {latency_ns}, std_ns: {latency_ns // 3}")
    p = os.path.join(ROOT, "config", "backtest", name + ".yaml")
    if not os.path.exists(p) or open(p, encoding="utf-8").read() != y:
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(y)
    return name


def run_one(job):
    feed, sym, s, e, strategy, params, tag, fee_maker, latency_ns = job
    scen = scenario_for(feed, fee_maker, latency_ns)
    grid = {k: [v] for k, v in params.items()}
    grid["symbols"] = [sym]
    run_tag = f"{tag}_{feed.replace('/', '_')}"
    cmd = [PY, "-m", "engine.backtest.runner", "--scenario", scen, "--exchange", "kucoin", "--product", "swap_usdt",
           "--symbols", sym, "--strategy", strategy, "--mode", "grid", "--param-grid", json.dumps(grid),
           "--run-tag", run_tag, "--start-ns", str(ns_of(s)), "--end-ns", str(ns_of(e)), "--integrity-check", "loose"]
    env = dict(os.environ, HFT_ENV="backtest", PYTHONPATH=ROOT, PYTHONIOENCODING="utf-8")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, timeout=4 * 3600)
    out_dir = os.path.join(ROOT, "data", "backtest_results", f"{scen}_{run_tag}_0")
    rep_path = os.path.join(out_dir, "report.json")
    row = dict(feed=feed, sym=sym, start=s, end=e, elapsed=round(time.time() - t0), out_dir=out_dir)
    if not os.path.exists(rep_path):
        row["error"] = (proc.stdout or b"").decode("utf-8", "replace")[-600:] + (proc.stderr or b"").decode("utf-8", "replace")[-400:]
        return row
    rep = json.load(open(rep_path, encoding="utf-8"))
    mm = rep.get("mm", {})
    row.update(events=rep.get("events"), fills=rep.get("fills"), net=float(mm.get("pnl_total", 0)), gross=float(mm.get("spread_pnl", 0)),
               fees=float(mm.get("fee_net", 0)), vol=float(mm.get("volume_notional", 0)), maker_ratio=mm.get("maker_ratio"),
               inv_peak=float(mm.get("inventory_peak_qty", 0)), inv_end=float(mm.get("inventory_end_qty", 0)),
               capture=mm.get("capture_rate"), blocked=rep.get("risk_blocked"), blocked_by=rep.get("risk_blocked_by_rule"),
               max_drawdown=rep.get("max_drawdown"), sharpe=rep.get("sharpe"))
    # 最大回撤($):按权益曲线
    try:
        import pyarrow.parquet as pq
        eq = pq.read_table(os.path.join(out_dir, "equity_curve.parquet")).to_pandas()
        col = [c for c in eq.columns if c != "ts_ns"][0]
        v = eq[col].astype(float).values
        peak = v[0]; mdd = 0.0
        for x in v:
            peak = max(peak, x); mdd = max(mdd, peak - x)
        row["mdd_usd"] = float(mdd)
    except Exception:
        row["mdd_usd"] = None
    row["net_bp"] = (row["net"] / row["vol"] * 1e4) if row["vol"] else 0.0
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--params-json", default="{}")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--fee-maker", default="OUR_FEE")
    ap.add_argument("--latency-ns", type=int, default=1500000)
    ns = ap.parse_args()
    sl = json.load(open(ns.manifest, encoding="utf-8"))
    params = json.loads(ns.params_json)
    jobs = [(f, s, a, b, ns.strategy, params, ns.tag, ns.fee_maker, ns.latency_ns) for f, s, a, b in sl]
    rows = []
    t0 = time.time()
    with ThreadPoolExecutor(ns.workers) as ex:
        for row in ex.map(run_one, jobs):
            rows.append(row)
            if "error" in row:
                print(f"ERR {row['feed']} {row['start']}: {row['error'][-300:]}", flush=True)
            else:
                print(f"{row['feed']:<20} {row['start'][:13]} fills {row['fills']:>5} vol ${row['vol']:>10,.0f} gross {row['gross']:>+8.2f} fees {row['fees']:>+7.2f} "
                      f"net {row['net']:>+8.2f} ({row['net_bp']:+.3f}bp) invpk {row['inv_peak']:.3f} end {row['inv_end']:+.3f} mdd {row['mdd_usd'] if row['mdd_usd'] is None else round(row['mdd_usd'], 1)} blocked {row['blocked']} {row['elapsed']}s", flush=True)
    os.makedirs(os.path.join(ROOT, "data", "research", "runs"), exist_ok=True)
    out = os.path.join(ROOT, "data", "research", "runs", f"{ns.tag}.json")
    json.dump({"strategy": ns.strategy, "params": params, "fee_maker": ns.fee_maker, "latency_ns": ns.latency_ns, "rows": rows},
              open(out, "w", encoding="utf-8"), indent=1, default=str)
    ok = [r for r in rows if "net" in r]
    if ok:
        vol = sum(r["vol"] for r in ok); net = sum(r["net"] for r in ok); gross = sum(r["gross"] for r in ok); fees = sum(r["fees"] for r in ok)
        nets = sorted(r["net"] for r in ok)
        print(f"\n=== {ns.tag}: {len(ok)} slices, fills {sum(r['fills'] for r in ok)}, vol ${vol:,.0f}, gross {gross:+.2f} ({gross / vol * 1e4 if vol else 0:+.3f}bp), "
              f"fees {fees:+.2f}, net {net:+.2f} ({net / vol * 1e4 if vol else 0:+.3f}bp); positive slices {sum(n > 0 for n in nets)}/{len(nets)}; "
              f"mean {net / len(ok):+.2f} median {nets[len(nets) // 2]:+.2f} worst {nets[0]:+.2f} best {nets[-1]:+.2f}; {round(time.time() - t0)}s")
    print("saved", out)


if __name__ == "__main__":
    main()
