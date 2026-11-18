#!/usr/bin/env python3
"""MIDCAP-1 离线实验(2026-10-01;流程阶段 5):KuCoin 山寨永续上"贴盘口、排队首"做市的成交条件收益。
依据:Albers et al. 2025(2502.18625,币安 BTC 永续队首/队尾 markout)、Moallemi-Yuan 2017(队首价值)、Gould-Bonart 2016(大 tick 失衡)、
DeLise 2024 / Lalor-Swishchuk 2024(穿价成交必须计入);用户 2026-10-01 裁决:实测延迟下按队首口径。
假设 H-A:在相对 tick 大(≥1 bp)、点差多为 1–2 tick 的合约上,排在队首的贴盘口挂单,在"本侧队长、对侧队短"等有利状态下,
  成交条件净收益 = 半点差 + 我方费率 返佣 − 成交后不利漂移 > 0。
数学定义:每张吃单(同 ts、同 side 的成交聚合为一张)打到被动侧盘口价 p;队首挂单必被首先成交,成交量 min(clip, 该档成交额)。
  edge_τ = s·(mid_{t+τ} − p)/p·1e4(s = +1 我方买入 / −1 我方卖出),net_τ = edge_τ + 0.7;edge_0 = 半点差(即时)。
  状态(成交前最后一帧盘口):I_same = (near − opp)/(near + opp)(near = 我方所在侧盘口量,美元);spread_ticks;near 相对当日中位;
  吃单额/near(≥1 = 打穿本档 → 穿价成交)。
数据:data/tardis_kualt(14 币,含 book)与 tardis_kualt2(60 币)quotes+trades,7 个月首日;合约规格 data/research2/kc_contract_specs.json。
输出:data/research3/touch_mm_scan.csv(合约×日×side×状态桶 汇总:笔数、可成交额、Σedge_τ·额、Σedge_0·额、穿价比例)。
用法:Python314/python.exe scripts/research3/touch_mm_scan.py --workers 4
"""
import argparse, glob, json, os, re
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPECS = json.load(open(os.path.join(ROOT, "data", "research2", "kc_contract_specs.json")))
SRC = [os.path.join(ROOT, "data", "tardis_kualt"), os.path.join(ROOT, "data", "tardis_kualt2")]
TAUS = {"e1": 1_000_000, "e5": 5_000_000, "e30": 30_000_000}
CLIP = 1000.0
REBATE = OUR_FEE


def native(tag):
    return tag[3:].upper() + "USDTM"


