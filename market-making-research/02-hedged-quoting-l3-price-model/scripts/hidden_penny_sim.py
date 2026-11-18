#!/usr/bin/env python3
"""MIDCAP-8 假设 H-H(隐藏单拦截成对打印)的事件级回放(流程阶段 5/6):
机制:KuCoin 合约支持隐藏单(hidden=true,不显示在盘口;按 **taker 费率** 收费,无返佣)。成对打印机器人看不到隐藏单,
  仍会把自己的挂单放在"显示最优价内 1 tick"再用吃单腿去吃;若我方隐藏单价更优(显示最优价内 k tick,k ≥ 2),按价格优先,它的吃单腿先成交我方。
规则(事先写定):
  - 每侧一张隐藏单,价 = 显示最优价(L ms 前的行情)向内 k tick;每 R ms 才允许改价一次(R = 0 表示每次行情变动都跟);点差不足 2k+1 tick 时该侧不挂。
  - 成交:吃单首档成交价比我方价**至少差 1 tick**(对吃单方更差)→ 按价格优先先成交我方,成交价 = 我方价,额 = min(clip, 吃单总额)。
    同侧两次成交间隔 ≥ L(重挂时间)。库存上限 ±cap clip。
  - 费用:每笔成交付 taker 费 我方费率(隐藏单)。结算:现金 + 期末库存按期末中价。
乐观假设(只能实盘验证):对手吃单腿不看盘口/不带"只吃自己"的限制;隐藏单在更优价上确实先成交;对手不因被拦截而改变行为。"""
import argparse, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import touch_mm_replay as R_

FEE = OUR_FEE


