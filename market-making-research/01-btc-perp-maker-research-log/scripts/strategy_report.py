#!/usr/bin/env python3
"""策略报告(prompt §28/§35/§36):从 run_slices 结果 JSON + 引擎 fills.parquet + 研究因子 mid 序列,
计算 Net PnL、逐小时统计、Sharpe、回撤、fill rate、realized spread、adverse selection(markout)、库存、费用。
用法:python scripts/research/strategy_report.py --run data/research/runs/<tag>.json [--baseline data/research/runs/<tag>.json] --label "训练面板"
输出:markdown 片段到 stdout(由 research 文档汇编)+ JSON。
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FOUT = os.path.join(ROOT, "data", "research", "factors")
_MID_CACHE = {}


def _mid(day):
    if day not in _MID_CACHE:
        f = pq.read_table(os.path.join(FOUT, f"{day}.parquet"), columns=["ts", "mid"]).to_pandas()
        _MID_CACHE[day] = (f["ts"].values.astype(np.int64), f["mid"].values.astype(np.float64))
    return _MID_CACHE[day]


def slice_metrics(row):
    out = dict(row)
    fp = os.path.join(row["out_dir"], "fills.parquet")
    day = row["feed"].split("/")[1].split("_")[0]
    ts, mid = _mid(day)
    n = len(ts)
    if os.path.exists(fp):
        e = pq.read_table(fp).to_pandas()
        e = e[e["strategy"] != "__funding__"]
        t = e["ts_ns"].astype(np.int64).values // 1000
        px = e["price"].astype(float).values
        q = e["qty"].astype(float).values
        sd = np.where(e["side"].values == "buy", 1.0, -1.0)
        k0 = np.maximum(np.searchsorted(ts, t, "left") - 1, 0)
        out["realized_spread_bp"] = float(np.average(sd * (mid[k0] - px) / px * 1e4, weights=q)) if len(q) else 0.0
        for h in (500, 5000, 30000):
            kk = np.minimum(np.searchsorted(ts, t + h * 1000, "left"), n - 1)
            out[f"markout_{h}ms_bp"] = float(np.average(sd * (mid[kk] - px) / px * 1e4, weights=q)) if len(q) else 0.0
        out["adverse_selection_bp"] = -out["markout_5000ms_bp"]
        pos = np.cumsum(sd * q)
        out["inv_mean"] = float(np.mean(np.abs(pos))) if len(pos) else 0.0
        out["inv_std"] = float(np.std(pos)) if len(pos) else 0.0
        out["inv_max"] = float(np.max(np.abs(pos))) if len(pos) else 0.0
        out["maker_fills"] = int(e["maker"].sum())
        out["fill_qty_btc"] = float(q.sum())
    else:
        out.update(realized_spread_bp=0.0, markout_500ms_bp=0.0, markout_5000ms_bp=0.0, markout_30000ms_bp=0.0,
                   adverse_selection_bp=0.0, inv_mean=0.0, inv_std=0.0, inv_max=0.0, maker_fills=0, fill_qty_btc=0.0)
    rep = json.load(open(os.path.join(row["out_dir"], "report.json"), encoding="utf-8"))
    out["orders"] = rep.get("tracker_orders", 0)
    out["fill_rate"] = (row["fills"] / out["orders"]) if out["orders"] else 0.0
    out["rebates"] = -row["fees"] if row["fees"] < 0 else 0.0
    out["fees_paid"] = row["fees"] if row["fees"] > 0 else 0.0
    return out


def summarize(rows):
    ok = [r for r in rows if "net" in r]
    nets = np.array([r["net"] for r in ok])
    vol = sum(r["vol"] for r in ok)
    s = dict(n_slices=len(ok), total_net=float(nets.sum()), avg_hourly=float(nets.mean()), median_hourly=float(np.median(nets)),
             worst_hourly=float(nets.min()), best_hourly=float(nets.max()), positive_slices=int((nets > 0).sum()),
             sharpe_hourly=float(nets.mean() / nets.std() * np.sqrt(len(nets))) if len(nets) > 1 and nets.std() > 0 else 0.0,
             max_drawdown=float(max(r.get("mdd_usd") or 0 for r in ok)), vol=vol, fills=sum(r["fills"] for r in ok),
             gross=sum(r["gross"] for r in ok), fees=sum(r["fees"] for r in ok),
             net_bp=(nets.sum() / vol * 1e4) if vol else 0.0,
             fill_rate=float(np.mean([r["fill_rate"] for r in ok])),
             realized_spread_bp=float(np.average([r["realized_spread_bp"] for r in ok], weights=[max(r["vol"], 1) for r in ok])),
             adverse_selection_bp=float(np.average([r["adverse_selection_bp"] for r in ok], weights=[max(r["vol"], 1) for r in ok])),
             markout_500ms_bp=float(np.average([r["markout_500ms_bp"] for r in ok], weights=[max(r["vol"], 1) for r in ok])),
             markout_30000ms_bp=float(np.average([r["markout_30000ms_bp"] for r in ok], weights=[max(r["vol"], 1) for r in ok])),
             inv_mean=float(np.mean([r["inv_mean"] for r in ok])), inv_std=float(np.mean([r["inv_std"] for r in ok])),
             inv_max=float(max(r["inv_max"] for r in ok)), rebates=sum(r["rebates"] for r in ok), fees_paid=sum(r["fees_paid"] for r in ok))
    return s


def md_summary(label, s):
    return "\n".join([
        f"**{label}**({s['n_slices']} 个 1h 切片)", "",
        "| 指标 | 值 |", "|---|---|",
        f"| Total Net PnL | ${s['total_net']:+.2f}({s['net_bp']:+.3f} bp / 流水 ${s['vol']:,.0f}) |",
        f"| Average / Median / Worst / Best Hourly Net | ${s['avg_hourly']:+.2f} / ${s['median_hourly']:+.2f} / ${s['worst_hourly']:+.2f} / ${s['best_hourly']:+.2f} |",
        f"| Positive slices | {s['positive_slices']}/{s['n_slices']} |",
        f"| Sharpe(hourly, annualization-free √n) | {s['sharpe_hourly']:.2f} |",
        f"| Max Drawdown(单切片最大,$) | {s['max_drawdown']:.2f} |",
        f"| Fills / Fill Rate(fills/orders) | {s['fills']} / {s['fill_rate']:.3f} |",
        f"| Realized Spread(bp,成交价 vs 成交时 mid) | {s['realized_spread_bp']:+.3f} |",
        f"| Adverse Selection(bp,−5s markout;500ms / 30s markout) | {s['adverse_selection_bp']:+.3f}({s['markout_500ms_bp']:+.3f} / {s['markout_30000ms_bp']:+.3f}) |",
        f"| Inventory mean / std / max(BTC) | {s['inv_mean']:.3f} / {s['inv_std']:.3f} / {s['inv_max']:.3f} |",
        f"| Gross(spread pnl)/ Rebates / Fees paid / Slippage | ${s['gross']:+.2f} / ${s['rebates']:+.2f} / ${s['fees_paid']:.2f} / 0(post_only,无 taker) |",
    ])


def md_slices(rows):
    L = ["| slice | start | end | Net | Gross | Fees | Fills | Fill rate | Inv max | MDD | AS 5s bp |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "net" not in r:
            L.append(f"| {r['feed']} | {r['start']} | {r['end']} | ERROR | | | | | | | |")
            continue
        L.append(f"| {r['feed']} | {r['start']} | {r['end']} | {r['net']:+.2f} | {r['gross']:+.2f} | {r['fees']:+.2f} | {r['fills']} | {r['fill_rate']:.3f} | {r['inv_max']:.3f} | {r['mdd_usd']:.1f} | {r['adverse_selection_bp']:+.3f} |")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default="")
    ns = ap.parse_args()
    R = json.load(open(ns.run, encoding="utf-8"))
    rows = [slice_metrics(r) if "net" in r else r for r in R["rows"]]
    s = summarize(rows)
    md = md_summary(ns.label or os.path.basename(ns.run), s) + "\n\n" + md_slices(rows) + "\n"
    print(md)
    out = ns.out or ns.run.replace(".json", "_metrics.json")
    json.dump({"summary": s, "rows": rows, "params": R.get("params"), "strategy": R.get("strategy")}, open(out, "w", encoding="utf-8"), indent=1, default=float)


if __name__ == "__main__":
    main()
