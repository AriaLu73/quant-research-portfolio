"""Step 15 —— 费率与延迟:P2 完整 / WoMO(γ*)的返佣感知目录(maker OUR_FEE USDT / OUR_FEE USDC 折 tick/张,EC-45)+ taker OUR_FEE,
接到 l3sim,延迟 L ∈ {0, 1.8, 3.8, 10, 25, 50} ms(latency.yaml 网格 + 用户 2026-10-03 拥堵 50 ms;0 只作单调性检验),每个测试日整天回放。
另跑论文忠实成交(sim_partB,50 ms 网格盘口、无延迟)含费率的对照。
输出  data/step15/<sym>/<day>_<agent>.npz、<day>_paper.json;然后 step15_report.py 出 Table 11 与配对单调性。
用法  python step15_run.py <sym> <V_LO> [--days d1,d2] [--lats 0,1.8,3.8,10,25,50]
"""
import datetime as dt
import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "a"))
sys.path.insert(0, os.path.join(REPRO, "b"))
import engine_bridge as B      # noqa: E402
import agents as AG            # noqa: E402
import arrivals as AR          # noqa: E402
import sim_partB as SB         # noqa: E402
import step13_build as S13     # noqa: E402
import step14_batch as S14B    # noqa: E402
import step14_run as S14       # noqa: E402

L, E = B.L, B.E
NS = 1_000_000_000
REBATE_BP = {"USDT": 0.7, "USDC": 1.2}


def catalogs(sym, V_LO, day, g, reb):
    out = {}
    for eb, lab in ((V_LO, "full"), (0, "WoMO")):
        p = os.path.join(REPRO, "data", "step13", sym, "dt1000", f"{day}_g{g:g}_e{eb:g}_reb{reb:g}.npz")
        if not os.path.exists(p):
            S13.build(sym, V_LO, day, gamma=g, e_bar=eb, rebate_bp=reb)
        out[lab] = S13.load(p)
    return out


def run_day(sym, V_LO, day, g, lats):
    c = B.CONTRACTS[sym]
    reb = REBATE_BP[c["quote"]]
    cats = catalogs(sym, V_LO, day, g, reb)
    B.patch_engine(sym)
    day0 = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    gs = AR.GState("g3")
    agents = []
    for lab, (q, meta) in cats.items():
        for lm in lats:
            a = AG.P2Agent(f"P2_{lab}_L{lm:g}", q, gs, V_LO, 1000, day0, fee_take_ticks=meta["fee_take_ticks"], lat_ms=lm, rebate_ticks=meta["rebate_ticks"])
            a.lat = L.Latency(fixed_ms=lm)
            agents.append(a)
    hours = E.hours_of(day, sym)
    sim = L.L3Sim(sym, L.Latency(fixed_ms=lats[0]), agents, recorder=S14.Dispatcher(agents), trade_ticks=E.P.load_trade_ticks(day, hours, sym))
    E.run_hours(sim, day, hours, prewarm_s=300)
    od = os.path.join(REPRO, "data", "step15", sym)
    os.makedirs(od, exist_ok=True)
    for a in agents:
        np.savez_compressed(os.path.join(od, f"{day}_{a.name}.npz"), records=np.asarray(a.records, np.int64).reshape(-1, 10),
                            fills=np.asarray(a.fills, np.int64).reshape(-1, 10), requotes=np.asarray(getattr(a, "records_requote", []), np.int64).reshape(-1, 6),
                            mos=np.asarray(a.mos, float).reshape(-1, 6), W=a.W, I=a.I, breaks=a.n_breaks)
        print(f"{sym} {day} {a.name}: orders={len(a.records)} fills={len(a.fills)} qty={sum(f[3] for f in a.fills)} mos={len(a.mos)} W={a.W:.0f} I={a.I:.0f}", flush=True)
    # 论文忠实成交 + 费率(无延迟)对照
    q, meta = cats["full"]; qw, _ = cats["WoMO"]
    pols = [SB.P2Policy("P2_full_paper", q, q.edges), SB.P2Policy("P2_WoMO_paper", qw, qw.edges), SB.TouchPolicy("alpha_c")]
    segs, fr = SB.simulate_day(sym, day, 1000, pols, gs, V_LO, float(c["tick"]), float(c["mult"]), meta["fee_take_ticks"], rebate_ticks=meta["rebate_ticks"])
    with open(os.path.join(od, f"{day}_paper.json"), "w", encoding="utf-8") as fh:
        json.dump({n: SB.summarize(s, 1000) for n, s in segs.items()}, fh, default=float)
    return meta


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    arg = lambda f, d: sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d
    lats = tuple(float(x) for x in arg("--lats", "0,1.8,3.8,10,25,50").split(","))
    g = S14B.gamma_star(sym)
    days = arg("--days", None)
    days = days.split(",") if days else sorted({os.path.basename(p)[:8] for p in glob.glob(os.path.join(REPRO, "data", "step01", sym, "202610*.npz"))})
    print("gamma*", g, "lats", lats, flush=True)
    for d in days:
        run_day(sym, V_LO, d, g, lats)
    import subprocess
    subprocess.run([sys.executable, os.path.join(HERE, "step15_report.py"), sym, str(V_LO), "--gamma", f"{g:g}"], cwd=REPRO)
    print("STEP15_DONE", flush=True)
