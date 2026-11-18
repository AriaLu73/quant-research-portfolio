"""Step 13.8 退化对拍:γ → 0、ē = 0、终端改成 P1 的二次形(−λ y²)时,QVI 的最优挂单距离应退化回 Step 6 的 Catalog 报价。
对齐方式:两者都以"距终端的步数"配对 —— QVI 第 k 步(n_steps − k 步到段末)↔ Catalog 第 N + 1 − (n_steps − k) 步(同样步数到日末)。
两种需求口径各对一次:
  (i) P1 字面线性需求 Q = c(p − L)(可负、无封顶,q_clip=False)—— 与 Catalog 同一需求模型,残差只来自 48 对经验样本(EC-38)、14 点 L 网格、y 网格(EC-42);
  (ii) EC-37 截断需求 Q = min(max(c(p − L), 0), V_LO)—— Part B 实际使用的口径,差异即 EC-37 的后果。
输出  reports/step13/check_degenerate_<sym>.md
用法  python step13_check.py <sym> <V_LO> [--day 20261016]
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "a"))
import bellman as BM           # noqa: E402
import step06_catalog as S6    # noqa: E402
import step13_build as S13     # noqa: E402

LAM_USDT = 0.0005


def compare(sym, V_LO, day, cat, tabs, lam_tick, q_clip, lab):
    q, meta = S13.build(sym, V_LO, day, gamma=0.0, dt_ms=1000, e_bar=0, terminal="quadratic", lam_q=lam_tick, save=False, store_phi=False, q_clip=q_clip)
    n_steps = meta["n_steps"]; N = cat.N
    seen = np.where(tabs["count"] > 30)[0]
    s0 = 0                                                   # 二次终端、无市价单时 s 不进入目标
    ys = q.y[np.abs(q.y) <= 8 * V_LO]
    i_y0 = int(np.argmin(np.abs(ys)))
    md = [f"# Step 13.8 退化对拍 —— {sym} {day}:QVI(γ=0, ē=0, 终端 −λy², λ_tick={lam_tick:g})vs Step 6 Catalog(g3)—— 需求口径:{lab}", "",
          f"QVI:Y={q.Y}(Δy={q.dy:g}), L 网格 {len(q.L)} 点 {q.L.tolist()};Catalog:N={N}。配对按距终端步数;y 取 |y| ≤ 8·V_LO 的网格点({len(ys)} 个),g 取窗内计数 > 30 的状态({len(seen)} 个)。", "",
          "## 全部点", "",
          "| 距终端 步 | 方 | Catalog L 均值 | QVI L 均值 | 均值差 | \\|差\\| 均值 | \\|差\\| p90 | 相关(跨 y×g) | Catalog dL/dy | QVI dL/dy | Catalog L 落在 L 网格内的占比 | y=0 处 Catalog L | y=0 处 QVI L |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    inside_rows = ["| 距终端 步 | 方 | 点数 | Catalog L 均值 | QVI L 均值 | 均值差 | \\|差\\| 均值 | \\|差\\| 中位 | 相关 |", "|---|---|---|---|---|---|---|---|---|"]
    for togo in (1, 5, 30, 120, 300):
        kq = n_steps - togo; kc = N + 1 - togo
        if kq < 0 or kc < 0:
            continue
        for side, key in (("L⁺", "Lp"), ("L⁻", "Lm")):
            C, Q = [], []
            for gi in seen:
                for y in ys:
                    Lp, Lm = BM.optimal_L(cat, kc, int(gi), float(y))
                    C.append(Lp if key == "Lp" else Lm)
                    j = int(np.clip(np.round((y + q.y[-1]) / q.dy), 0, q.Y - 1))
                    Q.append(float(q.L[q.pol[key][kq, j, s0, int(gi)]]))
            C, Q = np.array(C), np.array(Q); d = Q - C
            sl_c = np.mean([np.polyfit(ys, C[i * len(ys):(i + 1) * len(ys)], 1)[0] for i in range(len(seen))])
            sl_q = np.mean([np.polyfit(ys, Q[i * len(ys):(i + 1) * len(ys)], 1)[0] for i in range(len(seen))])
            msk = (C >= q.L.min()) & (C <= q.L.max())
            y0 = np.array([(i % len(ys)) == i_y0 for i in range(len(C))])
            corr = float(np.corrcoef(C, Q)[0, 1]) if C.std() > 0 and Q.std() > 0 else float("nan")
            md.append(f"| {togo} | {side} | {C.mean():.1f} | {Q.mean():.1f} | {d.mean():+.1f} | {np.abs(d).mean():.1f} | {np.percentile(np.abs(d), 90):.1f} | {corr:+.3f} | {sl_c:+.4f} | {sl_q:+.4f} | {msk.mean():.0%} | {C[y0].mean():.1f} | {Q[y0].mean():.1f} |")
            if msk.any():
                dm = d[msk]; cm = float(np.corrcoef(C[msk], Q[msk])[0, 1]) if C[msk].std() > 0 and Q[msk].std() > 0 else float("nan")
                inside_rows.append(f"| {togo} | {side} | {int(msk.sum())} | {C[msk].mean():.1f} | {Q[msk].mean():.1f} | {dm.mean():+.1f} | {np.abs(dm).mean():.1f} | {np.median(np.abs(dm)):.1f} | {cm:+.3f} |")
    md += ["", f"## 只取 Catalog L 在 QVI 网格范围 [{q.L.min():g}, {q.L.max():g}] 内的点", ""] + inside_rows
    md += ["", "判读:QVI 的 L 只能取网格值,|差| 的下界是网格间距的一半;相关与 dL/dy 同号、同量级即视为退化成立。"
           "线性需求口径下的残差只来自 48 对样本(EC-38)、L 网格与 y 网格;截断口径下的差异是 EC-37 的后果:L·E[c(p−L)⁺] 对 L 单调不减,封顶后收入 ≈ L·V_LO,把 y=0 处的报价推到网格最远点。", ""]
    return md


def main(sym, V_LO, day):
    c = S13.CONTRACTS[sym]
    lam_tick = LAM_USDT / (float(c["tick"]) * float(c["mult"]))
    cat, tabs = S6.load_catalog(os.path.join(REPRO, "data", "step06", sym, "base", "dt1000", f"{day}_g3.npz"))
    md = []
    for q_clip, lab in ((False, "P1 字面线性需求 Q = c(p−L)(可负、无封顶)"), (True, "EC-37 截断需求 Q = min(max(c(p−L),0), V_LO)(Part B 实际用)")):
        md += compare(sym, V_LO, day, cat, tabs, lam_tick, q_clip, lab)
    rep = os.path.join(REPRO, "reports", "step13"); os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"check_degenerate_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md)); print("CHECK_DONE", flush=True)


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    main(sym, V_LO, sys.argv[sys.argv.index("--day") + 1] if "--day" in sys.argv else "20261016")
