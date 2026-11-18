#!/usr/bin/env python3
"""research3 LTK-0:大 tick 合约选品的逐合约-日统计(预登记 docs/research3/ltk_selection_2026-10-03.md)。
每个 (合约, 日),只用购买数据的 L1 事件与成交(data/research2/events):
  share1     真实吃单发生时点差 = 1 tick 的比例(Eisler et al. 2012;Dayri–Rosenbaum 表 1 的口径)
  tw_share1  按时间加权的 1 tick 点差占比
  eta        Dayri–Rosenbaum η̂ = N_c / (2 N_a),真实吃单成交价(显示最优价)序列的非零变动的延续 / 反转
  pi_bp      α_bp·(1/2 − η̂) + 返佣
  q_over_v   成交前本侧最优价队列 / 该笔真实吃单量(中位数;Wyart §3.3、Moallemi–Yuan)
  gamma_mu   中价变动次数 / 真实吃单次数(Moallemi–Yuan §4.3)
  net5       真实挂单方在显示最优价成交后 5 s 的毛收益 + 返佣(research3 的独立度量,f = min($1000, 成交额) 加权)
  质量:stale_share(盘口 > 60 s 不更新而其间有成交的时长占比)、beyond_share(真实吃单打在显示最优价之外的比例)
成对打印的判定与 scripts/research3/flow_anatomy.py 相同。
用法:Python314/python.exe scripts/research3/ltk_scan.py 20260910,20260918,20260924 [workers=6]
输出:data/research3/ltk/ltk_scan.jsonl(可续跑)与 .csv"""
import glob, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow_anatomy as FA      # noqa: E402  (load, SPECS, EV)

OUT = os.path.join(FA.ROOT, "data", "research3", "ltk")
CLIP = 1000.0


def rebate(sym):
    if sym.endswith("USDCM"):
        return 1.2
    return 0.8 if FA.SPECS[sym].get("class") in ("STOCK", "METAL", "COMMODITY") else 0.7


def eta_hat(px):
    """Dayri & Rosenbaum 2015 §2.3: η̂ = N_c / (2 N_a) on the non-zero changes of a price series (in ticks)."""
    d = np.diff(px.astype(np.int64))
    d = d[d != 0]
    if len(d) < 3:
        return np.nan, 0, 0, np.nan
    s = np.sign(d)
    nc = int((s[1:] == s[:-1]).sum())
    na = int((s[1:] != s[:-1]).sum())
    return (nc / (2 * na) if na else np.nan), nc, na, float((np.abs(d) == 1).mean())


