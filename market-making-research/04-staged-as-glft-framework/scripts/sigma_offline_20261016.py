#!/usr/bin/env python3
"""波动 σ 的线下核对(用户 10-16 同意"波动这一块先做线下核对和短回放")。只读,不是回测。

问题  实盘现在 σ = 前一天估的常数;策略第 8 步已写好 σ = rv_scale × rv_ewm_10s(实时)。哪个更准、rv_scale 该取多少。
做法  data/factors/grid 的 10 毫秒中间价(每天 12–18 时 UTC),BTC、ETH,全部有网格的日子(04-01 除外);每 1 秒取一个点 t:
        预测 A = 前一个可用日 12–18 时 1 秒对数变动的均方根(bp/√秒)—— 实盘口径的近似
        预测 B = rv_ewm_10s(策略第 8 步原式,bp/√秒)
        实际   = 之后 τ 秒的已实现波动 sqrt(RV_τ / τ)(bp/√秒),τ = 1、10、60 秒
      指标:QLIKE(方差口径,越小越好)、|log(实际/预测)| 的中位数、实际/预测 的中位数(= 不偏时该乘的倍数)、秩相关(逐天)。
用法  Python314/python.exe scripts/research7/sigma_offline_20261016.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research7"))
import factor_reeval_eval as E                                      # noqa: E402  rv_feats、grid_mid 共用

TAUS = (1, 10, 60)
DAYS = sorted(f[-12:-4] for f in os.listdir(E.GRID) if f.startswith("XBTUSDTM_") and "20260401" not in f)
rows = []
for sym, (nat, _) in E.SYMS.items():
    prev_sig, prev_scale, low_frac = None, 1.0, (np.nan, np.nan)
    for day in DAYS:
        t0, mid = E.grid_mid(day, nat)
        rv1, rvew, cs = E.rv_feats(mid)
        r1 = 1e4 * np.diff(np.log(mid[::100]))
        sig_today = float(np.sqrt(np.nanmean(r1 * r1)))
        if prev_sig is not None:
            n = len(mid)
            rr = np.arange(1100, n - 6000, 100)
            for tau in TAUS:
                k = rr + tau * 100
                real = np.sqrt(np.maximum(cs[k] - cs[rr], 0) / tau)
                rv_raw = rvew[rr - 1]
                cands = (("前一天常数", np.full(len(rr), prev_sig)), ("rv_ewm_10s", rv_raw),
                         ("rv_ewm_10s×前日倍数,下限 0.25×前日常数", np.maximum(prev_scale * rv_raw, 0.25 * prev_sig)))
                if tau == 10:
                    low_frac = (np.mean(rv_raw < 0.25 * prev_sig), np.mean(rv_raw < 0.1 * prev_sig))
                for name, pred in cands:
                    m = np.isfinite(pred) & (pred > 0) & np.isfinite(real)
                    p, y = pred[m], real[m]
                    v = (y / p) ** 2
                    pos = y > 0
                    yv, pv = y * y, p * p
                    mz = np.corrcoef(pv, yv)[0, 1] ** 2 if np.std(pv) > 0 else np.nan     # 方差对方差的相关平方(Mincer–Zarnowitz R²)
                    rows.append(dict(sym=sym, day=day, tau=tau, pred=name, mz_r2=mz, low25=low_frac[0] if tau >= 10 else np.nan, low10=low_frac[1] if tau >= 10 else np.nan,
                                     qlike=np.mean(v - np.log(np.where(pos, v, 1)) - 1) if pos.any() else np.nan,
                                     abslog=np.median(np.abs(np.log(y[pos] / p[pos]))), ratio_med=np.median(y / p),
                                     ratio_rms=np.sqrt(np.mean(y * y)) / np.sqrt(np.mean(p * p)),
                                     ic=np.corrcoef(pd.Series(p).rank(), pd.Series(y).rank())[0, 1] if np.std(p) > 0 else np.nan))
        rr_all = np.arange(1100, len(mid) - 6000, 100)                     # 今天的倍数 = 已实现 1 秒波动均方根 / rv_ewm_10s 均方根,明天用
        rv_t = rvew[rr_all - 1]
        rl = np.sqrt(np.maximum(cs[rr_all + 1000] - cs[rr_all], 0) / 10)
        mm = np.isfinite(rv_t)
        prev_scale = float(np.sqrt(np.mean(rl[mm] ** 2)) / np.sqrt(np.mean(rv_t[mm] ** 2)))
        prev_sig = sig_today
    print("  %s 完成" % sym, flush=True)
df = pd.DataFrame(rows)
out = os.path.join(ROOT, "data", "research7", "sigma_offline_20261016.csv")
df.to_csv(out, index=False, encoding="utf-8-sig")
g = df.groupby(["sym", "tau", "pred"]).agg(days=("day", "nunique"), qlike_median=("qlike", "median"), abslog=("abslog", "mean"), mz_r2=("mz_r2", "mean"),
                                            ratio_rms=("ratio_rms", "median"), ic=("ic", "mean"), low25=("low25", "mean"), low10=("low10", "mean")).reset_index()
print("σ 预测对比(%d 天,每天 12–18 时,每 1 秒一个点;QLIKE、|log 误差| 越小越好;倍数 = 实际 / 预测 的逐天中位数,1 = 不偏)" % df["day"].nunique())
print(g.round(3).to_string(index=False))
w = df.pivot_table(index=["sym", "day", "tau"], columns="pred", values="qlike").dropna()
w["rv 更好"] = w["rv_ewm_10s"] < w["前一天常数"]
print("\n逐天 QLIKE:rv_ewm_10s 胜过前一天常数的天数比例")
print(w.groupby(level=["sym", "tau"])["rv 更好"].mean().round(2).to_string())
print("写入", out)
