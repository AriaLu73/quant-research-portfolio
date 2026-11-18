"""Step 14 报告(Table 10 + Figure 8):
  3. ahead0 分布(分位数、按 |L| 档、按 g、按小时)与 "ahead0 = 0" 占比(脚注 5/6 成立的比例);
  4. 同一时段、同一报价序列的三种成交量:(a) 脚注 5/6 队首假设(Part A 的 sim_paper)、(b) l3sim 精确排队、(c) V_L 改为 "严格优于 + 同价位前方量" 的 Step 2 公式;
  6. 改价撤单放弃的 ahead 与新单 ahead0 的分布。
输入  data/step14/<sym>/<day>_<agent>.npz;(a)(c) 由 sim_paper 在同一天重放 M_g3(论文忠实 / vl_queue)得到。
用法  python step14_report.py <sym> <V_LO> [--days d1,d2] [--gamma 1e-4]
"""
import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402
import numpy as np                # noqa: E402
import yaml                       # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPRO, "a"))
import arrivals as AR             # noqa: E402
import sim_paper as SP            # noqa: E402
import step06_catalog as S6       # noqa: E402

with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as _fh:
    CONTRACTS = yaml.safe_load(_fh)
L_BUCKETS = [(0, 1), (1, 3), (3, 10), (10, 30), (30, 100), (100, 1e9)]


def paper_fills(sym, day, V_LO, vl_queue):
    c = CONTRACTS[sym]
    cat, _ = S6.load_catalog(os.path.join(REPRO, "data", "step06", sym, "base", "dt1000", f"{day}_g3.npz"))
    g = AR.GState("g3")
    out, fr = SP.simulate(sym, day, 1000, [SP.CatalogPolicy("M_g3", cat, g)], g, V_LO, 0.0005, float(c["tick"]), float(c["mult"]), vl_queue=vl_queue)
    r = out["M_g3"]["series"]
    return int(r["qp"].sum() + r["qm"].sum()), int(((r["qp"] > 0) | (r["qm"] > 0)).sum()), r


