#!/usr/bin/env python3
"""出货信号的增量(用户 10-16:"这样用,然后算增量"):在 obi_l1(按仓位方向取号)之上,
tox_ladderstretch / tox_l2hole / tox_bnpushnet / rls_lag15_hl5min 还多带多少关于"仓位接下来往哪走"的信息。只读,线下。

样本  和 factor_reeval_eval.py 的 B 一样:第三轮实盘组回测十天的持仓时刻(12–18 时 UTC,每 1 秒一个点),外加 10-14 实盘。
标签  H_τ = 仓位方向 × 之后 τ 秒中间价变动(bp),τ = 1、3、10 秒。
增量  逐天:因子的秩、标签的秩分别对 obi_l1 的秩做线性回归,取残差的相关(偏秩相关);另报两者合成后的 IC 比 obi_l1 单独高多少
      (合成 = 两个秩的等权和,方向按因子本身的号)。
用法  Python314/python.exe scripts/research7/exit_increment_20261016.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research7"))
import factor_reeval_eval as E                                      # noqa: E402

FAC = {"tox_ladderstretch": "side", "tox_l2hole": "side", "tox_bnpushnet": "side", "rls_lag15_hl5min": "dir"}
TAUS = (1, 3, 10)


def samples(fills, sample):
    out = []
    for day in sorted(fills["day"].unique()):
        for sym, (nat, j) in E.SYMS.items():
            t0, mid = E.grid_mid(day, nat)
            n = len(mid)
            fall = fills[(fills["symbol"] == sym) & (fills["day"] == day)].sort_values("ts_ns")
            grid_t = t0 + np.arange(500, n - 1100, 100, dtype=np.int64) * E.STEP
            ft, pa, fh = fall["ts_ns"].to_numpy(), fall["pos_after"].to_numpy(), fall["hour"].to_numpy()
            idx = np.searchsorted(ft, grid_t, side="right") - 1
            pos = np.where(idx >= 0, pa[np.clip(idx, 0, None)], 0.0)
            if sample == "bt":
                same_h = (idx >= 0) & (fh[np.clip(idx, 0, None)] == (grid_t // 3_600_000_000_000) % 24)
                pos = np.where(same_h, pos, 0.0)
            hold = np.abs(pos) > 1e-12
            r = ((grid_t[hold] - t0) // E.STEP).astype(np.int64)
            s = np.sign(pos[hold])
            d = {"day": day, "sym": sym}
            for tau in TAUS:
                d["H_%g" % tau] = s * (mid[r + tau * 100] - mid[r]) / mid[r] * 1e4
            d["obi_l1"] = s * E.load_factor(day, "obi_l1")[r - 1, j]
            for f, kind in FAC.items():
                if kind == "side":
                    a, b = E.load_factor(day, f + "_ask")[r - 1, j], E.load_factor(day, f + "_bid")[r - 1, j]
                    d[f] = np.where(s > 0, b, a)                     # 多仓怕买盘被扫 → _bid
                else:
                    d[f] = s * E.load_factor(day, f)[r - 1, j]
            out.append(pd.DataFrame(d))
            print("  %s %s %s 持仓点 %d" % (sample, day, sym, len(r)), flush=True)
    return pd.concat(out, ignore_index=True)


def rk(x):
    return pd.Series(x).rank().to_numpy()


def evaluate(df, tag):
    rows = []
    for sym, g0 in df.groupby("sym"):
        for f in FAC:
            for tau in TAUS:
                base, part, comb, alone = [], [], [], []
                for _, g in g0.groupby("day"):
                    x, o, y = g[f].to_numpy(), g["obi_l1"].to_numpy(), g["H_%g" % tau].to_numpy()
                    m = np.isfinite(x) & np.isfinite(o) & np.isfinite(y)
                    if m.sum() < 500:
                        continue
                    rx, ro, ry = rk(x[m]), rk(o[m]), rk(y[m])
                    ex = rx - np.polyval(np.polyfit(ro, rx, 1), ro)
                    ey = ry - np.polyval(np.polyfit(ro, ry, 1), ro)
                    sx = np.sign(np.corrcoef(rx, ry)[0, 1])
                    base.append(np.corrcoef(ro, ry)[0, 1])
                    alone.append(np.corrcoef(rx, ry)[0, 1])
                    part.append(np.corrcoef(ex, ey)[0, 1])
                    comb.append(np.corrcoef(ro + sx * rx, ry)[0, 1])
                if not base:
                    continue
                part = np.array(part)
                rows.append(dict(样本=tag, 合约=sym, 因子=f, τ秒=tau, 天数=len(base), obi单独IC=np.mean(base), 因子单独IC=np.mean(alone),
                                 偏IC_去掉obi后=part.mean(), 偏IC_t=part.mean() / part.std(ddof=1) * np.sqrt(len(part)) if len(part) > 1 else np.nan,
                                 合成IC=np.mean(comb), 合成比obi多=np.mean(comb) - np.mean(base)))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    bt = E.bt_fills()
    bt = bt[bt["day"].isin(E.BT_DAYS)]
    res = [evaluate(samples(bt, "bt"), "回测十天"), evaluate(samples(E.live_fills(), "live"), "实盘1014")]
    out = pd.concat(res, ignore_index=True)
    p = os.path.join(E.RE, "出货信号增量_20261016.csv")
    out.to_csv(p, index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print(out.round(3).to_string(index=False))
    print("写入", p)
