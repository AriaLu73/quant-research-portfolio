#!/usr/bin/env python3
"""research3 流量解剖(事件 parquet 口径,购买数据):一个合约的吃单流里,多少是"盘口内新单被等量秒吃"的成对打印、多少是真实吃单;
真实吃单打到显示盘口时,**真实挂单方**(不需要任何排队假设)在 1/5/30/300 s 的每万 U 毛收益;按点差(tick)与盘口失衡分桶。
分类(吃单 = 同毫秒同向成交;成交前最后一帧盘口,严格早于成交时间戳):
  at = 首档价等于显示最优价;in = 比显示最优价好(显示之外的新单被吃);beyond = 比显示最优价差。
  pair = in,或 at 且该侧最优价 ≤ 10 ms 前向内改善且吃单量 = 显示量。real = 其余 at/beyond。
用法:python scripts/research3/flow_anatomy.py XAUTUSDTM,PAXGUSDTM [days]"""
import glob, json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EV = os.path.join(ROOT, "data", "research2", "events")
SPECS = json.load(open(os.path.join(ROOT, "data", "research2", "kc_contract_specs.json")))
CLIP = 1000.0; HS = [1, 5, 30, 300]


def load(sym, day):
    b = pd.read_parquet(os.path.join(EV, f"book_{sym}_{day}.parquet")); t = pd.read_parquet(os.path.join(EV, f"trades_{sym}_{day}.parquet"))
    tick = float(SPECS[sym]["tick"])
    return b, t, tick


def load_tardis(tag, day):
    """tardis_kualt / kualt2 的 quotes+trades(7 个月首日)→ 与事件 parquet 相同的列(价 = 整数 tick,量 = 币)。"""
    sym = tag[3:].upper() + "USDTM"; tick, mult = float(SPECS[sym]["tick"]), float(SPECS[sym]["mult"])
    d = next(x for x in (os.path.join(ROOT, "data", "tardis_kualt"), os.path.join(ROOT, "data", "tardis_kualt2")) if os.path.exists(os.path.join(x, f"quotes-{tag}-{day}.csv.gz")))
    q = pd.read_csv(os.path.join(d, f"quotes-{tag}-{day}.csv.gz"), usecols=["timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"])
    q = q[(q.bid_price > 0) & (q.ask_price > q.bid_price)]
    b = pd.DataFrame(dict(ts=q.timestamp.values, bb=np.rint(q.bid_price.values / tick).astype(np.int64), ba=np.rint(q.ask_price.values / tick).astype(np.int64),
                          bq1=q.bid_amount.values * mult, aq1=q.ask_amount.values * mult))
    t = pd.read_csv(os.path.join(d, f"trades-{tag}-{day}.csv.gz"), usecols=["timestamp", "side", "price", "amount"])
    t = pd.DataFrame(dict(ts=t.timestamp.values, sgn=np.where(t.side == "buy", 1, -1), px=np.rint(t.price.values / tick).astype(np.int64), qty=t.amount.values * mult))
    return b, t, tick, sym


def anatomy(sym, day, tardis=False):
    if tardis:
        b, t, tick, sym = load_tardis(sym, day)
    else:
        b, t, tick = load(sym, day)
    qts = b.ts.values.astype(np.int64); bb, ba = b.bb.values.astype(np.int64), b.ba.values.astype(np.int64); bq, aq = b.bq1.values, b.aq1.values
    mid = (bb + ba) / 2.0
    t = t.assign(usd=t.px * tick * t.qty)
    g = t.groupby(["ts", "sgn"]).agg(pmin=("px", "min"), pmax=("px", "max"), usd=("usd", "sum"), qty=("qty", "sum"), n=("px", "size")).reset_index()
    ts = g.ts.values.astype(np.int64); sg = g.sgn.values.astype(int)
    i0 = np.searchsorted(qts, ts, side="left") - 1; ok = i0 >= 0; g, ts, sg, i0 = g[ok].reset_index(drop=True), ts[ok], sg[ok], i0[ok]
    fpx = np.where(sg > 0, g.pmin.values, g.pmax.values); lpx = np.where(sg > 0, g.pmax.values, g.pmin.values)
    touch = np.where(sg > 0, ba[i0], bb[i0]); tsz = np.where(sg > 0, aq[i0], bq[i0]); osz = np.where(sg > 0, bq[i0], aq[i0])
    spr = ba[i0] - bb[i0]
    da = np.r_[0, np.diff(ba)]; db = np.r_[0, np.diff(bb)]
    la = np.maximum.accumulate(np.where(da != 0, np.arange(len(qts)), 0)); lb = np.maximum.accumulate(np.where(db != 0, np.arange(len(qts)), 0))
    j = np.where(sg > 0, la[i0], lb[i0]); age = (ts - qts[j]) / 1000.0
    imp = np.where(sg > 0, da[j] < 0, db[j] > 0)
    k = sg * (fpx - touch)
    cat = np.select([k == 0, k < 0], ["at", "in"], "beyond")
    pair = (k < 0) | ((k == 0) & (age <= 10) & imp & (np.abs(g.qty.values - tsz) <= 1e-6 * np.maximum(1, tsz)))
    imb = (tsz - osz) / (tsz + osz + 1e-12)
    out = pd.DataFrame(dict(sym=sym, day=day, ts=ts, sg=sg, cat=cat, pair=pair, usd=g.usd.values, f=np.minimum(CLIP, g.usd.values), spr=spr, age=age,
                            imb=imb, sweep=sg * (lpx - fpx), thru=g.qty.values >= tsz * (1 - 1e-6), half_bp=spr / 2 / mid[i0] * 1e4, tick_bp=1 / mid[i0] * 1e4))
    for h in HS:
        mh = mid[np.clip(np.searchsorted(qts, ts + h * 1_000_000, side="right") - 1, 0, len(qts) - 1)]
        out[f"e{h}"] = sg * (touch - mh) / touch * 1e4          # 真实挂单方(在显示最优价成交)的毛收益 bp:卖在 touch,之后中价 mh
        out[f"v{h}"] = ts + h * 1_000_000 <= qts[-1]
    out["hours"] = (qts[-1] - qts[0]) / 3.6e9
    out["px"] = touch * tick; out["mid0"] = mid[i0] * tick; out["mid_end"] = mid[-1] * tick
    return out