def sim(a):
    tag, day, k, L, Rms, cap = a[:6]; pshare = a[6] if len(a) > 6 else None
    try:
        q, o, tick, sym = R_.load(tag, day)
    except Exception as e:  # noqa: BLE001
        return dict(tag=tag, day=day, k=k, L=L, R=Rms, error=repr(e)[:120])
    mult = float(R_.SPECS[sym]["mult"])
    qts = q.timestamp.values.astype(np.int64); bp, ap = q.bid_price.values, q.ask_price.values; mid = (bp + ap) / 2
    ts = o.timestamp.values.astype(np.int64); sg = o.sg.values; fpx = o.price.values; tot = o.tot.values
    tref = ts if Rms <= 0 else (ts // int(Rms * 1000)) * int(Rms * 1000)          # 上一次允许改价的时刻
    iq = np.searchsorted(qts, tref - int(L * 1000), side="left") - 1
    ok = iq >= 0; ts, sg, fpx, tot, iq = ts[ok], sg[ok], fpx[ok], tot[ok], iq[ok]
    spr = np.rint((ap[iq] - bp[iq]) / tick)
    touch = np.where(sg > 0, ap[iq], bp[iq]); ours = touch - sg * k * tick
    quoted = spr >= 2 * k + 1
    if pshare is not None:      # EV 门槛(模型推导,非拟合):成对占比 p 的吃单几乎不动价(b≈0.15 个半点差),真实吃单推 1.8 个半点差
        half_bp = (ap[iq] - bp[iq]) / 2 / mid[iq] * 1e4; tick_bp = tick / mid[iq] * 1e4
        ev = half_bp * (1 - 0.15 * pshare - 1.8 * (1 - pshare)) - k * tick_bp - FEE * 1e4
        quoted &= ev >= 0
    hit = quoted & (sg * (fpx - ours) >= tick * 0.5)
    i0 = np.searchsorted(qts, ts, side="left") - 1; m0 = mid[np.clip(i0, 0, len(qts) - 1)]
    m5 = mid[np.clip(np.searchsorted(qts, ts + 5_000_000, side="right") - 1, 0, len(qts) - 1)]
    cash = pos = vol = 0.0; n = 0; a_spread = a_adv = 0.0; last = {1: -10**18, -1: -10**18}; peak = 0.0
    for j in np.where(hit)[0]:
        d = -sg[j]                                   # 我方方向:吃单买 → 我方卖
        if ts[j] - last[d] < L * 1000:
            continue
        pu = pos * m0[j]
        if (d > 0 and pu >= cap * R_.CLIP - 1e-9) or (d < 0 and pu <= -cap * R_.CLIP + 1e-9):
            continue
        f = min(R_.CLIP, tot[j]); qy = f / ours[j]
        pos += d * qy; cash -= d * f; vol += f; n += 1; last[d] = ts[j]
        a_spread += d * (m0[j] - ours[j]) * qy; a_adv += d * (m5[j] - m0[j]) * qy
        peak = max(peak, abs(pos) * m0[j])
    leg = cash + pos * mid[-1]
    return dict(tag=tag, sym=sym, day=day, k=k, L=L, R=Rms, cap=cap, fills=n, vol=vol, leg=leg, fee=vol * FEE, net=leg - vol * FEE, net_maker=leg + vol * 0.7e-4,
                attr_spread=a_spread, attr_adv5=a_adv, attr_hold=leg - a_spread - a_adv, end_pos=pos * mid[-1], peak=peak,
                taker_usd=float(o.tot.sum()), spr_med=float(np.median(np.rint((ap - bp) / tick))), tick_bp=float(tick / np.median(mid) * 1e4))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--syms", required=True); p.add_argument("--days", default="20251001,20260101,20260401,20260601,20260701,20260801,20260901")
    p.add_argument("--k", default="2"); p.add_argument("--L", default="3"); p.add_argument("--R", default="0,200,1000"); p.add_argument("--cap", type=float, default=3)
    p.add_argument("--workers", type=int, default=5); p.add_argument("--tag", default=""); p.add_argument("--ev", type=int, default=0)
    ns = p.parse_args()
    jobs = [(s, d, int(k), float(l), float(r), ns.cap) for s in ns.syms.split(",") for d in ns.days.split(",") for k in ns.k.split(",") for l in ns.L.split(",") for r in ns.R.split(",") if R_.find(s, d)]
    if ns.ev:                   # 用前一个可用日的成对占比(事前量)做 EV 门槛;没有前一日的跳过
        A = pd.read_csv(os.path.join(R_.ROOT, "data", "research3", "flow_anatomy_alts.csv")); A = A[A.error.isna()] if "error" in A else A
        A["day"] = A.day.astype(int).astype(str); prev = {}
        for tg, X in A.groupby("tag"):
            X = X.sort_values("day"); ds = X.day.tolist(); ps = X.pair_share.tolist()
            for i in range(1, len(ds)):
                prev[(tg, ds[i])] = ps[i - 1]
        jobs = [j + (prev[(j[0], j[1])],) for j in jobs if (j[0], j[1]) in prev]
    part = os.path.join(R_.ROOT, "data", "research3", f"hidden_penny{ns.tag}.jsonl")
    done = set()
    if os.path.exists(part):
        done = {(r["tag"], str(r["day"]), r["k"], r["L"], r["R"]) for r in map(json.loads, open(part, encoding="utf-8"))}
    todo = [j for j in jobs if (j[0], j[1], j[2], j[3], j[4]) not in done]
    print(len(jobs), "jobs", len(todo), "todo", flush=True)
    with ProcessPoolExecutor(ns.workers) as ex, open(part, "a", encoding="utf-8") as fh:
        for r in ex.map(sim, todo):
            fh.write(json.dumps({k: (v.item() if hasattr(v, "item") else v) for k, v in r.items()}) + "\n"); fh.flush()
    D = pd.DataFrame([json.loads(l) for l in open(part, encoding="utf-8")]); D.to_csv(part.replace(".jsonl", ".csv"), index=False)
    if "error" in D:
        D = D[D.error.isna()]
    pd.set_option("display.width", 250)
    g = D.groupby(["sym", "k", "R"]).agg(days=("day", "size"), net=("net", "sum"), pos_days=("net", lambda x: int((x > 0).sum())), worst=("net", "min"), vol_day=("vol", "mean"),
                                           spread=("attr_spread", "sum"), adv5=("attr_adv5", "sum"), hold=("attr_hold", "sum"), fee=("fee", "sum"), part=("vol", "sum"), tk=("taker_usd", "sum"))
    g["net_bp"] = g.net / (g.vol_day * g.days) * 1e4; g["part"] = g.part / g.tk
    print(g.drop(columns="tk").round(2).to_string())
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
