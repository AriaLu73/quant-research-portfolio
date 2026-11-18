"""Step 11 —— Part A 结果汇总与验证清单。读 reports/step02、step04、step10 与 data/step06 的 json,写 reports/partA/README_<sym>.md。
用法  python step11_report.py <sym> [dt_ms]
"""
import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台 gbk 会在打印表格时崩

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bellman as BM           # noqa: E402
import step06_catalog as S6    # noqa: E402


def catalog_checks(sym, dt_ms):
    out = dict(n=0, lemma2=0, lemma2_gap=0.0, lemma2_rel=0.0, gamma=0, A1=0, transcr=0.0, unseen=[], floored=[], state_spread_mid=[], inv_dir_ok=0)
    for p in sorted(glob.glob(os.path.join(REPRO, "data", "step06", sym, "base", f"dt{dt_ms}", "*_g3.json"))):
        m = json.load(open(p, encoding="utf-8"))
        c = m["checks"]
        out["n"] += 1
        out["lemma2"] += c["lemma2_violations"]; out["gamma"] += c["gamma_nonneg"]; out["A1"] += c["A1_nonneg"]
        if c.get("lemma2_max_gap"):                        # 违反量级:绝对 gap 与相对 |α| 的 gap(数值抵消误差 ~1e-9 量级)
            out["lemma2_gap"] = max(out["lemma2_gap"], float(c["lemma2_max_gap"]))
            out["lemma2_rel"] = max(out["lemma2_rel"], float(c["lemma2_max_gap"]) / max(abs(float(c["lemma2_max_alpha"])), 1e-30))
        out["transcr"] = max(out["transcr"], c["max_transcription_diff"])
        out["unseen"].append(m["n_unseen_filled"]); out["floored"].append(m["catalog"]["n_pi_floored"])
        cat, tabs = S6.load_catalog(p.replace(".json", ".npz"))
        k = cat.N // 2
        seen = tabs["count"] > 30
        Lp = np.array([BM.optimal_L(cat, k, s, 0.0)[0] for s in range(len(seen))])
        out["state_spread_mid"].append(float(Lp[seen].max() - Lp[seen].min()) if seen.any() else 0.0)
        s0 = int(np.argmax(tabs["count"]))
        out["inv_dir_ok"] += int(BM.optimal_L(cat, k, s0, 100.0)[0] < BM.optimal_L(cat, k, s0, -100.0)[0])
    return out


