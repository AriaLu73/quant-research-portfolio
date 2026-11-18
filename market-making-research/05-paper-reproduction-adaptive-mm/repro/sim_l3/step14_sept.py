"""Step 14 —— 9 月三天自录 L3(附录第 5 条、EC-44):只取排队分布,单独一列;不进校准、不进 PnL。
报价序列用第一个测试日 10-13 的 P1 目录(Part A g3)与 P2 目录(γ*);延迟 1.8 ms;数据目录按 SEPT 映射注入引擎。
输出  data/step14/<sym>/sept/<day>_<agent>.npz;reports/step14/table10_<sym>_sept.md
用法  python step14_sept.py <sym> <V_LO> [--gamma g]
"""
import datetime as dt
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "a"))
sys.path.insert(0, os.path.join(REPRO, "b"))
import engine_bridge as B      # noqa: E402
import agents as AG            # noqa: E402
import arrivals as AR          # noqa: E402
import step06_catalog as S6    # noqa: E402
import step13_build as S13     # noqa: E402
import step14_batch as S14B    # noqa: E402
import step14_run as S14       # noqa: E402

L, E = B.L, B.E
NS = 1_000_000_000
REF_DAY = "20261013"
L_BUCKETS = [(0, 1), (1, 3), (3, 10), (10, 30), (30, 100), (100, 10**9)]


def run_day(sym, V_LO, day, l3_dir, gamma, lat=1.8):
    B.patch_engine(sym, l3_dir=l3_dir, trd_dir=l3_dir)
    day0 = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    g = AR.GState("g3")
    cat, _ = S6.load_catalog(os.path.join(REPRO, "data", "step06", sym, "base", "dt1000", f"{REF_DAY}_g3.npz"))
    agents = [AG.PaperPolicyAgent(f"P1_M_g3_L{lat:g}", cat, g, V_LO, 1000, day0, lat_ms=lat)]
    p2 = os.path.join(REPRO, "data", "step13", sym, "dt1000", f"{REF_DAY}_g{gamma:g}_e{V_LO:g}.npz") if gamma is not None else None
    if p2 and os.path.exists(p2):
        q, meta = S13.load(p2)
        agents.append(AG.P2Agent(f"P2_g{gamma:g}_L{lat:g}", q, g, V_LO, 1000, day0, fee_take_ticks=meta["fee_take_ticks"], lat_ms=lat))
    for a in agents:
        a.lat = L.Latency(fixed_ms=lat)
    hours = E.hours_of(day, sym)
    sim = L.L3Sim(sym, L.Latency(fixed_ms=lat), agents, recorder=S14.Dispatcher(agents), trade_ticks=E.P.load_trade_ticks(day, hours, sym))
    E.run_hours(sim, day, hours, prewarm_s=300)
    od = os.path.join(REPRO, "data", "step14", sym, "sept"); os.makedirs(od, exist_ok=True)
    out = {}
    for a in agents:
        rec = np.asarray(a.records, np.int64).reshape(-1, 10); fl = np.asarray(a.fills, np.int64).reshape(-1, 10)
        rq = np.asarray(getattr(a, "records_requote", []), np.int64).reshape(-1, 6)
        np.savez_compressed(os.path.join(od, f"{day}_{a.name}.npz"), records=rec, fills=fl, requotes=rq, hours=np.array(hours))
        live = rec[rec[:, 5] >= 0]; a0 = live[:, 5]
        out[a.name] = dict(hours=hours, n_orders=int(len(rec)), n_rested=int(len(live)), ahead0_zero_share=float((a0 == 0).mean()) if len(a0) else None,
                           p=[float(np.percentile(a0, k)) for k in (50, 90, 99)] if len(a0) else None, n_fills=int(len(fl)), fill_qty=int(fl[:, 3].sum()) if len(fl) else 0,
                           byL={f"[{lo},{hi})": (float((a0[(np.abs(live[:, 9]) >= lo) & (np.abs(live[:, 9]) < hi)] == 0).mean()) if ((np.abs(live[:, 9]) >= lo) & (np.abs(live[:, 9]) < hi)).any() else None,
                                                int(((np.abs(live[:, 9]) >= lo) & (np.abs(live[:, 9]) < hi)).sum())) for lo, hi in L_BUCKETS},
                           requote_given_up_p50_p90=[float(np.percentile(rq[:, 4], 50)), float(np.percentile(rq[:, 4], 90))] if len(rq) else None, breaks=a.n_breaks)
        print(f"{sym} {day} {a.name}: " + json.dumps(out[a.name], default=float)[:300], flush=True)
    return out


def main(sym, V_LO, gamma):
    res = {}
    for day, d in S14B.SEPT[sym]:
        res[day] = run_day(sym, V_LO, day, d, gamma)
    md = [f"# Table 10 附列 —— {sym}:9 月三天自录 L3 的排队分布(附录第 5 条;报价序列 = {REF_DAY} 的目录;1.8 ms;只报排队,不进 PnL / 校准)", "",
          "| 日 | 小时 | agent | 下单数 | 进簿单 | ahead0=0 占比 | ahead0 p50/p90/p99 | 成交次数 / 张 | 改价放弃 ahead p50/p90 | 断流 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for day, r in res.items():
        for n, o in r.items():
            md.append(f"| {day} | {','.join(o['hours'])} | {n} | {o['n_orders']:,} | {o['n_rested']:,} | {(f"{o['ahead0_zero_share']:.1%}" if o['ahead0_zero_share'] is not None else '–')} | {'/'.join(f'{x:.0f}' for x in o['p']) if o['p'] else '–'} | "
                      f"{o['n_fills']} / {o['fill_qty']:,} | {'/'.join(f'{x:.0f}' for x in o['requote_given_up_p50_p90']) if o['requote_given_up_p50_p90'] else '–'} | {o['breaks']} |")
    md += ["", "## ahead0=0 占比按 |level0| 档(P1_M_g3)", "", "| 日 | " + " | ".join(f"[{lo},{hi})" for lo, hi in L_BUCKETS) + " |", "|---|" + "---|" * len(L_BUCKETS)]
    for day, r in res.items():
        for n, o in r.items():
            if n.startswith("P1"):
                md.append(f"| {day} | " + " | ".join((f"{v[0]:.1%} (n={v[1]:,})" if v[0] is not None else "–") for v in o["byL"].values()) + " |")
    rep = os.path.join(REPRO, "reports", "step14"); os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"table10_{sym}_sept.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    with open(os.path.join(REPRO, "data", "step14", sym, "sept", "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=float)
    print("\n".join(md)); print("SEPT_DONE", flush=True)


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    gamma = float(sys.argv[sys.argv.index("--gamma") + 1]) if "--gamma" in sys.argv else S14B.gamma_star(sym)
    main(sym, V_LO, gamma)
