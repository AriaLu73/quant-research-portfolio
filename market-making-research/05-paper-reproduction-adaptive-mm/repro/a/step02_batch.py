"""Step 2 + 3 批跑:每个 (合约, Δt, 日) 估计逐区间 (c^±, p^±),存 data/step02/<sym>/dt<ms>/<day>.npz;每日矩与 Table 1 结构检查存 reports/step02。
两遍法(EC-09)  第一遍只在 9 月训练日(config/train_days.yaml)累计 reach 表(按档位序号),第二遍对全部日用固定表估计。
               reach 表固定取自 9 月 20 天(= 第一个测试日的训练窗;后续窗口移动几天,表几乎不变),存 reports/step02/reach_<sym>_dt<ms>.json。
用法  python step02_batch.py <sym> <V_LO> [dt_ms,...] [--grid levels|ticks] [--weights reach_freq|inv_dist|uniform] [--vl at_t0|per_mo] [--cap per_mo|interval] [--tag name]
"""
import datetime as dt
import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台 gbk 会在打印表格时崩

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "data"))
import demand as DM              # noqa: E402
import events as EV              # noqa: E402
import ladder_store as LS        # noqa: E402
import moments as MO             # noqa: E402

NS = 1_000_000_000
D01 = os.path.join(REPRO, "data", "step01")


def day_bounds(day):
    t = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    return t, t + 86400 * NS


def days_of(sym):
    out = {}
    for p in sorted(glob.glob(os.path.join(D01, sym, "*.npz"))):
        out.setdefault(os.path.basename(p)[:8], []).append(p)
    return out


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    dts = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else [1000]
    grid, weights, vl, cap, tag = arg("--grid", "levels"), arg("--weights", "reach_freq"), arg("--vl", "at_t0"), arg("--cap", "per_mo"), arg("--tag", "base")
    with open(os.path.join(REPRO, "config", "train_days.yaml"), encoding="utf-8") as fh:
        train_days = {str(d) for d in yaml.safe_load(fh)["train_days_sept"]}
    days = days_of(sym)
    out_root = os.path.join(REPRO, "data", "step02", sym, tag)
    rep = os.path.join(REPRO, "reports", "step02")
    os.makedirs(rep, exist_ok=True)
    summary = []
    for dt_ms in dts:
        # 第一遍:reach 表(9 月训练日)
        reach = None
        if weights == "reach_freq":
            acc = DM.DemandEstimator(V_LO, weight_fn="reach_freq", vl_mode=vl, cap_mode=cap, grid_mode=grid)
            for day in sorted(d for d in days if d in train_days):
                lads = [LS.load(p) for p in days[day]]
                d0, d1 = day_bounds(day)
                fr = EV.build(lads, dt_ms, d0, d1)
                acc.estimate(fr, lads)
            reach = acc.reach_table()
            with open(os.path.join(rep, f"reach_{sym}_dt{dt_ms}_{tag}.json"), "w", encoding="utf-8") as fh:
                json.dump(dict(bid=reach[0].tolist(), ask=reach[1].tolist(), cnt_bid=acc.reach_cnt[0].tolist(), cnt_ask=acc.reach_cnt[1].tolist(),
                               days=sorted(d for d in days if d in train_days)), fh)
            print(f"{sym} dt={dt_ms} reach(ask, rank 1..6) = {np.round(reach[1][1:7], 3)}", flush=True)
        est = DM.DemandEstimator(V_LO, weight_fn=weights, vl_mode=vl, cap_mode=cap, grid_mode=grid, reach=reach)
        od = os.path.join(out_root, f"dt{dt_ms}")
        os.makedirs(od, exist_ok=True)
        for day, files in days.items():
            lads = [LS.load(p) for p in files]
            d0, d1 = day_bounds(day)
            fr = EV.build(lads, dt_ms, d0, d1)
            dp = est.estimate(fr, lads)
            s = DM.summarize(dp)
            mp, mm = MO.from_params(dp, 0), MO.from_params(dp, 1)
            np.savez_compressed(os.path.join(od, f"{day}.npz"), t0=fr.t0, ind_plus=fr.ind_plus, ind_minus=fr.ind_minus, vol_plus=fr.vol_plus,
                                vol_minus=fr.vol_minus, n_plus=fr.n_plus, n_minus=fr.n_minus, mid2=fr.mid2, gap=fr.gap,
                                c=dp.c, p=dp.p, valid=dp.valid, reason=dp.reason, n_levels=dp.n_levels, q_sum=dp.q_sum,
                                meta=np.bytes_(json.dumps(dict(sym=sym, day=day, dt_ms=dt_ms, src=lads[0]["meta"]["src"], V_LO=V_LO, cfg=dp.cfg)).encode()))
            row = dict(sym=sym, day=day, src=lads[0]["meta"]["src"], dt_ms=dt_ms, V_LO=V_LO, tag=tag, n_intervals=len(fr), n_gap=int(fr.gap.sum()),
                       plus=s["plus"], minus=s["minus"], moments_plus=mp, moments_minus=mm,
                       checks=MO.table1_checks(mp, mm) if mp and mm else None)
            summary.append(row)
            print(f"{sym} {day} dt={dt_ms}: valid+ {s['plus']['n_valid']} c+ {s['plus']['c_mean']} p+ {s['plus']['p_mean']} | valid- {s['minus']['n_valid']} "
                  f"reasons+ {s['plus']['reasons']}", flush=True)
    with open(os.path.join(rep, f"daily_{sym}_{tag}.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1, default=float)
    print("STEP02_DONE", flush=True)


if __name__ == "__main__":
    main()
