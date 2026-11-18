#!/usr/bin/env python3
"""用我们的因子报价(用户 10-16:"用我们的因子报价，按你说的试一下")——线下估两张表,给快速版测试文件用。只读。

状态 x  三个现成因子:自己的买一卖一失衡 obi_l1;tox_bnpush 卖侧值 bnA;tox_bnpush 买侧值 bnB(RD 原定义,10 毫秒网格)。
        分档:obi_l1 按五分位(4 个边界),bnA、bnB 各按三分位(2 个边界),共 45 格;边界用 10-13 的分布定。
α 表   α(τ, x) = 10-13(12–18 时 UTC)每 10 毫秒一个时刻,之后 τ 的中间价变动(bp)按格平均;τ = 10、50、100 毫秒。
        样本外检查:10-14 同时段,查表值 vs 实际变动的秒 IC 与十分位差。
M 表   M_side(τ, x) = 真实挂在本侧最优价(进簿时价格 = 当时本侧最优价)的单被打到之后 τ 的 markout(bp,挂单方向,按成交额加权),
        按成交时刻的状态分格。数据:BTC-USDT L3,10-14 的 15、16、17 时(与回放用的 13、14 时不重叠;因子网格只有 12–18 时)。
        进簿不到 5 毫秒就被打掉的成交剔除(先挂后吃的对敲,与回放同口径)。中间价用 10 毫秒网格。
报价    e_买(x) = ρ + α(x) − J_买(x),e_卖(x) = ρ − α(x) − J_卖(x);J 定义为"被成交这件事带来的额外不利走势",
        J_买 = α − M_买、J_卖 = −α − M_卖,所以 e_side = ρ + M_side(x)。ρ = 返佣 我方费率。格内成交少于 30 笔时用这一侧全部成交的平均。
        决策用的 τ = 10-13 上 IC 最高的时长(用户 10-16:因子按测出来最有用的时长用,看到因子就立刻行动)。
输出    data/research7/alpha_quote_table_20261016.json(边界、α 表、M 表、e 表)
用法    .venv/Scripts/python.exe scripts/research7/alpha_quote_table_20261016.py
"""
import gzip, json, os, sys
import numpy as np
import orjson
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research7"))
import factor_reeval_eval as E      # noqa: E402

TAUS = (1, 5, 10, 30, 50, 100, 200, 500)   # 网格行数(10 毫秒一行)= 10 毫秒 … 5 秒;决策用的时长 = 10-13 上 IC 最高的那个
RHO = 0.7
J_BTC = 0


def state(day):
    g = np.load(os.path.join(E.GRID, "XBTUSDTM_%s.npz" % day))
    t0, n = int(g["t0"]), len(g["ok"])
    ok = g["ok"] & (g["ap"] > g["bp"])
    mid = pd.Series(np.where(ok, (g["ap"] + g["bp"]) / 2.0 * float(g["tick"]), np.nan)).ffill().to_numpy()
    bq, aq = g["bs"][:, 0].astype(float), g["as_"][:, 0].astype(float)
    obi = np.where(bq + aq > 0, (bq - aq) / (bq + aq), np.nan)
    tx = np.load(os.path.join(E.TOX1, "%s.npz" % day))
    return dict(t0=t0, n=n, ok=ok, mid=mid, obi=obi, bnA=tx["tox_bnpush_ask"][:, J_BTC].astype(float),
                bnB=tx["tox_bnpush_bid"][:, J_BTC].astype(float), bp=g["bp"].astype(np.int64), ap=g["ap"].astype(np.int64))


def cell(S, idx, ed):
    a = np.searchsorted(ed["obi"], S["obi"][idx], side="right")
    b = np.searchsorted(ed["bnA"], S["bnA"][idx], side="right")
    c = np.searchsorted(ed["bnB"], S["bnB"][idx], side="right")
    return a * 9 + b * 3 + c


tr = state("20261013")
m = tr["ok"] & np.isfinite(tr["obi"]) & np.isfinite(tr["bnA"]) & np.isfinite(tr["bnB"])
ed = dict(obi=np.nanquantile(tr["obi"][m], [0.2, 0.4, 0.6, 0.8]).tolist(), bnA=np.nanquantile(tr["bnA"][m], [1 / 3, 2 / 3]).tolist(),
          bnB=np.nanquantile(tr["bnB"][m], [1 / 3, 2 / 3]).tolist())
idx = np.flatnonzero(m)
idx = idx[idx < tr["n"] - 520]
c_tr = cell(tr, idx, ed)
alpha = {}
for k in TAUS:
    y = (tr["mid"][idx + k] - tr["mid"][idx]) / tr["mid"][idx] * 1e4
    s = pd.Series(y).groupby(c_tr).mean()
    alpha[k] = [float(s.get(i, 0.0)) for i in range(45)]
ic_tr = {k: E.sic(np.take(alpha[k], c_tr), (tr["mid"][idx + k] - tr["mid"][idx]) / tr["mid"][idx] * 1e4) for k in TAUS}
KBEST = max(TAUS, key=lambda k: ic_tr[k])
print("10-13(估表的那天)各时长的 IC:" + "  ".join("%d毫秒 %+.3f" % (k * 10, ic_tr[k]) for k in TAUS) + " → 用 %d 毫秒" % (KBEST * 10))

