"""Step 13.6 —— P2 Figure 3 型策略切片:(y, s) 平面上的挂单区 M 与吃单区 T(买入 / 卖出),近 T 与远 T 两张,按 g 状态分面(取样本最多的 4 个 g)。
用法  python figures_partB.py <sym> <day> <gamma> <e_bar> [dt_ms]   → reports/step13/fig3_<sym>_<day>_g<γ>.png
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402
import numpy as np                # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "a"))
import step13_build as B          # noqa: E402
import step06_catalog as S6       # noqa: E402


def main(sym, day, gamma, e_bar, dt_ms=1000):
    q, meta = B.load(os.path.join(REPRO, "data", "step13", sym, f"dt{dt_ms}", f"{day}_g{gamma:g}_e{e_bar:g}.npz"))
    z = np.load(os.path.join(REPRO, "data", "step06", sym, "base", f"dt{dt_ms}", f"{day}_g3.npz"))
    gs = np.argsort(-z["count"])[:4]
    n = q.pol["e"].shape[0]
    fig, axes = plt.subplots(2, 4, figsize=(16, 7), sharex=True, sharey=True)
    for row, (k, lab) in enumerate(((0, "far from T (k=0)"), (n - 5, f"near T (k={n - 5})"))):
        for col, g in enumerate(gs):
            e = q.pol["e"][k, :, :, g]                                     # [Y,S]
            Lp = q.L[q.pol["Lp"][k, :, :, g]]; Lm = q.L[q.pol["Lm"][k, :, :, g]]
            img = np.where(e > 0, 1.0, np.where(e < 0, -1.0, 0.0))
            ax = axes[row, col]
            ax.imshow(img.T, aspect="auto", origin="lower", cmap="bwr", vmin=-1, vmax=1, extent=[q.y[0], q.y[-1], -0.5, q.S - 0.5])
            # 挂单区内标注 L⁺/L⁻ 的中位数
            m = e == 0
            txt = f"M: L+ med {np.median(Lp[m]) if m.any() else np.nan:.0f}, L- med {np.median(Lm[m]) if m.any() else np.nan:.0f}"
            ax.set_title(f"g={g} ({S6.AR.GState('g3').label(int(g))}) {lab}\n{txt}", fontsize=8)
            ax.set_yticks(range(q.S)); ax.set_yticklabels([f"s{i}:{r:.0f}t" for i, r in enumerate(q.srep)], fontsize=7)
            if row == 1:
                ax.set_xlabel("inventory y (contracts)")
    fig.suptitle(f"P2 Figure 3 type: {sym} {day}, γ={gamma:g}, ē={e_bar:g}; red = BUY at market, blue = SELL at market, white = limit-order zone M", fontsize=10)
    fig.tight_layout()
    out = os.path.join(REPRO, "reports", "step13", f"fig3_{sym}_{day}_g{gamma:g}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=110)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5]) if len(sys.argv) > 5 else 1000)
