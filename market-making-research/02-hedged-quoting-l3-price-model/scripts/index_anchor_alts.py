#!/usr/bin/env python3
"""research3 H-I(指数锚)在山寨合约上的检验(预注册:策略档案第 21 节)。复用 research4/index_anchor_hist.py 的定义,不改参数;
只把指数目录换成 data/research3/index_hist、返佣换成 我方费率、输出放 data/research3/index_anchor_alts_<day>.parquet(不碰 research4 的文件)。
用法:python index_anchor_alts.py build 20260910,20260924,20260918,20260921
      python index_anchor_alts.py report 20260910,20260924,20260918,20260921"""
import os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research4")); sys.path.insert(0, os.path.join(ROOT, "scripts", "research3"))
import index_anchor_hist as H
H.IDX = os.path.join(ROOT, "data", "research3", "index_hist"); H.REBATE = OUR_FEE
OUT = os.path.join(ROOT, "data", "research3")
SYMS = open(os.path.join(OUT, "index_syms_alts.txt")).read().strip().split(",")


def one(a):
    s, d = a
    try:
        return H.rows(s, d)
    except Exception as e:  # noqa: BLE001
        print("ERR", s, d, repr(e)[:160], flush=True)
        return None


def build(days, workers=5):
    for day in days:
        path = os.path.join(OUT, f"index_anchor_alts_{day}.parquet")
        old = pd.read_parquet(path) if os.path.exists(path) else None
        done = set(old.sym.unique()) if old is not None else set()
        jobs = [(s, day) for s in SYMS if s not in done and os.path.exists(os.path.join(H.IDX, f"{s}_{day}.csv.gz")) and os.path.exists(os.path.join(H.FA.EV, f"book_{s}_{day}.parquet"))]
        with ProcessPoolExecutor(workers) as ex:
            parts = [r for r in ex.map(one, jobs) if r is not None and len(r)]
        if old is not None:
            parts.insert(0, old)
        if parts:
            X = pd.concat(parts, ignore_index=True); X.to_parquet(path); print(day, "contracts", X.sym.nunique(), "rows", len(X), flush=True)


def report(days):
    X = pd.concat([pd.read_parquet(os.path.join(OUT, f"index_anchor_alts_{d}.parquet")) for d in days if os.path.exists(os.path.join(OUT, f"index_anchor_alts_{d}.parquet"))], ignore_index=True)
    X["day"] = X.day.astype(str)
    X = X[(X.cat == "at") & (X.age > H.MIN_AGE_MS)]
    nd = X.day.nunique(); pd.set_option("display.width", 230)
    print(f"山寨:天 {sorted(X.day.unique())},合约 {X.sym.nunique()},真实吃单打到已存在 >20 ms 的最优价 {len(X)} 笔,可接额(单笔封顶 $1k)${X.f.sum() / nd:,.0f}/天")
    g = X[X.e300.notna()]
    print(f"无条件:300 s 净 {np.average(g.e300, weights=g.f) + H.REBATE:+.2f} bp;30 s 净 {np.average(X[X.e30.notna()].e30, weights=X[X.e30.notna()].f) + H.REBATE:+.2f}")
    print("\n[1] 按 edge(挂单方成交价相对指数公平价有利多少 bp)"); print(H.bucket_table(X, "edge", H.EDGE_BINS).round(2).to_string(index=False))
    print("\n[2] 按 edge / 5 分钟波动"); print(H.bucket_table(X, "edge_n", H.EDGEN_BINS).round(2).to_string(index=False))
    print("\n[3] 按 lag(公平价领先 KuCoin 中价、沿吃单方向 bp)"); print(H.bucket_table(X, "lag", H.LAG_BINS).round(2).to_string(index=False))
    print("\n[4] 对照:只按离 KuCoin 中价的距离(不用指数)"); print(H.bucket_table(X, "e0", H.EDGE_BINS).round(2).to_string(index=False))
    P = X[X.edge > 2]; gp = P[P.e300.notna()]
    lo, hi = H.boot(gp, "e300"); pt = np.average(gp.e300, weights=gp.f) + H.REBATE
    dn = gp.groupby("day").apply(lambda x: np.average(x.e300, weights=x.f) + H.REBATE, include_groups=False)
    usd_day = P.f.sum() / nd
    c1, c2, c3 = (pt > 0) and (lo + H.REBATE > 0), int((dn > 0).sum()) >= min(3, nd), usd_day >= 333_000
    print(f"\n主检验(预注册):edge > 2 bp → 占真实可接额 {P.f.sum() / X.f.sum():.1%},可接额 ${usd_day:,.0f}/天;300 s 净 {pt:+.2f} bp [{lo + H.REBATE:+.2f}, {hi + H.REBATE:+.2f}];各日 {dn.round(2).to_dict()}")
    print(f"① 点估计与区间下界 > 0:{c1} ② ≥3 天为正:{c2} ③ 日可接额 ≥ $33 万:{c3}"); print("结论:", ("通过(候选,仅 %d 天)" % nd if nd < 4 else "通过(候选)") if (c1 and c2 and c3) else "不通过")
    s = gp.groupby("sym").apply(lambda x: pd.Series(dict(f=x.f.sum(), net300=np.average(x.e300, weights=x.f) + H.REBATE)), include_groups=False)
    print(f"合约层面:edge>2 的 300 s 净为正的合约 {int((s.net300 > 0).sum())}/{len(s)};按可接额最大的 12 个:"); print(s.sort_values("f", ascending=False).head(12).round(2).to_string())


