"""Step 10 实验 A(Table 2/3):每个测试日 {鞅+g1, 鞅+g2, 鞅+g3, 非鞅+g3, Level 1–6},论文忠实成交(sim_paper)。
测试日 = 10 月 L3 日中 train + validation 覆盖的日子(final_test 锁);训练窗按 step06(附录第 6 条)。
输出  data/step10/<sym>/<tag>/dt<ms>/expA_<day>.json(+ series npz)、reports/step10/expA_<sym>_dt<ms>.md(Table 2/3 + 成交额 / 持仓统计)
用法  python run_expA.py <sym> <V_LO> [dt_ms] [--days d1,d2] [--tag base] [--variant base|det]
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
import arrivals as AR          # noqa: E402
import sim_paper as SP         # noqa: E402
import step06_catalog as S6    # noqa: E402

with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as _fh:
    CONTRACTS = yaml.safe_load(_fh)
with open(os.path.join(REPRO, "config", "train_days.yaml"), encoding="utf-8") as _fh:
    TD = yaml.safe_load(_fh)
LAM_USDT = 0.0005


def test_days(sym):
    """10 月 L3 日(提取物里 src=l3 的日子),全部在 final_test 切点之前(提取时已锁)。"""
    days = sorted({os.path.basename(p)[:8] for p in glob.glob(os.path.join(REPRO, "data", "step01", sym, "202610*.npz"))})
    return days


def ensure_catalogs(sym, day, dt_ms, tag, det):
    od = os.path.join(REPRO, "data", "step06", sym, tag + ("_det" if det else ""), f"dt{dt_ms}")
    need = [k for k in ("g1", "g2", "g3") if not os.path.exists(os.path.join(od, f"{day}_{k}.npz"))]
    if need:
        S6.build(sym, day, dt_ms, tuple(need), tag, deterministic=det, lam_usdt=LAM_USDT)
    return {k: S6.load_catalog(os.path.join(od, f"{day}_{k}.npz")) for k in ("g1", "g2", "g3")}


def run_day(sym, day, dt_ms, V_LO, tag, det, force=False):
    od = os.path.join(REPRO, "data", "step10", sym, tag + ("_det" if det else ""), f"dt{dt_ms}")
    done = os.path.join(od, f"expA_{day}.json")
    if os.path.exists(done) and not force:                 # 断点续跑:该日已完成(且 liq_buckets 已追加),不重复
        print(f"{sym} {day} dt={dt_ms}: 已有结果,跳过", flush=True)
        return json.load(open(done, encoding="utf-8"))
    c = CONTRACTS[sym]
    cats = ensure_catalogs(sym, day, dt_ms, tag, det)
    gs = {k: AR.GState(k) for k in ("g1", "g2", "g3")}
    results = {}
    # 状态函数不同的策略要分别回放(s_k 依赖 g);Level 基准与 g3 一起跑
    for kind in ("g1", "g2", "g3"):
        pols = [SP.CatalogPolicy(f"M_{kind}", cats[kind][0], gs[kind])]
        if kind == "g3":
            pols.append(SP.CatalogPolicy("G_g3", cats["g3"][0], gs["g3"], use_drift=True))
            pols += [SP.FixedLevelPolicy(i) for i in range(1, 7)]
        out, fr = SP.simulate(sym, day, dt_ms, pols, gs[kind], V_LO, LAM_USDT, float(c["tick"]), float(c["mult"]))
        for name, r in out.items():
            r.update(SP.summarize_series(r["series"], dt_ms))
            results[name] = r
    od = os.path.join(REPRO, "data", "step10", sym, tag + ("_det" if det else ""), f"dt{dt_ms}")
    os.makedirs(od, exist_ok=True)
    np.savez_compressed(os.path.join(od, f"expA_{day}_series.npz"),
                        **{f"{n}_{k}": v for n, r in results.items() for k, v in r["series"].items() if k in ("W", "I", "bid", "ask", "qp", "qm", "flag", "frozen", "beyond")})
    slim = {n: {k: v for k, v in r.items() if k != "series"} for n, r in results.items()}
    with open(os.path.join(od, f"expA_{day}.json"), "w", encoding="utf-8") as fh:
        json.dump(slim, fh, ensure_ascii=False, indent=1, default=float)
    # Step 9 的清算成本分桶(供 Step 16)
    with open(os.path.join(REPRO, "data", "step10", sym, "liq_buckets.csv"), "a", encoding="utf-8") as fh:
        for n, r in slim.items():
            fh.write(f"{sym},{day},{dt_ms},{tag},{n},{r['I_T']},{r['S_T_tick']},{r['liq_cost_usdt']},{r['liq_depth_short']}\n")
    line = " | ".join(f"{n}: J={r['J_T_usdt']:+.2f} PnL={r['PnL_T_usdt']:+.2f} fills={r['n_fills']} vol=${r['notional_usdt']:,.0f} I_T={r['I_T']:.0f} max|I|={r['max_abs_I']:.0f}"
                     for n, r in slim.items() if n in ("M_g3", "G_g3", "Level1", "Level3"))
    print(f"{sym} {day} dt={dt_ms}: {line}", flush=True)
    return slim


def table(sym, dt_ms, tag, det):
    od = os.path.join(REPRO, "data", "step10", sym, tag + ("_det" if det else ""), f"dt{dt_ms}")
    rows = {}
    days = []
    for p in sorted(glob.glob(os.path.join(od, "expA_*.json"))):
        d = json.load(open(p, encoding="utf-8"))
        days.append(os.path.basename(p)[5:13])
        for n, r in d.items():
            rows.setdefault(n, []).append(r)
    order = ["M_g1", "M_g2", "M_g3", "G_g3"] + [f"Level{i}" for i in range(1, 7)]
    md = [f"# 实验 A(Table 2/3 型)—— {sym}, Δt = {dt_ms} ms, 变体 {tag}{'_det' if det else ''}, 论文忠实成交(队首假设、无费率、无延迟)", "",
          f"测试日 {len(days)} 天:{days[0]}…{days[-1]}。数字单位 USDT;λ = 0.0005 USDT/张²(MSFT 值,仅作对照,EC-21)。", "",
          "| 方案 | J_T 均值 | J_T 标准差 | PnL_T 均值 | PnL_T 标准差 | 成交笔数/日 | 成交额/日 | $/h | 日末 \\|I_T\\| 均值 | max\\|I\\| 均值 | 持仓段>300 s/日 | 冻结区间占比 | 规则触发占比 | 深于20档占比 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in order:
        if n not in rows:
            continue
        rs = rows[n]
        J = np.array([r["J_T_usdt"] for r in rs]); P = np.array([r["PnL_T_usdt"] for r in rs])
        md.append(f"| {n} | {J.mean():+.2f} | {J.std(ddof=1) if len(J) > 1 else 0:.2f} | {P.mean():+.2f} | {P.std(ddof=1) if len(P) > 1 else 0:.2f} | "
                  f"{np.mean([r['n_fills'] for r in rs]):.0f} | ${np.mean([r['notional_usdt'] for r in rs]):,.0f} | ${np.mean([r['notional_usdt'] for r in rs]) / 24:,.0f} | "
                  f"{np.mean([abs(r['I_T']) for r in rs]):.1f} | {np.mean([r['max_abs_I'] for r in rs]):.1f} | {np.mean([r['hold_gt_300s'] for r in rs]):.1f} | "
                  f"{np.mean([r['frozen_share'] for r in rs]):.1%} | {np.mean([r['flag_share'] for r in rs]):.1%} | {np.mean([r['beyond_share'] for r in rs]):.1%} |")
    rep = os.path.join(REPRO, "reports", "step10")
    os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"expA_{sym}_dt{dt_ms}_{tag}{'_det' if det else ''}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    dt_ms = int(sys.argv[3]) if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else 1000
    tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else "base"
    det = "--variant" in sys.argv and sys.argv[sys.argv.index("--variant") + 1] == "det"
    days = sys.argv[sys.argv.index("--days") + 1].split(",") if "--days" in sys.argv else test_days(sym)
    for d in days:
        run_day(sym, d, dt_ms, V_LO, tag, det, force="--force" in sys.argv)
    table(sym, dt_ms, tag, det)
    print("EXPA_DONE", flush=True)
