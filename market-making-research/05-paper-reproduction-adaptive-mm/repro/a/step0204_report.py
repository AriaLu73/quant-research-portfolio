"""Step 2–4 报告:汇总 reports/step02/daily_<sym>_<tag>.json 与 reports/step04/daily_<sym>.json → reports/step02/README_<sym>.md、reports/step04/README_<sym>.md,
并画 Figure 3 / 6(一个 10 月日)、Figure 4(训练窗)、Figure 5(一个 10 月日)。
用法  python step0204_report.py <sym> <V_LO> [--tag base] [--figday 20261016]
"""
import json
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台 gbk 会在打印表格时崩

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
PY = sys.executable


def step02(sym, tag):
    rows = json.load(open(os.path.join(REPRO, "reports", "step02", f"daily_{sym}_{tag}.json"), encoding="utf-8"))
    md = [f"# Step 2–3 报告 —— {sym}(变体 {tag})", "",
          "论文对应:Eq. (4)–(5) 随机需求、§3.1.2 虚拟单成交与加权回归、Eq. (7)–(8) 矩、Table 1。代码 a/demand.py、a/moments.py、a/step02_batch.py;单测 tests/test_demand.py。", "",
          "## Table 1 结构(各日估计的矩再取日均;Eq. (8) 条件口径)", "",
          "| 来源 | Δt | 天 | 有效区间/日(+/−) | 估计率(+)= 有效/有MO | μ_c⁺ | μ_c⁻ | μ_p⁺ | μ_p⁻ | μ_cp⁺ | μ_c⁺μ_p⁺ | μ_c2⁺ | μ_c2p⁺ | μ_c2⁺μ_p⁺ | c 的 CV(+) | corr(c,p)(+) | 用档数(+) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    by = {}
    for r in rows:
        by.setdefault((r["src"], r["dt_ms"]), []).append(r)
    for (src, dtm), rs in sorted(by.items()):
        rs = [r for r in rs if r["moments_plus"] and r["moments_minus"]]
        if not rs:
            continue
        mp = {k: np.mean([r["moments_plus"][k] for r in rs]) for k in ("mu_c", "mu_p", "mu_cp", "mu_c2", "mu_c2p", "mu_c2p2")}
        mm = {k: np.mean([r["moments_minus"][k] for r in rs]) for k in ("mu_c", "mu_p", "mu_cp", "mu_c2", "mu_c2p", "mu_c2p2")}
        nv_p = np.mean([r["plus"]["n_valid"] for r in rs]); nv_m = np.mean([r["minus"]["n_valid"] for r in rs])
        mo_p = np.mean([r["plus"]["n_valid"] + sum(v for k, v in r["plus"]["reasons"].items() if k not in ("ok", "no_mo")) for r in rs])
        cv = np.mean([np.sqrt(max(r["moments_plus"]["mu_c2"] - r["moments_plus"]["mu_c"] ** 2, 0)) / r["moments_plus"]["mu_c"] for r in rs])
        corr = np.nanmean([r["plus"]["corr_cp"] if r["plus"]["corr_cp"] is not None else np.nan for r in rs])
        nl = np.nanmean([r["plus"]["n_levels_p50"] if r["plus"]["n_levels_p50"] is not None else np.nan for r in rs])
        md.append(f"| {src} | {dtm} | {len(rs)} | {nv_p:.0f}/{nv_m:.0f} | {nv_p / max(mo_p, 1):.1%} | {mp['mu_c']:.4f} | {mm['mu_c']:.4f} | {mp['mu_p']:.1f} | {mm['mu_p']:.1f} | "
                  f"{mp['mu_cp']:.3f} | {mp['mu_c'] * mp['mu_p']:.3f} | {mp['mu_c2']:.4f} | {mp['mu_c2p']:.3f} | {mp['mu_c2'] * mp['mu_p']:.3f} | {cv:.2f} | {corr:.2f} | {nl:.0f} |")
    md += ["", "单位:c 张/tick,p tick。论文 Table 1(MSFT):slope 标准差约为均值的 200%(CV≈2),corr(c,p)≈20%,μ_cp ≈ 1.09 μ_cμ_p,μ_c2p ≈ 1.27 μ_c2μ_p。",
           "", "## 无效原因(Δt = 1 s,各日合计)", "", "| 来源 | 有效 | 无 MO | 缺口 | 无盘口 | 斜率非负 | 档位不足 | 全零 | p 超范围 |", "|---|---|---|---|---|---|---|---|---|"]
    for (src, dtm), rs in sorted(by.items()):
        if dtm != 1000:
            continue
        tot = {}
        for r in rs:
            for k, v in r["plus"]["reasons"].items():
                tot[k] = tot.get(k, 0) + v
        md.append(f"| {src} (+侧) | {tot.get('ok', 0):,} | {tot.get('no_mo', 0):,} | {tot.get('gap', 0):,} | {tot.get('no_ladder', 0):,} | {tot.get('slope_nonneg', 0):,} | {tot.get('too_few_levels', 0):,} | {tot.get('all_zero', 0):,} | {tot.get('p_out_of_range', 0):,} |")
    md += ["", "## 每日(Δt = 1 s)", "", "| 日 | 来源 | 有效(+/−) | μ_c⁺ | μ_p⁺ | μ_c⁻ | μ_p⁻ | corr(+) |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["dt_ms"] == 1000 and r["moments_plus"] and r["moments_minus"]:
            md.append(f"| {r['day']} | {r['src']} | {r['plus']['n_valid']}/{r['minus']['n_valid']} | {r['moments_plus']['mu_c']:.4f} | {r['moments_plus']['mu_p']:.1f} | "
                      f"{r['moments_minus']['mu_c']:.4f} | {r['moments_minus']['mu_p']:.1f} | {r['plus']['corr_cp'] if r['plus']['corr_cp'] is None else round(r['plus']['corr_cp'], 2)} |")
    md += ["", "工程选择:EC-08(档位网格)、EC-09(权重 reach_freq)、EC-10(坐标)、EC-11(V_L 取 t_k)、EC-12(Eq. 8 口径)、EC-13(逐笔封顶)、EC-22(远档截断与 p 范围)。图:fig3_*.png、fig6_*.png。"]
    with open(os.path.join(REPRO, "reports", "step02", f"README_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md[:12]))


def step04(sym):
    rows = json.load(open(os.path.join(REPRO, "reports", "step04", f"daily_{sym}.json"), encoding="utf-8"))
    md = [f"# Step 4 报告 —— {sym}", "",
          "论文对应:Eq. (45) g1/g2/g3、Eq. (46)–(47) 条件频率、Eq. (9) 联合律、Assumption 4 / Eq. (42) 转移 Γ、Remark 5(Figure 5)。代码 a/arrivals.py、a/step04_batch.py;单测 tests/test_arrivals.py。", "",
          "## 各日状态覆盖(训练窗模型 = 窗内各日计数相加;最终 Catalog 用的窗见 data/step06 的 json)", "",
          "| 日 | 来源 | Δt | 区间 | g1 见/64 | g1 <30 | g2 见/27 | g2 <30 | g3 见/81 | g3 <30 | π⁺(无条件) | π⁻ | π(1,1) | 合法性违反 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["dt_ms"] in (1000, 100):
            md.append(f"| {r['day']} | {r['src']} | {r['dt_ms']} | {r['n']:,} | {r['g1']['n_seen']} | {r['g1']['states_lt_30']} | {r['g2']['n_seen']} | {r['g2']['states_lt_30']} | "
                      f"{r['g3']['n_seen']} | {r['g3']['states_lt_30']} | {r['g3']['base']['pi_plus']:.4f} | {r['g3']['base']['pi_minus']:.4f} | {r['g3']['base']['pi_11']:.5f} | "
                      f"{r['g1']['pi11_gt_min'] + r['g2']['pi11_gt_min'] + r['g3']['pi11_gt_min']} |")
    md += ["", "样本不足的状态只报告不修改估计法(EC-17);递推时 π=0 的状态截到 1e-6(EC-18、EC-24)。图:fig4_*.png(训练窗 π± 对 g3 状态)、fig5_*.png(双侧窗诊断,不进策略)。"]
    with open(os.path.join(REPRO, "reports", "step04", f"README_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md[:8]))


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], sys.argv[2]
    tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else "base"
    figday = sys.argv[sys.argv.index("--figday") + 1] if "--figday" in sys.argv else "20261016"
    step02(sym, tag)
    step04(sym)
    F = os.path.join(HERE, "figures.py")
    for args in (["fig3", sym, figday, "1000", V_LO], ["fig6", sym, figday, "1000", V_LO], ["fig6", sym, "20260918", "1000", V_LO],
                 ["fig4", sym, "1000", "20260826", "20261002"], ["fig5", sym, "1000", figday]):
        r = subprocess.run([PY, F] + args, capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(args[0], r.returncode, (r.stdout or r.stderr).strip()[-120:])
