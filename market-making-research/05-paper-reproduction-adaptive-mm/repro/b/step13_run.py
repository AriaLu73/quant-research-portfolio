"""Step 13 运行器:γ 扫描(EC-36 网格,先在 SCAN_DAYS 上;EC-41)→ 按 NIR 选 γ → 全部测试日跑 {P2 完整, P2 WoMO, αc, αr};P1 原版对照取 Part A 的 expA 结果。
输出  data/step13/<sym>/dt<ms>/sim_<day>_<policy>.json;reports/step13/gamma_scan_<sym>.md、table9_<sym>.md、fig3_<sym>_*.png
用法  python step13_run.py <sym> <V_LO> [--dt 1000] [--scan-days d1,d2,d3] [--gammas 0,1e-5,1e-4,1e-3,1e-2] [--days all|d1,...] [--gamma-fixed g]
"""
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
import arrivals as AR            # noqa: E402
import sim_partB as SB           # noqa: E402
import step13_build as B         # noqa: E402

with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as _fh:
    CONTRACTS = yaml.safe_load(_fh)
SCAN_DAYS = ["20261016", "20261017", "20261018"]
GAMMAS = [0.0, 1e-5, 1e-4, 1e-3, 1e-2]


def catalog(sym, V_LO, day, gamma, dt_ms, e_bar):
    p = os.path.join(REPRO, "data", "step13", sym, f"dt{dt_ms}", f"{day}_g{gamma:g}_e{e_bar:g}.npz")
    if not os.path.exists(p):
        B.build(sym, V_LO, day, gamma=gamma, dt_ms=dt_ms, e_bar=e_bar)
    return B.load(p)


def run_day(sym, V_LO, day, dt_ms, gammas, with_bench=True):
    c = CONTRACTS[sym]
    pols, metas = [], {}
    for gm in gammas:
        for eb, lab in ((V_LO, "full"), (0, "WoMO")):
            q, meta = catalog(sym, V_LO, day, gm, dt_ms, eb)
            pols.append(SB.P2Policy(f"P2_{lab}_g{gm:g}", q, q.edges)); metas[pols[-1].name] = meta
    if with_bench:
        pols += [SB.TouchPolicy("alpha_c"), SB.TouchPolicy("alpha_r", random=True)]
    fee = next(iter(metas.values()))["fee_take_ticks"]
    segs, fr = SB.simulate_day(sym, day, dt_ms, pols, AR.GState("g3"), V_LO, float(c["tick"]), float(c["mult"]), fee)
    od = os.path.join(REPRO, "data", "step13", sym, f"dt{dt_ms}")
    out = {}
    for n, s in segs.items():
        S = SB.summarize(s, dt_ms)
        out[n] = S
        with open(os.path.join(od, f"sim_{day}_{n}.json"), "w", encoding="utf-8") as fh:
            json.dump(dict(summary=S, segments=s), fh, default=float)
    print(f"{sym} {day}: " + " | ".join(f"{n}: m={S['m']:+.3f} sd={S['sd']:.3f} fills/seg={S['fills']:.1f} mo/seg={S['n_mo']:.2f} max|Y|={S['maxY_mean']:.0f} |Y_T|={S['YT_abs_mean']:.0f}" for n, S in out.items()), flush=True)
    return out


