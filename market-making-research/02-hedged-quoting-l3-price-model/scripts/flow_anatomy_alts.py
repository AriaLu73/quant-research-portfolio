#!/usr/bin/env python3
"""research3 H-C2/H-C3:74 个山寨永续 × 7 个月首日的流量解剖(剔除成对打印后,真实挂单方在显示最优价的收益)。
每 (合约, 日) 一行汇总 → data/research3/flow_anatomy_alts.csv;增量 jsonl 可续跑。"""
import glob, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow_anatomy as FA

DAYS = ["20251001", "20260101", "20260401", "20260601", "20260701", "20260801", "20260901"]


def one(a):
    tag, day = a
    try:
        X = FA.anatomy(tag, day, tardis=True)
    except Exception as e:  # noqa: BLE001
        return dict(tag=tag, day=day, error=repr(e)[:150])
    def w(x, c):
        return float((x[c] * x.f).sum() / x.f.sum()) if x.f.sum() else None
    real = X[~X.pair & (X.cat != "in")]; at = real[real.cat == "at"]
    r = dict(tag=tag, sym=X.sym.iloc[0], day=day, taker_usd=float(X.usd.sum()), orders=len(X), pair_share=float(X.usd[X.pair].sum() / X.usd.sum()), real_usd=float(real.usd.sum()),
             at_usd=float(at.usd.sum()), at_f=float(at.f.sum()), spr_med=float(X.spr.median()), tick_bp=float(X.tick_bp.median()), half_bp=float(X.half_bp.median()),
             beyond_share=float(real.usd[real.cat == "beyond"].sum() / max(1e-9, real.usd.sum())), thru_share=float(at.usd[at.thru].sum() / max(1e-9, at.usd.sum())))
    for h in FA.HS:
        v = at[at[f"v{h}"]]; r[f"at_e{h}"] = w(v, f"e{h}")
    for nm, m in (("spr1", at.spr <= 1), ("spr2", at.spr == 2), ("spr3p", at.spr >= 3), ("partial", ~at.thru), ("thru", at.thru),
                  ("opp_big", at.imb <= -0.33), ("same_big", at.imb >= 0.33), ("flat", at.imb.abs() < 0.33)):
        v = at[m]; r[f"{nm}_f"] = float(v.f.sum()); r[f"{nm}_e5"] = w(v, "e5"); r[f"{nm}_e30"] = w(v[v.v30], "e30")
    return r


def main():
    tags = sorted({os.path.basename(p).split("-")[1] for d in ("tardis_kualt", "tardis_kualt2") for p in glob.glob(os.path.join(FA.ROOT, "data", d, "quotes-ku_*-*.csv.gz"))})
    part = os.path.join(FA.ROOT, "data", "research3", "flow_anatomy_alts.jsonl")
    done = set()
    if os.path.exists(part):
        done = {(json.loads(l)["tag"], json.loads(l)["day"]) for l in open(part, encoding="utf-8")}
    jobs = [(t, d) for t in tags for d in DAYS if (t, d) not in done and any(os.path.exists(os.path.join(FA.ROOT, "data", x, f"quotes-{t}-{d}.csv.gz")) for x in ("tardis_kualt", "tardis_kualt2"))]
    print(len(tags), "tags", len(jobs), "jobs", flush=True)
    with ProcessPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 4) as ex, open(part, "a", encoding="utf-8") as fh:
        for r in ex.map(one, jobs):
            fh.write(json.dumps(r) + "\n"); fh.flush()
    D = pd.DataFrame([json.loads(l) for l in open(part, encoding="utf-8")]); D.to_csv(part.replace(".jsonl", ".csv"), index=False)
    print("ALL DONE", len(D), flush=True)


if __name__ == "__main__":
    main()