def stage2(days):
    """第二阶段(预注册:门槛在 09-10 上定,只在其余天检验):A = edge > 10 bp;B = edge_n > 0.5。"""
    X = pd.concat([pd.read_parquet(os.path.join(OUT, f"index_anchor_alts_{d}.parquet")) for d in days], ignore_index=True)
    X["day"] = X.day.astype(str); X = X[(X.cat == "at") & (X.age > H.MIN_AGE_MS)]; nd = X.day.nunique()
    g0 = X[X.e300.notna()]
    print(f"检验日 {sorted(X.day.unique())},合约 {X.sym.nunique()};真实可接额 ${X.f.sum() / nd:,.0f}/天;无条件 300 s 净 {np.average(g0.e300, weights=g0.f) + H.REBATE:+.2f} bp")
    for name, m in (("A: edge > 10 bp", X.edge > 10), ("B: edge_n > 0.5", X.edge_n > 0.5), ("主检验口径: edge > 2 bp", X.edge > 2)):
        P = X[m]; out = [f"== {name}:占真实可接额 {P.f.sum() / X.f.sum():.1%},${P.f.sum() / nd:,.0f}/天"]
        res = {}
        for h in (30, 300, 1800):
            g = P[P[f"e{h}"].notna()]; lo, hi = H.boot(g, f"e{h}"); res[h] = (np.average(g[f"e{h}"], weights=g.f) + H.REBATE, lo + H.REBATE, hi + H.REBATE)
            out.append(f"   {h:>4} s 净 {res[h][0]:+.2f} bp [{res[h][1]:+.2f}, {res[h][2]:+.2f}]")
        g = P[P.e300.notna()]
        dn = g.groupby("day").apply(lambda x: np.average(x.e300, weights=x.f) + H.REBATE, include_groups=False)
        s_ = g.groupby("sym").apply(lambda x: np.average(x.e300, weights=x.f) + H.REBATE, include_groups=False)
        c1, c2, c3 = res[300][0] > 0 and res[300][1] > 0, int((dn > 0).sum()) >= 2, P.f.sum() / nd >= 333_000
        out.append(f"   各日 300 s 净 {dn.round(2).to_dict()};合约为正 {int((s_ > 0).sum())}/{len(s_)};半点差(额加权){np.average(P.half_bp, weights=P.f):.1f} bp,成交价离中价 {np.average(P.e0, weights=P.f):.1f} bp")
        out.append(f"   ① 点估计与区间下界 > 0:{c1} ② ≥2 天为正:{c2} ③ 日可接额 ≥ $33 万:{c3} → {'通过(候选)' if (c1 and c2 and c3) else '不通过'}")
        print(); print(*out, sep="\n")


if __name__ == "__main__":
    days = sys.argv[2].split(",")
    {"build": build, "report": report, "stage2": stage2}[sys.argv[1]](days)
