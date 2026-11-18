"""Step 1 验证:按 UTC 日、按 Δt 报到达频率 / 联合到达频率 / 成交量分布,外加方向检查与时间因果检查(任务书 Step 1)。
输入  data/step01/<sym>/<day>_<hh>.npz(ladder_store)
输出  reports/step01/validate_<sym>.csv(每日 × Δt 一行)、reports/step01/validate_<sym>.md(按来源汇总)、
      reports/step01/events_1s_<sym>_<day>.csv(一天的按秒事件序列样例)
用法  python step01_validate.py <sym> [dt_ms 列表,默认 100,250,500,1000,2000]
"""
import csv
import datetime as dt
import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台 gbk 会在打印表格时崩

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "data"))
import events as EV              # noqa: E402
import ladder_store as LS        # noqa: E402

NS = 1_000_000_000
D01 = os.path.join(REPRO, "data", "step01")
REP = os.path.join(REPRO, "reports", "step01")


def day_bounds(day):
    t = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    return t, t + 86400 * NS


def days_of(sym):
    out = {}
    for p in sorted(glob.glob(os.path.join(D01, sym, "*.npz"))):
        day = os.path.basename(p)[:8]
        out.setdefault(day, []).append(p)
    return out


def direction_check(lads):
    """L3:买 MO 首笔 tick 应 = 到达前卖一(引擎口径下恒等);L2:报 at_best / inside / through 占比。"""
    side = np.concatenate([d["sw_side"] for d in lads if len(d["sw_side"])]).astype(int) if any(len(d["sw_side"]) for d in lads) else np.zeros(0, int)
    if len(side) == 0:
        return dict(n=0)
    first = np.concatenate([d["sw_first"] for d in lads if len(d["sw_first"])])
    best = np.concatenate([d["sw_lad"][:, 0, 0] for d in lads if len(d["sw_lad"])]).astype(np.int64)
    has = best > 0
    at = ((side == 0) & (first == best)) | ((side == 1) & (first == best))
    through = ((side == 0) & (first > best)) | ((side == 1) & (first < best))
    inside = ((side == 0) & (first < best)) | ((side == 1) & (first > best))
    return dict(n=int(len(side)), no_pre_ladder=int((~has).sum()), at_best=float((at & has).sum() / max(has.sum(), 1)),
                through=float((through & has).sum() / max(has.sum(), 1)), inside=float((inside & has).sum() / max(has.sum(), 1)))