def main(sym, V_LO, days, gamma):
    rows = []
    md = [f"# Table 10 —— {sym}:脚注 5/6 队首假设的实测(l3sim 精确排队,固定延迟;ahead0 = 进簿时同价前方张数)", ""]
    a0_all, a0_byL, a0_byg, a0_byh, rq_all = [], {b: [] for b in L_BUCKETS}, {}, {}, []
    md += ["| 日 | agent | 下单数 | ahead0=0 占比 | ahead0 p50/p90/p99(张) | 成交(部分)次数 | 成交张数 | 全成交单 | 撤单 | 断流 | 进簿→成交 p50 ms | 改价次数 | 改价放弃 ahead p50/p90 | 市价单 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    tri = ["", "## 三种成交量(同一天、M_g3 报价序列)", "", "| 日 | (a) 队首假设 张 / 成交区间 | (b) l3sim 1.8 ms 张 / 成交次数 | (c) V_L 含同价位前方量 张 / 区间 | (b)/(a) | (c)/(a) |", "|---|---|---|---|---|---|"]
    for day in days:
        files = sorted(glob.glob(os.path.join(REPRO, "data", "step14", sym, f"{day}_*.npz")))
        if not files:
            continue
        lsim_b = None
        for p in files:
            z = np.load(p); name = os.path.basename(p)[9:-4]
            rec, fl, rq = z["records"], z["fills"], z["requotes"]
            live = rec[rec[:, 5] >= 0]; a0 = live[:, 5]
            if "P1_M_g3_L1.8" in name:
                lsim_b = (int(fl[:, 3].sum()) if len(fl) else 0, int(len(fl)))
                a0_all.append(a0)
                # 按 |L|(用 level0 = 离同侧最优价 tick 数的绝对值作代理)、按小时
                lv = np.abs(live[:, 9]); hrs = ((live[:, 1] // 10**9) % 86400) // 3600
                for lo, hi in L_BUCKETS:
                    a0_byL[(lo, hi)].append(a0[(lv >= lo) & (lv < hi)])
                for h in range(24):
                    a0_byh.setdefault(h, []).append(a0[hrs == h])
                rq_all.append(rq)
            md.append(f"| {day} | {name} | {len(rec):,} | {(a0 == 0).mean():.1%} | {np.percentile(a0, 50):.0f}/{np.percentile(a0, 90):.0f}/{np.percentile(a0, 99):.0f} | {len(fl):,} | {int(fl[:, 3].sum()) if len(fl) else 0:,} | "
                      f"{int((rec[:, 7] == 1).sum())} | {int((rec[:, 7] == 2).sum()):,} | {int((rec[:, 7] == 3).sum())} | {np.median(fl[:, 6]) / 1e6 if len(fl) else float('nan'):.0f} | {len(rq):,} | "
                      f"{np.percentile(rq[:, 4], 50) if len(rq) else float('nan'):.0f}/{np.percentile(rq[:, 4], 90) if len(rq) else float('nan'):.0f} | {len(z['mos'])} |")
        qa, na, _ = paper_fills(sym, day, V_LO, False)
        qc, nc, _ = paper_fills(sym, day, V_LO, True)
        if lsim_b:
            tri.append(f"| {day} | {qa:,} / {na:,} | {lsim_b[0]:,} / {lsim_b[1]:,} | {qc:,} / {nc:,} | {lsim_b[0] / max(qa, 1):.3f} | {qc / max(qa, 1):.3f} |")
        print(day, "done", flush=True)
    a0 = np.concatenate(a0_all) if a0_all else np.zeros(0)
    md += ["", f"## ahead0 分布(P1_M_g3, 1.8 ms, 全部日合计 {len(a0):,} 张单)", "",
           f"ahead0 = 0 占比 {(a0 == 0).mean():.1%};p50/p90/p99 = {np.percentile(a0, 50):.0f}/{np.percentile(a0, 90):.0f}/{np.percentile(a0, 99):.0f} 张。", "",
           "| 离同侧最优价 \\|level0\\| 档 | 单数 | ahead0=0 占比 | p50 | p90 |", "|---|---|---|---|---|"]
    for b in L_BUCKETS:
        x = np.concatenate(a0_byL[b]) if a0_byL[b] else np.zeros(0)
        if len(x):
            md.append(f"| [{b[0]}, {b[1] if b[1] < 1e9 else '∞'}) | {len(x):,} | {(x == 0).mean():.1%} | {np.percentile(x, 50):.0f} | {np.percentile(x, 90):.0f} |")
    md += ["", "| 小时 | " + " | ".join(str(h) for h in range(24)) + " |", "|---|" + "---|" * 24,
           "| ahead0=0 占比 | " + " | ".join(f"{np.concatenate(a0_byh[h]).__eq__(0).mean():.0%}" if h in a0_byh and len(np.concatenate(a0_byh[h])) else "–" for h in range(24)) + " |"]
    rq = np.concatenate(rq_all) if rq_all else np.zeros((0, 6))
    if len(rq):
        md += ["", f"## 改价撤单的队列位置损失(P1_M_g3, 1.8 ms;{len(rq):,} 次改价)", "", f"放弃的 ahead:p50/p90/p99 = {np.percentile(rq[:, 4], 50):.0f}/{np.percentile(rq[:, 4], 90):.0f}/{np.percentile(rq[:, 4], 99):.0f} 张;原单 ahead0 p50 = {np.percentile(rq[:, 5], 50):.0f}。"]
    md += tri
    md += ["", "说明:(a) 为论文忠实回测(sim_paper,脚注 5/6);(b) 为引擎按 L3 进簿序号排队 + post-only + 1.8 ms 延迟;(c) 为把 V_L 改成 '严格优于 + 同价位前方量' 后的 Step 2 公式成交量。三者报价序列相同,但 (b) 的报价由引擎盘口即时算出,与 (a)(c) 的 50 ms 网格盘口有微小差别。"]
    rep = os.path.join(REPRO, "reports", "step14"); os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"table10_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    if len(a0):
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.hist(np.minimum(a0, 2000), bins=60); ax.set_yscale("log"); ax.set_xlabel("ahead0 (contracts ahead at same price when resting; clipped at 2000)"); ax.set_ylabel("orders")
        ax.set_title(f"Figure 8 type: {sym} ahead0 distribution, P1_M_g3 @1.8 ms ({(a0 == 0).mean():.1%} zero)"); fig.tight_layout()
        fig.savefig(os.path.join(rep, f"fig8_{sym}.png"), dpi=120)
    print("\n".join(md[:14]))


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    arg = lambda f, d: sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d
    days = arg("--days", None)
    days = days.split(",") if days else sorted({os.path.basename(p)[:8] for p in glob.glob(os.path.join(REPRO, "data", "step14", sym, "*_summary.json"))})
    main(sym, V_LO, days, float(arg("--gamma", "1e-4")))
