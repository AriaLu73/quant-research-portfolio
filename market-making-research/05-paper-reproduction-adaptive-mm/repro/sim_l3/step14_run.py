"""Step 14 —— 脚注 5/6 队首假设的实测:把 P1 目录策略(Part A)与 P2 策略(Step 13)接到 l3sim,延迟 1.8 / 3.8 ms,记录每张单的 ahead0 / ahead / 结局。
输出  data/step14/<sym>/<day>_L<lat>.npz(records / fills / requotes / mos)+ reports/step14/table10_<sym>.md、fig8_<sym>.png
用法  python step14_run.py <sym> <V_LO> <day> [--lat 1.8,3.8] [--gamma 1e-4] [--hours HH,HH] [--dt 1000] [--bbo] [--kinds g3|g1,g2,g3]
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

L, E = B.L, B.E
NS = 1_000_000_000


class Dispatcher:
    """recorder 接口:把引擎的 on_sweep 转发给全部 agent(区间到达指标用);on_bbo 不用。"""

    def __init__(self, agents, record_bbo=False):
        self.agents = agents
        self.record_bbo = record_bbo
        self.bbo_ts, self.bbo_mid2 = [], []       # L3 时间分辨率的中价序列(Step 12 的 1 ms / 10 ms markout 用)

    def on_bbo(self, ts, bb, ba, bsz, asz):
        if self.record_bbo and bb is not None and ba is not None and bb > 0 and ba > 0:
            self.bbo_ts.append(ts); self.bbo_mid2.append(bb + ba)

    def on_sweep(self, ts, maker_side, sweep):
        for a in self.agents:
            a.on_sweep(ts, maker_side, sweep)


def run(sym, V_LO, day, lats=(1.8, 3.8), gamma=1e-4, hours=None, dt_ms=1000, record_bbo=False, kinds=("g3",)):
    """dt_ms ≠ 1000 时输出到 data/step14/<sym>/dt<dt>/(Step 12 的 l3sim 列);P2 目录不存在则只跑 P1。record_bbo:另存 L3 分辨率中价序列。
    kinds(2026-11-08,任务书 Table 8 "× g1/g2/g3"):P1 目录策略按每个状态函数各一个 agent(P1_M_g1 / g2 / g3),同一场回放;P2 仍用 g3 状态(Step 13 实现口径)。"""
    c = B.patch_engine(sym)
    day0 = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    g = AR.GState("g3")
    cats = {k: (AR.GState(k), S6.load_catalog(os.path.join(REPRO, "data", "step06", sym, "base", f"dt{dt_ms}", f"{day}_{k}.npz"))[0]) for k in kinds}
    p2 = os.path.join(REPRO, "data", "step13", sym, f"dt{dt_ms}", f"{day}_g{gamma:g}_e{V_LO:g}.npz")
    q, meta = S13.load(p2) if os.path.exists(p2) else (None, None)
    agents = []
    for lm in lats:
        new_agents = [AG.PaperPolicyAgent(f"P1_M_{k}_L{lm:g}", cat_k, g_k, V_LO, dt_ms, day0, lat_ms=lm) for k, (g_k, cat_k) in cats.items()]
        if q is not None:
            new_agents.append(AG.P2Agent(f"P2_g{gamma:g}_L{lm:g}", q, g, V_LO, dt_ms, day0, fee_take_ticks=meta["fee_take_ticks"], lat_ms=lm))
        for a in new_agents:
            a.lat = L.Latency(fixed_ms=lm)
            agents.append(a)
    hours = hours or E.hours_of(day, sym)
    disp = Dispatcher(agents, record_bbo=record_bbo)
    sim = L.L3Sim(sym, L.Latency(fixed_ms=lats[0]), agents, recorder=disp, trade_ticks=E.P.load_trade_ticks(day, hours, sym))
    E.run_hours(sim, day, hours, prewarm_s=300)
    od = os.path.join(REPRO, "data", "step14", sym) if dt_ms == 1000 else os.path.join(REPRO, "data", "step14", sym, f"dt{dt_ms}")
    os.makedirs(od, exist_ok=True)
    if record_bbo:
        np.savez_compressed(os.path.join(od, f"{day}_bbo.npz"), ts=np.asarray(disp.bbo_ts, np.int64), mid2=np.asarray(disp.bbo_mid2, np.int64))
    out = {}
    for a in agents:
        rec = np.asarray(a.records, np.int64).reshape(-1, 10)
        fl = np.asarray(a.fills, np.int64).reshape(-1, 10)
        rq = np.asarray(getattr(a, "records_requote", []), np.int64).reshape(-1, 6)
        mo = np.asarray(a.mos, float).reshape(-1, 6)
        np.savez_compressed(os.path.join(od, f"{day}_{a.name}.npz"), records=rec, fills=fl, requotes=rq, mos=mo, W=a.W, I=a.I, breaks=a.n_breaks,
                            segments=np.asarray(getattr(a, "segments", []), float).reshape(-1, 3))
        live = rec[rec[:, 5] >= 0]
        a0 = live[:, 5]
        out[a.name] = dict(n_orders=int(len(rec)), n_rested=int(len(live)), ahead0_zero_share=float((a0 == 0).mean()) if len(a0) else None,
                           ahead0_pct={k: float(np.percentile(a0, k)) for k in (10, 50, 90)} if len(a0) else None,
                           filled=int((rec[:, 7] == 1).sum()), canceled=int((rec[:, 7] == 2).sum()), lost=int((rec[:, 7] == 3).sum()),
                           fill_qty=int(fl[:, 3].sum()) if len(fl) else 0, n_fills=int(len(fl)), n_requotes=int(len(rq)),
                           requote_ahead_given_up_p50=float(np.median(rq[rq[:, 4] >= 0, 4])) if len(rq) and (rq[:, 4] >= 0).any() else None,
                           time_to_fill_ms_p50=float(np.median(fl[:, 6]) / 1e6) if len(fl) else None, n_mo=int(len(mo)),
                           W_tick_contracts=float(a.W), I_end=float(a.I), breaks=a.n_breaks)
        print(f"{sym} {day} {a.name}: " + json.dumps(out[a.name], default=float)[:400], flush=True)
    with open(os.path.join(od, f"{day}_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
    return out


if __name__ == "__main__":
    sym, V_LO, day = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    arg = lambda f, d: sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d
    hours = arg("--hours", None)
    run(sym, V_LO, day, lats=tuple(float(x) for x in arg("--lat", "1.8,3.8").split(",")), gamma=float(arg("--gamma", "1e-4")),
        hours=hours.split(",") if hours else None, dt_ms=int(arg("--dt", "1000")), record_bbo="--bbo" in sys.argv, kinds=tuple(arg("--kinds", "g3").split(",")))