# 样本外检查(10-14)
te = state("20261014")
mt = te["ok"] & np.isfinite(te["obi"]) & np.isfinite(te["bnA"]) & np.isfinite(te["bnB"])
it = np.flatnonzero(mt)
it = it[it < te["n"] - 520]
c_te = cell(te, it, ed)
print("α 表(10-13 估)在 10-14 上的样本外检查(每 10 毫秒一个时刻)")
for k in TAUS:
    y = (te["mid"][it + k] - te["mid"][it]) / te["mid"][it] * 1e4
    pred = np.take(alpha[k], c_te)
    ic = E.sic(pred, y)
    q = pd.qcut(pd.Series(pred).rank(method="first"), 10, labels=False)
    g = pd.Series(y).groupby(q.values).mean()
    print("  τ = %3d 毫秒:秩 IC %+.3f;预测最低 10%% 实际 %+.3f bp,最高 10%% 实际 %+.3f bp" % (k * 10, ic, g.iloc[0], g.iloc[-1]))

# M 表:10-14 15–17 时,真实挂在本侧最优价的单被打到之后的 markout
rows = []
for hh in (15, 16, 17):
    p = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt", "20261014", "%02d_XBTUSDTM_l3.jsonl.gz" % hh)
    orders = {}
    with gzip.open(p, "rb") as fh:
        try:
            for ln in fh:
                d = orjson.loads(ln[ln.index(b"\t") + 1:])
                s, dd = d.get("subject"), d.get("data") or {}
                if s == "open":
                    t = int(dd["ts"])
                    r = (t - te["t0"] - 1) // E.STEP
                    if 0 <= r < te["n"] and te["ok"][r]:
                        tk = round(float(dd["price"]) / 0.1)
                        sd = 0 if dd["side"] == "buy" else 1
                        at_touch = (tk == te["bp"][r]) if sd == 0 else (tk == te["ap"][r])
                        if at_touch:
                            orders[dd["orderId"]] = (sd, tk, t)
                elif s == "match":
                    o = orders.get(dd["makerOrderId"])
                    if o is not None:
                        t = int(dd["ts"])
                        if t - o[2] >= 5_000_000:
                            rows.append((t, o[0], o[1], float(dd["size"])))
                elif s == "done":
                    orders.pop(dd["orderId"], None)
        except (EOFError, OSError):
            pass
    print("  L3 %d 时读完,累计贴最优价被打到的成交 %d 笔" % (hh, len(rows)), flush=True)
F = pd.DataFrame(rows, columns=["ts", "sd", "tk", "sz"])
r = ((F["ts"].to_numpy() - te["t0"] - 1) // E.STEP).astype(np.int64)
keep = (r >= 0) & (r < te["n"] - 520) & mt[np.clip(r, 0, te["n"] - 1)]
F, r = F[keep].reset_index(drop=True), r[keep]
F["cell"] = cell(te, r, ed)
px = F["tk"].to_numpy() * 0.1
sg = np.where(F["sd"] == 0, 1.0, -1.0)
w = F["sz"].to_numpy() * 0.001 * px
M, E_ = {}, {}
for k in TAUS:
    mo = sg * (te["mid"][r + 1 + k] - px) / px * 1e4             # 成交所在格之后 τ
    M[k] = {}
    for sd, nm in ((0, "bid"), (1, "ask")):
        sel = F["sd"].to_numpy() == sd
        tot = float(np.average(mo[sel], weights=w[sel]))
        vals, cnt = [], []
        for i in range(45):
            ss = sel & (F["cell"].to_numpy() == i)
            cnt.append(int(ss.sum()))
            vals.append(float(np.average(mo[ss], weights=w[ss])) if ss.sum() >= 30 else tot)
        M[k][nm] = vals
        M[k][nm + "_n"] = cnt
        M[k][nm + "_all"] = tot
    print("  τ = %3d 毫秒:贴最优价成交的 markout 全部平均 买单 %+.3f 卖单 %+.3f bp;e = 0.7 + M > 0 的格:买 %d / 45,卖 %d / 45" % (
        k * 10, M[k]["bid_all"], M[k]["ask_all"], sum(v + RHO > 0 for v in M[k]["bid"]), sum(v + RHO > 0 for v in M[k]["ask"])))
k = KBEST
e_bid = [RHO + v for v in M[k]["bid"]]
e_ask = [RHO + v for v in M[k]["ask"]]
out = dict(edges=ed, alpha_bp={str(kk * 10): alpha[kk] for kk in TAUS}, M_bp={str(kk * 10): M[kk] for kk in TAUS},
           e_bid=e_bid, e_ask=e_ask, horizon_ms=KBEST * 10, rho=RHO, n_fills=len(F))
json.dump(out, open(os.path.join(ROOT, "data", "research7", "alpha_quote_table_20261016.json"), "w"), indent=1)
print("贴最优价被打到的成交共 %d 笔;写入 data/research7/alpha_quote_table_20261016.json" % len(F))
