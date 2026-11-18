"""Step 14 第 5 条:用 (c) 口径(V_L = 严格优于 + 同价位前方量,demand.vl_mode="queue",tag l3q)重新估计 (c,p) 与矩、重建 Catalog,
与 Part A(base)的 Catalog 对比最优报价差异。对照实验,标注"L3 队列口径",不与论文忠实结果混报。
前置:a/step0204_chain.py <sym> <V_LO> 1000 --vl queue --tag l3q 已跑(data/step02/<sym>/l3q/dt1000)。
输出  data/step06/<sym>/l3q/dt1000/<day>_g3.npz;reports/step14/l3q_catalog_<sym>.md
用法  python step14_l3q.py <sym> <V_LO> [--days d1,d2,d3]
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPRO, "a"))
sys.path.insert(0, os.path.join(REPRO, "b"))
import bellman as BM           # noqa: E402
import step06_catalog as S6    # noqa: E402
import step13_run as S13R      # noqa: E402

LAM_USDT = 0.0005


def main(sym, V_LO, days):
    md = [f"# Step 14 第 5 条 —— {sym}:L3 队列口径(V_L 含同价位前方量)重估的 Catalog vs Part A(base)", "",
          "## 需求矩(训练窗 20 日,g3 目录所用)", "", "| 测试日 | 口径 | μ_c⁺ | μ_p⁺ (tick) | μ_c⁻ | μ_p⁻ | μ_cp⁺ | μ_cp⁻ |", "|---|---|---|---|---|---|---|---|"]
    cmp_rows = ["| 测试日 | 距终端 步 | 方 | base L 均值 | l3q L 均值 | 差(l3q − base) | \\|差\\| 均值 | 相关 | base dL/dI | l3q dL/dI |", "|---|---|---|---|---|---|---|---|---|---|"]
    for day in days:
        for tag in ("base", "l3q"):
            p = os.path.join(REPRO, "data", "step06", sym, tag, "dt1000", f"{day}_g3.npz")
            if not os.path.exists(p):
                S6.build(sym, day, 1000, ("g3",), tag, lam_usdt=LAM_USDT)
            w = S6.training_window(sym, day, 1000, tag)
            mom = S6.window_moments(sym, w, 1000, tag)
            mp, mm = mom["plus"], mom["minus"]
            md.append(f"| {day} | {tag} | {mp['mu_c']:.4f} | {mp['mu_p']:.1f} | {mm['mu_c']:.4f} | {mm['mu_p']:.1f} | {mp['mu_cp']:.3f} | {mm['mu_cp']:.3f} |")
        cb, tb = S6.load_catalog(os.path.join(REPRO, "data", "step06", sym, "base", "dt1000", f"{day}_g3.npz"))
        cq, tq = S6.load_catalog(os.path.join(REPRO, "data", "step06", sym, "l3q", "dt1000", f"{day}_g3.npz"))
        seen = np.where((tb["count"] > 30) & (tq["count"] > 30))[0]
        Is = np.arange(-8 * V_LO, 8 * V_LO + 1, V_LO)
        N = cb.N
        for togo in (1, 60, 3600, N // 2):
            k = N + 1 - togo
            for side, idx in (("L⁺", 0), ("L⁻", 1)):
                B_, Q_ = [], []
                for gi in seen:
                    for I in Is:
                        B_.append(BM.optimal_L(cb, k, int(gi), float(I))[idx]); Q_.append(BM.optimal_L(cq, k, int(gi), float(I))[idx])
                B_, Q_ = np.array(B_), np.array(Q_)
                slb = np.mean([np.polyfit(Is, B_[i * len(Is):(i + 1) * len(Is)], 1)[0] for i in range(len(seen))])
                slq = np.mean([np.polyfit(Is, Q_[i * len(Is):(i + 1) * len(Is)], 1)[0] for i in range(len(seen))])
                corr = float(np.corrcoef(B_, Q_)[0, 1]) if B_.std() > 0 and Q_.std() > 0 else float("nan")
                cmp_rows.append(f"| {day} | {togo} | {side} | {B_.mean():.1f} | {Q_.mean():.1f} | {(Q_ - B_).mean():+.1f} | {np.abs(Q_ - B_).mean():.1f} | {corr:+.3f} | {slb:+.4f} | {slq:+.4f} |")
    md += ["", "## 最优报价对比(g 取两窗内计数 > 30 的状态;I 取 ±8·V_LO 网格;距终端步数配对)", ""] + cmp_rows
    md += ["", "说明:l3q 口径下 V_L 更大 → 同一吃单量下虚拟单成交更少,需求曲线的 (c,p) 变化;本表只比目录报价,不重放 PnL(任务书 Step 14.5 只要求报价差异)。"]
    rep = os.path.join(REPRO, "reports", "step14"); os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"l3q_catalog_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md)); print("L3Q_DONE", flush=True)


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    days = sys.argv[sys.argv.index("--days") + 1].split(",") if "--days" in sys.argv else S13R.SCAN_DAYS
    main(sym, V_LO, days)