def one(args):
    d, tag, day = args
    sym = native(tag)
    sp = SPECS.get(sym)
    if not sp:
        return []
    tick, mult = float(sp["tick"]), float(sp["mult"])
    try:
        q = pd.read_csv(os.path.join(d, f"quotes-{tag}-{day}.csv.gz"), usecols=["timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"])
        t = pd.read_csv(os.path.join(d, f"trades-{tag}-{day}.csv.gz"), usecols=["timestamp", "side", "price", "amount"])
    except Exception as e:  # noqa: BLE001
        return [dict(sym=sym, day=day, error=str(e)[:80])]
    q = q[(q.bid_price > 0) & (q.ask_price > q.bid_price)]
    if len(q) < 1000 or len(t) < 50:
        return []
    qts = q.timestamp.values.astype(np.int64)
    bp, ap = q.bid_price.values, q.ask_price.values
    bq, aq = q.bid_amount.values * mult * bp, q.ask_amount.values * mult * ap      # 美元
    mid = (bp + ap) / 2
    spread_ticks = np.rint((ap - bp) / tick)
    # 吃单聚合
    t["usd"] = t.price * t.amount * mult
    t["sg"] = np.where(t.side == "buy", 1, -1)
    g = t.groupby(["timestamp", "sg"])
    agg = g.agg(usd=("usd", "sum"), pmin=("price", "min"), pmax=("price", "max"), n=("price", "size")).reset_index()
    # 首档成交额(该吃单在第一个价位成交的额):买单首档 = pmin 那一价位
    first_px = np.where(agg.sg > 0, agg.pmin, agg.pmax)
    t["px_key"] = t.price
    first_usd = t.groupby(["timestamp", "sg", "px_key"]).usd.sum().reset_index()
    fu = first_usd.merge(agg[["timestamp", "sg"]].assign(px_key=first_px), on=["timestamp", "sg", "px_key"], how="inner")
    agg = agg.merge(fu[["timestamp", "sg", "usd"]].rename(columns={"usd": "usd_first"}), on=["timestamp", "sg"], how="left")
    ts = agg.timestamp.values.astype(np.int64)
    i0 = np.searchsorted(qts, ts, side="left") - 1                     # 成交前最后一帧
    ok = i0 >= 0
    agg, ts, i0, first_px = agg[ok], ts[ok], i0[ok], first_px[ok]
    sg = agg.sg.values
    touch = np.where(sg > 0, ap[i0], bp[i0])
    at_touch = np.abs(first_px - touch) <= tick * 0.5                  # 首档就是当时盘口价(否则盘口已变,跳过)
    agg, ts, i0, first_px, sg = agg[at_touch], ts[at_touch], i0[at_touch], first_px[at_touch], sg[at_touch]
    if len(agg) == 0:
        return []
    near = np.where(sg > 0, aq[i0], bq[i0])                            # 我方所在侧(被动侧)盘口美元量
    opp = np.where(sg > 0, bq[i0], aq[i0])
    I_same = (near - opp) / (near + opp + 1e-9)
    spr = spread_ticks[i0]
    s = -sg                                                             # 我方成交方向:吃单买 → 我方卖
    p = first_px
    e0 = s * (mid[i0] - p) / p * 1e4                                    # 半点差(即时)
    fill_usd = np.minimum(agg.usd_first.fillna(agg.usd).values, CLIP)
    sweep = agg.usd_first.fillna(agg.usd).values >= near * 0.999        # 首档被吃空(穿价)
    near_med = float(np.median(near)) if len(near) else 1.0
    rows = []
    edges = {}
    for k, tau in TAUS.items():
        j = np.searchsorted(qts, ts + tau, side="right") - 1
        edges[k] = s * (mid[j] - p) / p * 1e4
    df = pd.DataFrame(dict(side=np.where(s > 0, "buy", "sell"), imb=np.select([I_same <= -0.33, I_same >= 0.33], ["opp_big", "same_big"], "flat"),
                           spr=np.select([spr <= 1, spr == 2], ["1", "2"], "3+"), nearrel=np.select([near < 0.5 * near_med, near > 2 * near_med], ["thin", "thick"], "mid"),
                           sweep=sweep, fill=fill_usd, e0=e0 * fill_usd, **{k: v * fill_usd for k, v in edges.items()}))
    hours = (qts[-1] - qts[0]) / 3.6e12
    base = dict(sym=sym, day=day, tick_bp=float(tick / np.median(mid) * 1e4), spread_med_ticks=float(np.median(spread_ticks)),
                taker_usd=float(t.usd.sum()), hours=hours, near_med_usd=near_med)
    for keys, gg in df.groupby(["side", "imb", "spr", "nearrel"]):
        r = dict(base, side=keys[0], imb=keys[1], spr=keys[2], nearrel=keys[3], n=len(gg), fill_usd=float(gg.fill.sum()),
                 sweep_n=int(gg.sweep.sum()), e0=float(gg.e0.sum()), **{k: float(gg[k].sum()) for k in TAUS})
        rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--days", default="")
    ns = ap.parse_args()
    jobs = []
    for d in SRC:
        for f in glob.glob(os.path.join(d, "quotes-*.csv.gz")):
            m = re.match(r"quotes-(.+)-(\d{8})\.csv\.gz$", os.path.basename(f))
            if m and (not ns.days or m.group(2) in ns.days.split(",")):
                jobs.append((d, m.group(1), m.group(2)))
    print(len(jobs), "contract-days", flush=True)
    out = []
    with ProcessPoolExecutor(ns.workers) as ex:
        for k, rows in enumerate(ex.map(one, jobs)):
            out += rows
            if k % 20 == 0:
                print(k, len(out), flush=True)
    os.makedirs(os.path.join(ROOT, "data", "research3"), exist_ok=True)
    pd.DataFrame(out).to_csv(os.path.join(ROOT, "data", "research3", "touch_mm_scan.csv"), index=False)
    print("SCAN_DONE", len(out), flush=True)


if __name__ == "__main__":
    main()
