"""Step 16 —— 按本地盘口校准 P2 的清算函数 L(x,y,p,s) = x + yp − |y|s/2 − ε(ε = 0;taker 比例费两边同样进入,比较时不含费)。
采样  train + validation 内每分钟的 200 档深快照(ladder_store deep_lad);库存网格 I = V_LO × {1,2,3,5,8,13,21,34,55}(两个方向)。
实际  卖出 I 沿 bid 侧走簿、买回 |I| 沿 ask 侧走簿:x + S̄_t(I)·I;预测:x + I·p_t − |I|·s_t/2,p_t、s_t 为当时中价与点差。
残差  r_t(I) = 实际 − 预测(tick×张;折 USDT 与 bp);按 |I|、小时、点差桶汇总;报告残差超过 半 tick/张 与 maker 返佣(我方费率 / 我方费率 折 tick/张)的 |I| 起点。
对照  Step 9 保存的 Part A 实际清算成本(data/step10/<sym>/liq_buckets.csv)按 I_T 分桶叠画。
输出  reports/step16/table12_<sym>.md、fig9_<sym>.png
用法  python step16_liq.py <sym> <V_LO>
"""
import datetime as dt
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
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "data"))
import ladder_store as LS         # noqa: E402
import spread_chain as SC         # noqa: E402
import step13_build as B          # noqa: E402

with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as _fh:
    CONTRACTS = yaml.safe_load(_fh)
MULTS = [1, 2, 3, 5, 8, 13, 21, 34, 55]
NS = 1_000_000_000