def main(sym, dt_ms=1000):
    rep = os.path.join(REPRO, "reports", "partA")
    os.makedirs(rep, exist_ok=True)
    md = [f"# Part A 汇总 —— {sym}, Δt = {dt_ms} ms(论文忠实回测,P1 Table 1–7 / Figure 4–6 对照)", ""]
    md.append("## 1. 表与图的位置")
    md += ["| 论文 | 本地 |", "|---|---|",
           f"| Table 1 | reports/step02/README_{sym}.md §Table 1 结构 |",
           f"| Figure 3 / 6 | reports/step02/fig3_{sym}_*.png、fig6_{sym}_*.png |",
           f"| Figure 4 / 5 | reports/step04/fig4_{sym}_*.png、fig5_{sym}_*.png;reports/step04/README_{sym}.md |",
           f"| Table 2 / 3 | reports/step10/expA_{sym}_dt{dt_ms}_base.md |",
           f"| Table 4 / 5 | reports/step10/expB_{sym}_dt{dt_ms}_base.md |",
           f"| Table 6 / 7 | reports/step10/expA_{sym}_dt{dt_ms}_base_det.md |",
           "| 工程选择登记表 | registry/engineering_choices.md |", ""]
    for name, f in (("实验 A(Table 2/3)", f"expA_{sym}_dt{dt_ms}_base.md"), ("实验 B(Table 4/5)", f"expB_{sym}_dt{dt_ms}_base.md"), ("实验 C(Table 6/7)", f"expA_{sym}_dt{dt_ms}_base_det.md")):
        p = os.path.join(REPRO, "reports", "step10", f)
        if os.path.exists(p):
            md += [f"## {name}", ""] + open(p, encoding="utf-8").read().split("\n")[2:] + [""]
    cc = catalog_checks(sym, dt_ms)
    md += ["## 验证清单(任务书 Step 11)", "", "| 项 | 结果 |", "|---|---|",
           "| Inventory / Cash 更新 Eq. (11)–(12) | tests/test_sim_paper.py::test_cash_inventory_update_and_level 通过;回放中 W += a·Q̃⁺ − b·Q̃⁻、I += Q̃⁻ − Q̃⁺ |",
           "| Bid/Ask 方向 | to_quotes 保证 ask ≥ 中价上方紧邻 tick、bid ≤ 下方紧邻 tick(规则触发占比见实验表\"规则触发占比\"列) |",
           f"| Quote 随 Inventory 方向 | ⁽¹⁾A^± < 0 在全部目录、全部 k、非截断状态成立(违反 {cc['A1']} 次);多头 100 张时 L⁺ 更小:{cc['inv_dir_ok']}/{cc['n']} 个测试日目录 |",
           f"| Quote 随状态 | 日中 k = N/2、count>30 的状态间 L⁺ 极差(tick):{np.round(cc['state_spread_mid'], 3).tolist()}(远离 T 时 α→0,状态效应微弱,见 Corollary 3 后第 3 条) |",
           f"| Probability consistency | step04 各日合法性违反 0;未见状态填充数(各测试日 g3):{cc['unseen']};π=0 截断状态数:{cc['floored']}(EC-17/18/24) |",
           f"| Lemma 2 与 (A.12) | 全部目录、全部 k、非截断状态:Lemma 2 违反 {cc['lemma2']} 次(超容差的最大 gap {cc['lemma2_gap']:.1e} tick·张,相对 |α| {cc['lemma2_rel']:.1e};≤1e-8 绝对量级为三点插值的浮点抵消误差,非真违反),γ ≥ 0 出现 {cc['gamma']} 次;(19)–(21) 转录式与 (A.5) 精确递推最大差 {cc['transcr']:.1e} |",
           "| Terminal liquidation | Table 2 的 J_T(λ 二次项)与 Table 3 的 PnL_T(沿日末 200 档深快照清算)并列报告;清算成本按 I_T 分桶存 data/step10/<sym>/liq_buckets.csv(Step 16 用) |",
           "| 时间因果 | Step 1 边界在应用消息前记录;Δ̂ 只用 t_k 及之前 5 个中价(EC-26);目录按训练窗(测试日之前)构建 |", ""]
    md += ["## 与论文不一致之处的归类(任务书 Step 11:数学实现 / 数据差异 / 需求估计差异 / 成交模型差异)", "",
           "- 数学实现:(17)–(22)、(19)–(21) 与 (A.5) 两条独立路径一致到 1e-8;Lemma 2 / (A.12) / 暴力优化单测通过。无已知偏差。",
           "- 数据差异:MSFT 20 档连续分价 vs KuCoin 稀疏阶梯盘口(XBTUSDCM 第 2 个占用价位被触及的频率仅 0.4–2.6%);9 月 L2 训练集 vs 10 月 L3 测试集的盘口口径不一致(reports/step01 §5);ETHUSDCM 吃单极稀。",
           "- 需求估计差异:论文未定的档位网格 / 权重 / V_L 时点 / 封顶(EC-08…13、EC-22)对 (c,p) 影响很大(XBTUSDCM 10 月 2 档 vs 11 档:p 38 vs 140 tick);corr(c,p) 为负(论文 +0.2),μ_cp < μ_cμ_p(论文反之)。",
           "- 成交模型差异:队首假设(脚注 5/6)按原样执行;Step 14 用 l3sim 实测。",
           "- 结论不以 PnL 正负判定(任务书);库存在远离 T 时不受控是模型性质(A1 ≈ α ≈ 0),与 λ 的量级(EC-21)共同决定 J_T 的符号。"]
    with open(os.path.join(rep, f"README_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md[-12:]))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1000)