def main():
    syms = sys.argv[1].split(",")
    days = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    rows = []
    for s in syms:
        ds = days or sorted(os.path.basename(p).split("_")[-1][:8] for p in glob.glob(os.path.join(EV, f"book_{s}_*.parquet")))
        for d in ds:
            if os.path.exists(os.path.join(EV, f"trades_{s}_{d}.parquet")):
                rows.append(anatomy(s, d))
    G = pd.concat(rows); G.to_parquet(os.path.join(ROOT, "data", "research3", f"flow_anatomy_{'_'.join(x[:4] for x in syms)}.parquet"))
    pd.set_option("display.width", 250)
    def wavg(x, col):
        return float((x[col] * x.f).sum() / x.f.sum()) if x.f.sum() else np.nan
    print("== 每合约概览 ==")
    o = []
    for s, X in G.groupby("sym"):
        nd = X.day.nunique(); real = X[~X.pair & (X.cat != "in")]; at = real[real.cat == "at"]
        o.append(dict(sym=s, days=nd, taker_usd_day=X.usd.sum() / nd, orders_day=len(X) / nd, pair_share=X.usd[X.pair].sum() / X.usd.sum(), real_usd_day=real.usd.sum() / nd,
                      spr_ticks_med=float(X.spr.median()), tick_bp=float(X.tick_bp.median()), half_bp=float(X.half_bp.median()),
                      at_e1=wavg(at, "e1"), at_e5=wavg(at, "e5"), at_e30=wavg(at[at.v30], "e30"), at_e300=wavg(at[at.v300], "e300"), beyond_share=real.usd[real.cat == "beyond"].sum() / max(1e-9, real.usd.sum()),
                      thru_share=at.usd[at.thru].sum() / max(1e-9, at.usd.sum())))
    print(pd.DataFrame(o).round(3).to_string(index=False))
    print("\n== 真实吃单打到显示最优价(at, 非成对):挂单方毛收益 bp(clip $1k 加权;我方费率 返佣后为净)按 点差 tick 桶 ==")
    R_ = G[~G.pair & (G.cat == "at")].copy()
    R_["sprb"] = np.select([R_.spr <= 1, R_.spr == 2, R_.spr <= 4, R_.spr <= 9], ["1", "2", "3-4", "5-9"], "10+")
    R_["imbb"] = np.select([R_.imb <= -0.33, R_.imb >= 0.33], ["opp_big", "same_big"], "flat")
    R_["thr"] = np.where(R_.thru, "thru", "partial")
    def tab(keys):
        a = R_.groupby(keys).apply(lambda x: pd.Series(dict(n=len(x), f_usd=x.f.sum(), half_bp=wavg(x, "half_bp"), e1=wavg(x, "e1"), e5=wavg(x, "e5"), e30=wavg(x[x.v30], "e30"), e300=wavg(x[x.v300], "e300"))), include_groups=False)
        return a.round(2)
    print(tab(["sym", "sprb"]).to_string())
    print("\n== 同上,按 我方侧盘口量相对对侧(imb)==")
    print(tab(["sym", "imbb"]).to_string())
    print("\n== 同上,按 是否打穿该档(thru = 吃单量 ≥ 显示量)==")
    print(tab(["sym", "thr"]).to_string())


if __name__ == "__main__":
    main()
