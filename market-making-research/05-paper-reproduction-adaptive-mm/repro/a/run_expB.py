"""Step 10 实验 B(Table 4/5):三列 {非鞅 + π(1,1)≥0, 鞅 + π(1,1)≥0, 非鞅 + π(1,1)≡0},非自适应二次 π(nonadaptive.py),随机需求矩同实验 A。
输出  data/step10/<sym>/<tag>/dt<ms>/expB_<day>.json、reports/step10/expB_<sym>_dt<ms>.md
用法  python run_expB.py <sym> <V_LO> [dt_ms] [--days d1,d2] [--tag base]
"""
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
import arrivals as AR          # noqa: E402
import bellman as BM           # noqa: E402
import nonadaptive as NA       # noqa: E402
import sim_paper as SP         # noqa: E402
import step06_catalog as S6    # noqa: E402

with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as _fh:
    CONTRACTS = yaml.safe_load(_fh)
LAM_USDT = 0.0005


def run_day(sym, day, dt_ms, V_LO, tag):
    done = os.path.join(REPRO, "data", "step10", sym, tag, f"dt{dt_ms}", f"expB_{day}.json")
    if os.path.exists(done) and "--force" not in sys.argv:    # 断点续跑
        print(f"{sym} {day} dt={dt_ms} expB: 已有结果,跳过", flush=True)
        return
    c = CONTRACTS[sym]
    tick, mult = float(c["tick"]), float(c["mult"])
    days = S6.training_window(sym, day, dt_ms, tag)
    mom = S6.window_moments(sym, days, dt_ms, tag)
    mp, mm = BM._mom(mom["plus"]), BM._mom(mom["minus"])
    coef = NA.fit_quadratic(sym, days, dt_ms, tag)
    N = int(round(86400 * 1000 / dt_ms)) - 1
    lam = LAM_USDT / (tick * mult)
    cats = {}
    for name, zero in (("pi11", False), ("pi11zero", True)):
        pp, pm, p11 = NA.evaluate(coef, N, dt_ms, pi11_zero=zero)
        cats[name] = BM.backward(NA.tables_fn(pp, pm, p11), mp, mm, N, lam)
    pols = [SP.CatalogPolicy("NA_nonmart_pi11", cats["pi11"], None, use_drift=True),
            SP.CatalogPolicy("NA_mart_pi11", cats["pi11"], None, use_drift=False),
            SP.CatalogPolicy("NA_nonmart_pi11zero", cats["pi11zero"], None, use_drift=True)]
    out, fr = SP.simulate(sym, day, dt_ms, pols, AR.GState("g1"), V_LO, LAM_USDT, tick, mult, need_state=False)
    slim = {}
    for n, r in out.items():
        r.update(SP.summarize_series(r["series"], dt_ms))
        slim[n] = {k: v for k, v in r.items() if k != "series"}
    od = os.path.join(REPRO, "data", "step10", sym, tag, f"dt{dt_ms}")
    os.makedirs(od, exist_ok=True)
    meta = dict(window=days, quadratic=coef, checks={k: v.checks for k, v in cats.items()},
                pi_eval_sample={k: [float(x) for x in NA.evaluate(coef, N, dt_ms)[0][::max(N // 6, 1)]] for k in ("plus",)})
    with open(os.path.join(od, f"expB_{day}.json"), "w", encoding="utf-8") as fh:
        json.dump(dict(results=slim, meta=meta), fh, ensure_ascii=False, indent=1, default=float)
    print(f"{sym} {day} dt={dt_ms} expB: " + " | ".join(f"{n}: J={r['J_T_usdt']:+.2f} PnL={r['PnL_T_usdt']:+.2f} fills={r['n_fills']} vol=${r['notional_usdt']:,.0f} I_T={r['I_T']:.0f}" for n, r in slim.items())
          + f" | quad plus {np.round(coef['plus'], 4).tolist()} mean {coef['plus_mean']:.4f}", flush=True)
    return slim


def table(sym, dt_ms, tag):
    od = os.path.join(REPRO, "data", "step10", sym, tag, f"dt{dt_ms}")
    rows, days = {}, []
    for p in sorted(glob.glob(os.path.join(od, "expB_*.json"))):
        d = json.load(open(p, encoding="utf-8"))["results"]
        days.append(os.path.basename(p)[5:13])
        for n, r in d.items():
            rows.setdefault(n, []).append(r)
    md = [f"# 实验 B(Table 4/5 型)—— {sym}, Δt = {dt_ms} ms, 非自适应二次 π(EC-28), 论文忠实成交", "", f"测试日 {len(days)} 天。单位 USDT。", "",
          "| 方案 | J_T 均值 | J_T 标准差 | PnL_T 均值 | PnL_T 标准差 | 成交笔数/日 | 成交额/日 | $/h | 日末 \\|I_T\\| | max\\|I\\| | 持仓段>300 s/日 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in ("NA_nonmart_pi11", "NA_mart_pi11", "NA_nonmart_pi11zero"):
        rs = rows.get(n, [])
        if not rs:
            continue
        J = np.array([r["J_T_usdt"] for r in rs]); P = np.array([r["PnL_T_usdt"] for r in rs])
        md.append(f"| {n} | {J.mean():+.2f} | {J.std(ddof=1) if len(J) > 1 else 0:.2f} | {P.mean():+.2f} | {P.std(ddof=1) if len(P) > 1 else 0:.2f} | {np.mean([r['n_fills'] for r in rs]):.0f} | "
                  f"${np.mean([r['notional_usdt'] for r in rs]):,.0f} | ${np.mean([r['notional_usdt'] for r in rs]) / 24:,.0f} | {np.mean([abs(r['I_T']) for r in rs]):.1f} | "
                  f"{np.mean([r['max_abs_I'] for r in rs]):.1f} | {np.mean([r['hold_gt_300s'] for r in rs]):.1f} |")
    rep = os.path.join(REPRO, "reports", "step10")
    os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"expB_{sym}_dt{dt_ms}_{tag}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    dt_ms = int(sys.argv[3]) if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else 1000
    tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else "base"
    import run_expA as A
    days = sys.argv[sys.argv.index("--days") + 1].split(",") if "--days" in sys.argv else A.test_days(sym)
    for d in days:
        run_day(sym, d, dt_ms, V_LO, tag)
    table(sym, dt_ms, tag)
    print("EXPB_DONE", flush=True)
