#!/usr/bin/env python3
"""research3 长尾体检(目标口径:月成交 $1,000 万 ≈ $33 万/天,每美元净 ≥ 1 bp):
对购买数据里每个 (合约, 日):剔除成对打印后,真实吃单打到显示最优价时**真实挂单方**的 1/5/30/300 s 毛收益(不需排队假设),
并做"一直挂在最优价、只接真实吃单、每笔 ≤ clip、库存 ±3 clip、日末按中价"的现金结算(含返佣:USDT 我方费率,USDC 我方费率)。
输出 data/research3/longtail_scan.jsonl / .csv。用法:python longtail_scan.py 20260910,20260918,20260924 [workers]"""
import glob, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow_anatomy as FA

CLIPS = (1000.0, 200.0)


def one(a):
    sym, day = a
    try:
        X = FA.anatomy(sym, day)
    except Exception as e:  # noqa: BLE001
        return dict(sym=sym, day=day, error=repr(e)[:120])
    reb = 1.2 if sym.endswith("USDCM") else 0.7
    real = X[~X.pair & (X.cat != "in")]; at = real[real.cat == "at"].sort_values("ts")
    r = dict(sym=sym, day=day, cls=FA.SPECS[sym].get("class"), reb=reb, taker_usd=float(X.usd.sum()), pair_share=float(X.usd[X.pair].sum() / max(1e-9, X.usd.sum())), real_usd=float(real.usd.sum()),
             n_at=len(at), at_usd=float(at.usd.sum()), at_f=float(at.f.sum()), spr_med=float(X.spr.median()) if len(X) else None, tick_bp=float(X.tick_bp.median()) if len(X) else None,
             half_bp=float(X.half_bp.median()) if len(X) else None, thru_share=float(at.usd[at.thru].sum() / max(1e-9, at.usd.sum())))
    for h in FA.HS:
        v = at[at[f"v{h}"]]; r[f"e{h}"] = float((v[f"e{h}"] * v.f).sum() / v.f.sum()) if v.f.sum() else None
    for clip in CLIPS:
        pos = cash = vol = 0.0; n = 0
        for sg, px, usd, m0 in zip(at.sg.values, at.px.values, at.usd.values, at.mid0.values):
            d = -sg; pu = pos * m0
            if (d > 0 and pu >= 3 * clip - 1e-9) or (d < 0 and pu <= -3 * clip + 1e-9):
                continue
            f = min(clip, usd); pos += d * f / px; cash -= d * f; vol += f; n += 1
        leg = cash + pos * at.mid_end.iloc[0] if len(at) else 0.0
        k = int(clip)
        r[f"vol{k}"] = vol; r[f"leg{k}"] = leg; r[f"net{k}"] = leg + vol * reb / 1e4; r[f"fills{k}"] = n; r[f"endpos{k}"] = pos * at.mid_end.iloc[0] if len(at) else 0.0
    return r


def main():
    days = sys.argv[1].split(","); workers = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    part = os.path.join(FA.ROOT, "data", "research3", "longtail_scan.jsonl")
    done = set()
    if os.path.exists(part):
        done = {(r["sym"], str(r["day"])) for r in map(json.loads, open(part, encoding="utf-8"))}
    jobs = []
    for d in days:
        for p in glob.glob(os.path.join(FA.EV, f"book_*_{d}.parquet")):
            s = os.path.basename(p)[5:-(len(d) + 9)]
            if s in FA.SPECS and (s, d) not in done and os.path.exists(os.path.join(FA.EV, f"trades_{s}_{d}.parquet")):
                jobs.append((s, d))
    print(len(jobs), "jobs", flush=True)
    with ProcessPoolExecutor(workers) as ex, open(part, "a", encoding="utf-8") as fh:
        for r in ex.map(one, jobs, chunksize=4):
            fh.write(json.dumps(r) + "\n"); fh.flush()
    pd.DataFrame([json.loads(l) for l in open(part, encoding="utf-8")]).to_csv(part.replace(".jsonl", ".csv"), index=False)
    print("LONGTAIL_DONE", flush=True)


if __name__ == "__main__":
    main()