def run(sym, dts):
    os.makedirs(REP, exist_ok=True)
    rows, by_src = [], {}
    sample_written = False
    for day, files in days_of(sym).items():
        lads = [LS.load(p, keys=LS.LIGHT_KEYS + ("sw_lad",)) for p in files]
        src = lads[0]["meta"]["src"]
        d0, d1 = day_bounds(day)
        dchk = direction_check(lads)
        # 时间因果:边界记录时刻 ≤ 之后第一条消息时刻由钩子保证;这里核对边界在 50 ms 网格上、单调、无重复
        bts = np.concatenate([d["bnd_ts"] for d in lads if len(d["bnd_ts"])])
        causal = dict(bnd_on_grid=bool(np.all(bts % (LS.GRID_MS * 1_000_000) == 0)), bnd_monotonic=bool(np.all(np.diff(bts) > 0)))
        for dt_ms in dts:
            try:
                fr = EV.build(lads, dt_ms, t_start=d0, t_end=d1)
            except ValueError:
                continue
            v = EV.validate(fr)
            cov = float((~fr.gap).mean())
            row = dict(sym=sym, src=src, day=day, hours=len(files), dt_ms=dt_ms, coverage=round(cov, 4), **{k: v[k] for k in
                       ("n_intervals", "n_gap", "pi_plus", "pi_minus", "pi_11", "pi_11_if_indep", "P00", "P10", "P01", "P11", "share_no_mo", "n_mo_per_interval_max")},
                       n_mo_buy=int(fr.n_plus.sum()), n_mo_sell=int(fr.n_minus.sum()),
                       vol_buy_p50=(v["vol_plus_pct"] or {}).get(50), vol_buy_p99=(v["vol_plus_pct"] or {}).get(99),
                       vol_sell_p50=(v["vol_minus_pct"] or {}).get(50), vol_sell_p99=(v["vol_minus_pct"] or {}).get(99),
                       dir_n=dchk.get("n"), dir_at_best=dchk.get("at_best"), dir_inside=dchk.get("inside"), dir_through=dchk.get("through"),
                       **causal)
            rows.append(row)
            by_src.setdefault((src, dt_ms), []).append(row)
            if dt_ms == 1000 and not sample_written and src == "l3":
                with open(os.path.join(REP, f"events_1s_{sym}_{day}.csv"), "w", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    w.writerow(["t_k_utc", "ind_plus", "ind_minus", "vol_plus", "vol_minus", "n_plus", "n_minus", "mid2", "gap"])
                    for i in range(min(len(fr), 7200)):
                        w.writerow([dt.datetime.fromtimestamp(fr.t0[i] / 1e9, dt.timezone.utc).strftime("%H:%M:%S"), int(fr.ind_plus[i]), int(fr.ind_minus[i]),
                                    int(fr.vol_plus[i]), int(fr.vol_minus[i]), int(fr.n_plus[i]), int(fr.n_minus[i]), int(fr.mid2[i]), int(fr.gap[i])])
                sample_written = True
        print(f"{sym} {day} {src} hours={len(files)} dir={dchk}", flush=True)
    with open(os.path.join(REP, f"validate_{sym}.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    md = [f"# Step 1 验证 —— {sym}", "", "按来源 × Δt 汇总(各日按非缺口区间数加权):", "",
          "| 来源 | Δt ms | 天数 | 区间数 | 缺口占比 | π⁺ | π⁻ | π(1,1) | π⁺π⁻ | 无 MO 区间 | MO/区间 max | 买 MO 数 | 卖 MO 数 | 买 MO 量 p50/p99(张) | 方向:首笔=最优 / 之间 / 穿过 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (src, dt_ms), rs in sorted(by_src.items()):
        n = np.array([r["n_intervals"] - r["n_gap"] for r in rs], float)
        wavg = lambda k: float(np.nansum([r[k] * ni for r, ni in zip(rs, n)]) / max(n.sum(), 1))
        p50 = np.nanmedian([r["vol_buy_p50"] for r in rs if r["vol_buy_p50"] is not None]) if any(r["vol_buy_p50"] is not None for r in rs) else float("nan")
        p99 = np.nanmedian([r["vol_buy_p99"] for r in rs if r["vol_buy_p99"] is not None]) if any(r["vol_buy_p99"] is not None for r in rs) else float("nan")
        dn = sum(r["dir_n"] or 0 for r in rs)
        dirs = "/".join(f"{np.nansum([(r[k] or 0) * (r['dir_n'] or 0) for r in rs]) / max(dn, 1):.1%}" for k in ("dir_at_best", "dir_inside", "dir_through"))
        md.append(f"| {src} | {dt_ms} | {len(rs)} | {int(n.sum()):,} | {1 - n.sum() / max(sum(r['n_intervals'] for r in rs), 1):.1%} | {wavg('pi_plus'):.4f} | {wavg('pi_minus'):.4f} | "
                  f"{wavg('pi_11'):.5f} | {wavg('pi_11_if_indep'):.5f} | {wavg('share_no_mo'):.3f} | {max(r['n_mo_per_interval_max'] for r in rs)} | "
                  f"{sum(r['n_mo_buy'] for r in rs):,} | {sum(r['n_mo_sell'] for r in rs):,} | {p50:.0f} / {p99:.0f} | {dirs} |")
    md += ["", "时间因果检查:边界全部在 50 ms 网格上且单调 = " + str(all(r["bnd_on_grid"] and r["bnd_monotonic"] for r in rows)),
           "MO 笔数在五个 Δt 下守恒 = " + str(all(len({(r["n_mo_buy"], r["n_mo_sell"]) for r in rows if r["day"] == d} ) == 1 for d in {r["day"] for r in rows})),
           "", "每日明细见 validate_<sym>.csv;按秒事件序列样例 events_1s_<sym>_<day>.csv。"]
    with open(os.path.join(REP, f"validate_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    sym = sys.argv[1]
    dts = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [100, 250, 500, 1000, 2000]
    run(sym, dts)
