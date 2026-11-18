"""V_LO 汇总:按 config/splits/<sym>.yaml 的 train 区间过滤 _tmp/vlo/<sym>_*.npz,
报前 5 档新挂单张数的中位数 / 均值 / p25 / p75 / p99 与美元折算。
用法  python vlo_aggregate.py <sym>[,<sym>...]   → reports/step00/vlo_<sym>.json + 汇总表 reports/step00/vlo.md(追加)
"""
import glob
import json
import os
import sys

import numpy as np
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine_bridge as B   # noqa: E402

VLO = os.path.join(B.REPRO, "_tmp", "vlo")
REP = os.path.join(B.REPRO, "reports", "step00")


def train_intervals(sym):
    with open(os.path.join(B.REPRO, "config", "splits", f"{sym}.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return [(x["start_ns"], x["end_ns"]) for x in cfg["split"]["train"]["intervals"]]


def in_intervals(ts, iv):
    m = np.zeros(len(ts), bool)
    for a, b in iv:
        m |= (ts >= a) & (ts < b)
    return m


def pct(x, k):
    return float(np.percentile(x, k)) if len(x) else float("nan")


def run(sym):
    c = B.CONTRACTS[sym]
    iv = train_intervals(sym)
    rows = []
    for p in sorted(glob.glob(os.path.join(VLO, f"{sym}_*.npz"))):
        r = np.load(p)["rows"]
        if len(r):
            rows.append(r[in_intervals(r[:, 0], iv)])
    r = np.concatenate(rows) if rows else np.zeros((0, 5), np.int64)
    allr = r[r[:, 4] >= 1]
    top = r[(r[:, 4] >= 1) & (r[:, 4] <= 5)]
    px = top[:, 2] * float(c["tick"]) if len(top) else np.zeros(0)
    usd = top[:, 3] * float(c["mult"]) * px
    med = pct(top[:, 3], 50)
    out = dict(sym=sym, train_hours=sum(b - a for a, b in iv) / 3.6e12, hours_files=len(rows),
               n_open_train=int(len(allr)), n_open_top5=int(len(top)), share_top5=float(len(top) / max(len(allr), 1)),
               size_contracts=dict(median=med, mean=float(top[:, 3].mean()) if len(top) else float("nan"),
                                   p25=pct(top[:, 3], 25), p75=pct(top[:, 3], 75), p99=pct(top[:, 3], 99)),
               size_coin_median=med * float(c["mult"]), usd_median=pct(usd, 50),
               usd_mean=float(usd.mean()) if len(usd) else float("nan"),
               by_rank_median={int(k): float(np.median(top[top[:, 4] == k, 3])) for k in range(1, 6) if (top[:, 4] == k).any()},
               all_ranks_median=pct(allr[:, 3], 50),
               V_LO=dict(x0_5=int(round(med * 0.5)), x1=int(round(med)), x2=int(round(med * 2))))
    os.makedirs(REP, exist_ok=True)
    with open(os.path.join(REP, f"vlo_{sym}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    syms = sys.argv[1].split(",")
    res = [run(s) for s in syms]
    lines = ["# V_LO 标定(train 区间,L3 新挂单落在同侧前 5 个占用价位;EC-04)", "",
             "| 合约 | train 小时 | 新挂单数 | 前5档占比 | 中位数(张) | 均值 | p25 | p75 | p99 | 中位数折币 | 中位数折美元 | V_LO ×0.5/×1/×2 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for o in res:
        s = o["size_contracts"]
        lines.append("| {sym} | {th:.1f} | {n:,} | {sh:.1%} | {med:.0f} | {mean:.1f} | {p25:.0f} | {p75:.0f} | {p99:.0f} | {coin:.4f} | ${usd:,.0f} | {a} / {b} / {c} |".format(
            sym=o["sym"], th=o["train_hours"], n=o["n_open_train"], sh=o["share_top5"], med=s["median"], mean=s["mean"],
            p25=s["p25"], p75=s["p75"], p99=s["p99"], coin=o["size_coin_median"], usd=o["usd_median"],
            a=o["V_LO"]["x0_5"], b=o["V_LO"]["x1"], c=o["V_LO"]["x2"]))
    with open(os.path.join(REP, "vlo.md"), "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