def tv_intervals(sym):
    with open(os.path.join(REPRO, "config", "splits", f"{sym}.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    return [(x["start_ns"], x["end_ns"]) for k in ("train", "validation") for x in cfg["split"][k]["intervals"]]


def walk(lad_side, qty):
    """沿一侧深快照成交 qty 张:返回 (平均价 tick, 不足张数)。"""
    got, left = 0.0, float(qty)
    for t, v in lad_side.astype(float):
        if v <= 0 or left <= 0:
            continue
        take = min(left, v); got += take * t; left -= take
    return (got / (qty - left) if qty - left > 0 else np.nan), left


def main(sym, V_LO):
    c = CONTRACTS[sym]
    tick, mult = float(c["tick"]), float(c["mult"])
    unit = tick * mult
    iv = tv_intervals(sym)
    ch = B.spread_chain_for(sym)
    rows = []
    for p in sorted(glob.glob(os.path.join(REPRO, "data", "step01", sym, "202610*.npz"))):
        z = LS.load(p, keys=("deep_ts", "deep_lad"))
        for ts, lad in zip(z["deep_ts"], z["deep_lad"]):
            if not any(a <= ts < b for a, b in iv):
                continue
            if lad[0, 0, 1] <= 0 or lad[1, 0, 1] <= 0:
                continue
            bb, ba = int(lad[0, 0, 0]), int(lad[1, 0, 0])
            mid, s = (bb + ba) / 2.0, ba - bb
            hour = int((ts // NS) % 86400 // 3600)
            for mlt in MULTS:
                I = mlt * V_LO
                for sign, side in ((+1, 0), (-1, 1)):            # 多头卖给 bid 侧;空头从 ask 侧买回
                    Sbar, short = walk(lad[side], I)
                    actual = sign * I * Sbar if np.isfinite(Sbar) else np.nan
                    pred = sign * I * mid - I * s / 2.0
                    rows.append((ts, hour, ch.state(s), mlt, sign, I, actual - pred, short, mid, s))
    R = np.array(rows, dtype=float)
    os.makedirs(os.path.join(REPRO, "reports", "step16"), exist_ok=True)
    mid_med = np.median(R[:, 8])
    rebate_ticks = {"我方费率": 0.7e-4 * mid_med, "我方费率": OUR_FEE * mid_med}
    md = [f"# Table 12 —— {sym}:P2 清算函数 L 的残差 r_t(I) = 实际沿深度清算 − (I·p − |I|·s/2)(train + validation,每分钟深快照,{len(np.unique(R[:, 0]))} 个采样时刻)", "",
          f"单位:tick×张;每张残差 = r/|I|(tick)。阈值:半 tick = 0.5 tick/张;maker 返佣 我方费率 ≈ {rebate_ticks['我方费率']:.0f} tick/张、我方费率 ≈ {rebate_ticks['我方费率']:.0f} tick/张(按中价中位 {mid_med:.0f} tick)。", "",
          "| \\|I\\|(张) | \\|I\\|/V_LO | 方向 | 残差/张 中位(tick) | p10 | p90 | 残差>半tick 占比 | 残差>我方费率 占比 | 残差>我方费率 占比 | 深度不足占比 | 残差 USDT 中位 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    curve = {}
    for mlt in MULTS:
        for sign, lab in ((+1, "卖出多头"), (-1, "买回空头")):
            m = (R[:, 3] == mlt) & (R[:, 4] == sign) & np.isfinite(R[:, 6])
            per = -R[m, 6] / R[m, 5]                               # 成本为正:预测 − 实际
            I = mlt * V_LO
            md.append(f"| {I:,} | {mlt} | {lab} | {np.median(per):.2f} | {np.percentile(per, 10):.2f} | {np.percentile(per, 90):.2f} | {(per > 0.5).mean():.1%} | "
                      f"{(per > rebate_ticks['我方费率']).mean():.1%} | {(per > rebate_ticks['我方费率']).mean():.1%} | {(R[(R[:, 3] == mlt) & (R[:, 4] == sign), 7] > 0).mean():.1%} | {np.median(-R[m, 6]) * unit:.3f} |")
            curve[(mlt, sign)] = (np.median(per), np.percentile(per, 10), np.percentile(per, 90))
    # 失效起点
    def first_exceed(th):
        for mlt in MULTS:
            if max(curve[(mlt, 1)][0], curve[(mlt, -1)][0]) > th:
                return mlt * V_LO
        return None
    md += ["", f"线性冲击(与单量无关)假设失效的 |I| 起点(残差/张中位数首次超过阈值):半 tick → {first_exceed(0.5)};我方费率 → {first_exceed(rebate_ticks['我方费率'])};我方费率 → {first_exceed(rebate_ticks['我方费率'])}(None = 网格内未超过)。", ""]
    # 按小时 / 点差桶(|I| = 8·V_LO)
    md += ["## 按小时(|I| = 8·V_LO,两方向合并,残差/张中位 tick)", "", "| 小时 | " + " | ".join(str(h) for h in range(24)) + " |", "|---|" + "---|" * 24]
    m8 = (R[:, 3] == 8) & np.isfinite(R[:, 6])
    md.append("| 中位 | " + " | ".join(f"{np.median(-R[m8 & (R[:, 1] == h), 6] / R[m8 & (R[:, 1] == h), 5]):.2f}" if (m8 & (R[:, 1] == h)).any() else "–" for h in range(24)) + " |")
    md += ["", "## 按点差桶(|I| = 8·V_LO)", "", "| 桶 | 代表点差 tick | 残差/张 中位 | 样本 |", "|---|---|---|---|"]
    for si in range(ch.m):
        mm = m8 & (R[:, 2] == si)
        md.append(f"| s{si} | {ch.rep[si]:.0f} | {np.median(-R[mm, 6] / R[mm, 5]) if mm.any() else float('nan'):.2f} | {int(mm.sum())} |")
    # Part A 的实际清算成本对照(Step 9 分桶)
    lb = os.path.join(REPRO, "data", "step10", sym, "liq_buckets.csv")
    if os.path.exists(lb):
        A = [l.strip().split(",") for l in open(lb, encoding="utf-8") if l.strip()]
        IT = np.array([abs(float(a[5])) for a in A]); cost = np.array([float(a[7]) for a in A])
        md += ["", "## 对照:Part A(Step 9)日末实际清算成本(USDT)按 |I_T| 分桶", "", "| \\|I_T\\| 区间 | 条数 | 成本中位 USDT | 每张 tick |", "|---|---|---|---|"]
        edges = [0, V_LO, 3 * V_LO, 8 * V_LO, 21 * V_LO, 1e9]
        for a, b in zip(edges[:-1], edges[1:]):
            mm = (IT >= a) & (IT < b) & (IT > 0)
            if mm.any():
                md.append(f"| [{a:,.0f}, {b:,.0f}) | {int(mm.sum())} | {np.median(cost[mm]):.3f} | {np.median(cost[mm] / IT[mm]) / unit:.2f} |")
    md += ["", "不引入 λ、不拟合二次项(任务书 Step 16.6)。y_max 的依据见 EC-31。"]
    with open(os.path.join(REPRO, "reports", "step16", f"table12_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    # Figure 9
    fig, ax = plt.subplots(figsize=(8, 4.5))
    xs = [m * V_LO for m in MULTS]
    for sign, lab, col in ((1, "sell long into bids", "tab:blue"), (-1, "buy back short from asks", "tab:red")):
        med = [curve[(m, sign)][0] for m in MULTS]; lo = [curve[(m, sign)][1] for m in MULTS]; hi = [curve[(m, sign)][2] for m in MULTS]
        ax.plot(xs, med, "o-", color=col, label=f"{lab}: median residual per contract"); ax.fill_between(xs, lo, hi, color=col, alpha=0.15)
    ax.axhline(0.5, ls="--", color="gray", label="half tick"); ax.axhline(rebate_ticks["我方费率"], ls=":", color="green", label="我方费率 rebate"); ax.axhline(rebate_ticks["我方费率"], ls=":", color="purple", label="我方费率 rebate")
    ax.set_xscale("log"); ax.set_yscale("symlog", linthresh=1); ax.set_xlabel("|I| (contracts)"); ax.set_ylabel("cost beyond P2 linear L (ticks per contract)")
    ax.set_title(f"Figure 9 type: {sym} residual of P2 liquidation function vs inventory (train+validation)"); ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(os.path.join(REPRO, "reports", "step16", f"fig9_{sym}.png"), dpi=120)
    print("\n".join(md[:16]))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
