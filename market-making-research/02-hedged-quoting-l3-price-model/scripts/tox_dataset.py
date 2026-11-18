#!/usr/bin/env python3
"""research3 毒性可预测性(用户批评第 6/8 点:要的是 E[ΔP | fill, state],不是成交概率):
对每张"真实吃单打到显示最优价"的成交(挂单方视角),取成交前 L = 3 ms 就已知的状态,目标 = 挂单方 1/5/30/300 s 毛收益(bp)。
状态(全部带方向,正 = 对挂单方不利的方向):
  own_r_W   自身中价在 [t−L−W, t−L] 的收益 × 吃单方向(W = 0.1/1/10 s),单位 = 自身 60 s 波动(无量纲)
  lead_r_W  领先合约同窗口收益 × 吃单方向,单位 = 领先合约 60 s 波动
  gap       领先合约相对自身的偏离(log 比值 − 其 60 s EWMA)× 吃单方向,单位 = 自身 60 s 波动
  flow_W    同向真实吃单额(过去 W)/ 该合约当日每秒真实吃单额中位…(用 log1p 比值)
  imb       被打一侧盘口量相对对侧;spr 点差 tick;half_bp;vol60(bp);age_ms 被打侧最优价年龄;dt_last 距上一张真实吃单(s)
输出 data/research3/tox_<name>.parquet。用法:python tox_dataset.py commod | alts"""
import glob, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow_anatomy as FA

L_US = 3000
WS = [0.1, 1.0, 10.0]


def grid_vol(qts, mid):
    """1 s 网格上的 60 s 滚动波动(bp,每 1 s 收益的标准差),返回 (grid_ts, vol)。只用过去。"""
    g = np.arange(qts[0], qts[-1], 1_000_000); m = mid[np.clip(np.searchsorted(qts, g, side="right") - 1, 0, len(qts) - 1)]
    r = np.r_[0, np.diff(np.log(m))] * 1e4
    v = pd.Series(r).rolling(60, min_periods=20).std().bfill().values
    return g, np.maximum(v, 1e-3), m


def at(g, v, t):
    return v[np.clip(np.searchsorted(g, t, side="right") - 1, 0, len(g) - 1)]


def build(a):
    sym, day, tardis, lead = a
    try:
        X = FA.anatomy(sym, day, tardis=tardis)
        if tardis:
            b, _, tick, s2 = FA.load_tardis(sym, day)
        else:
            b, _, tick = FA.load(sym, day); s2 = sym
        qts = b.ts.values.astype(np.int64); mid = (b.bb.values + b.ba.values) / 2.0
        X = X[~X.pair & (X.cat == "at")].reset_index(drop=True)
        ts = X.ts.values.astype(np.int64); sg = X.sg.values; t0 = ts - L_US
        gv, vol, _ = grid_vol(qts, mid); v0 = at(gv, vol, t0)
        def mat(t):
            return mid[np.clip(np.searchsorted(qts, t, side="right") - 1, 0, len(qts) - 1)]
        m0 = mat(t0)
        for W in WS:
            X[f"own_r_{W:g}"] = sg * (np.log(m0) - np.log(mat(t0 - int(W * 1e6)))) * 1e4 / (v0 * np.sqrt(max(W, 0.1)))
        X["vol60"] = v0
        # 同向真实吃单流(不含本单)
        cs = np.cumsum(X.usd.values * sg); tsr = ts
        for W in (1.0, 10.0):
            lo = np.searchsorted(tsr, t0 - int(W * 1e6), side="right"); hi = np.searchsorted(tsr, t0, side="right")
            fl = (np.r_[0, cs][hi] - np.r_[0, cs][lo]) * sg
            X[f"flow_{W:g}"] = np.sign(fl) * np.log1p(np.abs(fl) / 1000.0)
        X["dt_last"] = np.r_[3600.0, np.diff(ts) / 1e6]
        if lead:
            lb = pd.read_parquet(os.path.join(FA.EV, f"book_{lead}_{day}.parquet"), columns=["ts", "bb", "ba"])
            lts = lb.ts.values.astype(np.int64); lmid = (lb.bb.values + lb.ba.values) / 2.0
            lgv, lvol, lgm = grid_vol(lts, lmid); lv0 = at(lgv, lvol, t0)
            def lat(t):
                return lmid[np.clip(np.searchsorted(lts, t, side="right") - 1, 0, len(lts) - 1)]
            l0 = lat(t0)
            for W in WS:
                X[f"lead_r_{W:g}"] = sg * (np.log(l0) - np.log(lat(t0 - int(W * 1e6)))) * 1e4 / (lv0 * np.sqrt(max(W, 0.1)))
            # 偏离:log(lead/own) 减其 60 s EWMA(1 s 网格,只用过去)
            gm = mid[np.clip(np.searchsorted(qts, lgv, side="right") - 1, 0, len(qts) - 1)]
            ratio = np.log(lgm) - np.log(gm); base = pd.Series(ratio).ewm(span=60, adjust=False).mean().shift(1).bfill().values
            X["gap"] = sg * ((np.log(l0) - np.log(m0)) - at(lgv, base, t0)) * 1e4 / v0
            X["lead_vol60"] = lv0
        X["sym"] = s2
        return X
    except Exception as e:  # noqa: BLE001
        print("ERR", a, repr(e)[:200], flush=True)
        return None


def main():
    name = sys.argv[1]
    if name == "commod":
        twins = {"XAUTUSDTM": "PAXGUSDTM", "PAXGUSDTM": "XAUTUSDTM", "CLUSDTM": "BZUSDTM", "BZUSDTM": "CLUSDTM", "XAGUSDTM": "XAUTUSDTM", "NATGASUSDTM": "CLUSDTM"}
        jobs = []
        for s, ld in twins.items():
            for p in sorted(glob.glob(os.path.join(FA.EV, f"book_{s}_*.parquet"))):
                d = os.path.basename(p).split("_")[-1][:8]
                if os.path.exists(os.path.join(FA.EV, f"book_{ld}_{d}.parquet")):
                    jobs.append((s, d, False, ld))
    else:
        tags = sorted({os.path.basename(p).split("-")[1] for dd in ("tardis_kualt", "tardis_kualt2") for p in glob.glob(os.path.join(FA.ROOT, "data", dd, "quotes-ku_*-*.csv.gz"))})
        jobs = [(t, d, True, "BTC") for t in tags for d in ["20251001", "20260101", "20260401", "20260601", "20260701", "20260801", "20260901"]
                if any(os.path.exists(os.path.join(FA.ROOT, "data", x, f"quotes-{t}-{d}.csv.gz")) for x in ("tardis_kualt", "tardis_kualt2"))]
    print(len(jobs), "jobs", flush=True)
    with ProcessPoolExecutor(int(sys.argv[2]) if len(sys.argv) > 2 else 4) as ex:
        parts = [x for x in ex.map(build, jobs) if x is not None]
    D = pd.concat(parts, ignore_index=True); D.to_parquet(os.path.join(FA.ROOT, "data", "research3", f"tox_{name}.parquet"))
    print("saved", len(D), flush=True)


if __name__ == "__main__":
    main()