def nir_table(sym, dt_ms, days, gammas):
    """每档 γ:m、σ、IR、NIR = (m(X*) − m(X^c)) / σ(X*),max|Y|、市价单笔数与成交额(P2 Section 4)。"""
    od = os.path.join(REPRO, "data", "step13", sym, f"dt{dt_ms}")
    def load(n):
        xs, ss, cl = [], [], []
        for d in days:
            p = os.path.join(od, f"sim_{d}_{n}.json")
            if os.path.exists(p):
                j = json.load(open(p, encoding="utf-8")); xs += [s["X_T_usdt"] for s in j["segments"]]; ss.append(j["summary"])
                cl += [s["frozen"] == 0 and s["book_ok"] for s in j["segments"]]
        return np.array(xs), ss, np.array(cl, bool)
    def stats(xs, cl, xc, cc):
        m, sd = xs.mean(), xs.std(ddof=1); nir = (m - xc.mean()) / sd if sd > 0 else 0.0
        xk = xs[cl]; mk, sk = (xk.mean(), xk.std(ddof=1)) if len(xk) > 1 else (0.0, 0.0); nk = (mk - xc[cc].mean()) / sk if sk > 0 and cc.any() else 0.0
        return m, sd, nir, int((~cl).sum()), mk, sk, nk
    xc, _, cc = load("alpha_c")
    rows = ["| 方案 | γ | 段数 | m(X_T) USDT | σ(X_T) | IR | NIR vs αc | 缺口段数 | 不含缺口段 m / σ / IR / NIR | 成交笔/段 | 成交额合计 | 市价单笔/段 | 市价单成交额 | taker 费合计 | max\\|Y\\| 均值 | 段末 \\|Y_T\\| 均值 | 段末清零占比 | 持仓段 p50 / max s | >300 s |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    best = None
    for gm in gammas:
        for lab in ("full", "WoMO"):
            n = f"P2_{lab}_g{gm:g}"
            xs, ss, cl = load(n)
            if len(xs) == 0:
                continue
            m, sd, nir, ngap, mk, sk, nk = stats(xs, cl, xc, cc)
            rows.append(f"| {n} | {gm:g} | {len(xs)} | {m:+.3f} | {sd:.3f} | {m / sd if sd > 0 else 0:+.3f} | {nir:+.3f} | {ngap} | {mk:+.3f} / {sk:.3f} / {mk / sk if sk > 0 else 0:+.3f} / {nk:+.3f} | {np.mean([s['fills'] for s in ss]):.2f} | ${np.sum([s['notional'] for s in ss]):,.0f} | "
                        f"{np.mean([s['n_mo'] for s in ss]):.2f} | ${np.sum([s['mo_notional'] for s in ss]):,.0f} | ${np.sum([s['mo_fee'] for s in ss]):,.2f} | {np.mean([s['maxY_mean'] for s in ss]):.0f} | "
                        f"{np.mean([s['YT_abs_mean'] for s in ss]):.0f} | {np.mean([s['YT_zero_share'] for s in ss]):.1%} | {np.mean([s['hold_p50_s'] for s in ss]):.0f} / {np.max([s['hold_max_s'] for s in ss]):.0f} | {np.sum([s['hold_gt_300s'] for s in ss])} |")
            if lab == "full" and (best is None or nir > best[1]):
                best = (gm, nir)
    for n in ("alpha_c", "alpha_r"):
        xs, ss, cl = load(n)
        if len(xs):
            m, sd, nir, ngap, mk, sk, nk = stats(xs, cl, xc, cc)
            rows.append(f"| {n} | – | {len(xs)} | {m:+.3f} | {sd:.3f} | {m / sd if sd > 0 else 0:+.3f} | – | {ngap} | {mk:+.3f} / {sk:.3f} / {mk / sk if sk > 0 else 0:+.3f} / – | {np.mean([s['fills'] for s in ss]):.2f} | ${np.sum([s['notional'] for s in ss]):,.0f} | 0 | $0 | $0 | "
                        f"{np.mean([s['maxY_mean'] for s in ss]):.0f} | {np.mean([s['YT_abs_mean'] for s in ss]):.0f} | {np.mean([s['YT_zero_share'] for s in ss]):.1%} | {np.mean([s['hold_p50_s'] for s in ss]):.0f} / {np.max([s['hold_max_s'] for s in ss]):.0f} | {np.sum([s['hold_gt_300s'] for s in ss])} |")
    return rows, best


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    arg = lambda f, d: sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d
    dt_ms = int(arg("--dt", "1000"))
    scan_days = arg("--scan-days", ",".join(SCAN_DAYS)).split(",")
    gammas = [float(x) for x in arg("--gammas", ",".join(f"{g:g}" for g in GAMMAS)).split(",")]
    rep = os.path.join(REPRO, "reports", "step13"); os.makedirs(rep, exist_ok=True)
    if "--gamma-fixed" in sys.argv:
        g_star = float(arg("--gamma-fixed", "1e-4"))
    else:
        for d in scan_days:
            run_day(sym, V_LO, d, dt_ms, gammas)
        rows, best = nir_table(sym, dt_ms, scan_days, gammas)
        g_star = best[0]
        with open(os.path.join(rep, f"gamma_scan_{sym}_dt{dt_ms}.md"), "w", encoding="utf-8") as fh:
            fh.write(f"# γ 扫描 —— {sym}, Δt={dt_ms} ms, 日 {scan_days}(EC-36/EC-41);选 γ* = {g_star:g}(NIR 最大)\n\n" + "\n".join(rows) + "\n")
        print("\n".join(rows)); print("gamma* =", g_star, flush=True)
    days = arg("--days", "all")
    import run_expA as A
    all_days = A.test_days(sym) if days == "all" else days.split(",")
    for d in all_days:
        run_day(sym, V_LO, d, dt_ms, [g_star])
    rows, _ = nir_table(sym, dt_ms, all_days, [g_star])
    with open(os.path.join(rep, f"table9_{sym}_dt{dt_ms}.md"), "w", encoding="utf-8") as fh:
        fh.write(f"# Table 9 —— {sym}, Δt={dt_ms} ms, γ* = {g_star:g}, 全部测试日 {all_days[0]}…{all_days[-1]}({len(all_days)} 天);P1 原版对照见 reports/step10/expA_{sym}_dt{dt_ms}_base.md\n\n" + "\n".join(rows) + "\n")
    print("\n".join(rows)); print("STEP13_DONE", flush=True)