def one(a):
    sym, day = a
    try:
        b, t, tick = FA.load(sym, day)
    except Exception as e:  # noqa: BLE001
        return dict(sym=sym, day=day, error=repr(e)[:160])
    if len(b) < 10 or len(t) < 10:
        return dict(sym=sym, day=day, error="too few rows")
    qts = b.ts.values.astype(np.int64)
    bb, ba = b.bb.values.astype(np.int64), b.ba.values.astype(np.int64)
    bq, aq = b.bq1.values.astype(float), b.aq1.values.astype(float)
    ok_book = ba > bb
    mid = (bb + ba) / 2.0
    # time-weighted spread = 1 tick
    dt = np.diff(np.r_[qts, qts[-1]]).astype(float)
    tw1 = float(dt[(ba - bb == 1) & ok_book].sum() / max(dt[ok_book].sum(), 1.0))
    # taker aggregates (same microsecond, same side), classification as in flow_anatomy.anatomy
    t = t.assign(usd=t.px.astype(float) * tick * t.qty.astype(float))
    g = t.groupby(["ts", "sgn"]).agg(pmin=("px", "min"), pmax=("px", "max"), usd=("usd", "sum"), qty=("qty", "sum")).reset_index().sort_values("ts")
    ts = g.ts.values.astype(np.int64)
    sg = g.sgn.values.astype(int)
    i0 = np.searchsorted(qts, ts, side="left") - 1
    keep = i0 >= 0
    g, ts, sg, i0 = g[keep].reset_index(drop=True), ts[keep], sg[keep], i0[keep]
    fpx = np.where(sg > 0, g.pmin.values, g.pmax.values)
    touch = np.where(sg > 0, ba[i0], bb[i0])
    tsz = np.where(sg > 0, aq[i0], bq[i0])
    spr = ba[i0] - bb[i0]
    da = np.r_[0, np.diff(ba)]
    db = np.r_[0, np.diff(bb)]
    la = np.maximum.accumulate(np.where(da != 0, np.arange(len(qts)), 0))
    lb = np.maximum.accumulate(np.where(db != 0, np.arange(len(qts)), 0))
    j = np.where(sg > 0, la[i0], lb[i0])
    age = (ts - qts[j]) / 1000.0
    imp = np.where(sg > 0, da[j] < 0, db[j] > 0)
    k = sg * (fpx - touch)
    qty = g.qty.values.astype(float)
    pair = (k < 0) | ((k == 0) & (age <= 10) & imp & (np.abs(qty - tsz) <= 1e-6 * np.maximum(1, tsz)))
    real = ~pair & (spr > 0)
    beyond = real & (k > 0)
    # data quality: book silent > 60 s while trades print
    gaps = np.diff(qts)
    big = np.where(gaps > 60_000_000)[0]
    stale = 0.0
    for gi in big:
        lo, hi = qts[gi], qts[gi + 1]
        if ((ts > lo) & (ts < hi)).any():
            stale += hi - lo
    span = max(float(qts[-1] - qts[0]), 1.0)
    r = dict(sym=sym, day=day, cls=FA.SPECS[sym].get("class"), reb=rebate(sym), hours=span / 3.6e9,
             tick_bp=float(np.median(1e4 / mid[ok_book])) if ok_book.any() else np.nan,
             taker_usd=float(g.usd.sum()), real_usd=float(g.usd.values[real].sum()), n_real=int(real.sum()),
             pair_share=float(g.usd.values[pair].sum() / max(g.usd.sum(), 1e-9)),
             stale_share=stale / span, beyond_share=float(beyond.sum() / max(real.sum(), 1)), crossed_share=float((~ok_book).mean()))
    if real.sum() < 30:
        r["error"] = "fewer than 30 real taker orders"
        return r
    rs = real & ~beyond
    r["share1"] = float((spr[real] == 1).mean())
    r["tw_share1"] = tw1
    r["spread_ticks_med"] = float(np.median(spr[real]))
    e, nc, na, one_tick = eta_hat(touch[real])
    r.update(eta=e, n_cont=nc, n_alt=na, jump1_share=one_tick)
    r["pi_bp"] = r["tick_bp"] * (0.5 - e) + r["reb"] if e == e else np.nan
    r["q_over_v"] = float(np.median(tsz[rs] / np.maximum(qty[rs], 1e-12))) if rs.any() else np.nan
    mchg = int(((np.diff(bb) != 0) | (np.diff(ba) != 0))[ok_book[1:]].sum())
    r["gamma_mu"] = mchg / max(int(real.sum()), 1)
    # 1-minute mid volatility of the day, bp
    mm = pd.Series(mid[ok_book] * tick, index=pd.to_datetime(qts[ok_book], unit="us")).resample("1min").last().dropna()
    r["sigma_day_bp"] = float(np.sqrt((np.diff(np.log(mm.values)) ** 2).sum()) * 1e4) if len(mm) > 2 else np.nan
    # real maker at the displayed best: 5 s gross + rebate (f-weighted)
    at = rs & (k == 0)
    if at.any():
        tt = ts[at]
        m5 = mid[np.clip(np.searchsorted(qts, tt + 5_000_000, side="right") - 1, 0, len(qts) - 1)]
        e5 = sg[at] * (touch[at] - m5) / touch[at] * 1e4
        f = np.minimum(CLIP, g.usd.values[at])
        v = tt + 5_000_000 <= qts[-1]
        r["net5"] = float((e5[v] * f[v]).sum() / f[v].sum() + r["reb"]) if v.any() else np.nan
        r["n_at"] = int(at.sum())
    return r


def main():
    days = sys.argv[1].split(",")
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    os.makedirs(OUT, exist_ok=True)
    part = os.path.join(OUT, "ltk_scan.jsonl")
    done = set()
    if os.path.exists(part):
        done = {(r["sym"], str(r["day"])) for r in map(json.loads, open(part, encoding="utf-8"))}
    jobs = []
    for d in days:
        for p in glob.glob(os.path.join(FA.EV, f"book_*_{d}.parquet")):
            s = os.path.basename(p)[5:-(len(d) + 9)]
            if s in FA.SPECS and (s, d) not in done and os.path.exists(os.path.join(FA.EV, f"trades_{s}_{d}.parquet")):
                jobs.append((s, d))
    jobs.sort(key=lambda x: os.path.getsize(os.path.join(FA.EV, f"book_{x[0]}_{x[1]}.parquet")))
    print(len(jobs), "jobs", flush=True)
    with ProcessPoolExecutor(workers) as ex, open(part, "a", encoding="utf-8") as fh:
        for i, r in enumerate(ex.map(one, jobs, chunksize=2)):
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            if i % 100 == 0:
                print(i, r["sym"], r["day"], flush=True)
    pd.DataFrame([json.loads(l) for l in open(part, encoding="utf-8")]).to_csv(part.replace(".jsonl", ".csv"), index=False)
    print("LTK_SCAN_DONE", flush=True)


if __name__ == "__main__":
    main()
