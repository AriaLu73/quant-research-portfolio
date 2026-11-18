#!/usr/bin/env python3
"""MIDCAP-6 假设 H-W(成对打印拦截)的离线实验(流程阶段 5):
现象:宽点差山寨永续上约 8 成吃单额是"盘口内刚挂出一张单 → 1–10 ms 内被等量吃掉"的成对打印。
规则(事先写定):每当某侧最优价向内改善(出现新单,价 P),我方在同侧挂 P 再向内 1 tick 的单,
  行情+下单延迟 L ms 后生效,存活 H ms,成交一次即撤;只有当我方价比事件前中价好出 ≥ phi × 事件前半点差时才挂(phi 无量纲)。
  成交:存活期内到达、打向该侧、且首档成交价不优于我方价的吃单,成交 min(clip, 吃单总额)。时间戳为毫秒,要求吃单 ts ≥ t0 + L + 1。
输出:每 (合约, 日, L, phi):挂单次数、成交笔数/额、成对特征占比、相对 1/5/30 s 后中价的每万 U 收益、带库存上限的回合净利(含返佣 我方费率)。
乐观假设(必须实盘验证):对手的吃单腿是限价/市价单、不看盘口,会先吃到价更优的我方;别的抢一档机器人不在同一毫秒抢在我们前面。"""
import argparse, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import touch_mm_replay as R

H_MS = float(os.environ.get('PI_H_MS', '20'))                       # 我方单存活时间(ms)
FR_MAX = float(os.environ.get('PI_FR', '1'))                        # 只跟"新单量在过去 2000 个改善事件里出现频率 < FR_MAX"的事件(1 = 全跟)


def rolling_freq(ez, n=2000):
    from collections import Counter, deque
    win = deque(); cnt = Counter(); fr = np.zeros(len(ez))
    for i, z in enumerate(ez):
        fr[i] = cnt[z] / max(1, len(win))
        win.append(z); cnt[z] += 1
        if len(win) > n:
            cnt[win.popleft()] -= 1
    return fr
CAP = float(os.environ.get('PI_CAP_USD', '3000')) / R.CLIP      # 库存上限(美元,环境变量 PI_CAP_USD)换算成 clip 数


EV = os.path.join(R.ROOT, "data", "research2", "events")
ALIAS = {"XBTUSDTM": "BTC_B", "XRPUSDTM": "XRP_B"}          # 9 月购买数据里早先按旧标签抽好的事件文件


def has_data(tag, day):
    if tag.startswith("ku_"):
        return bool(R.find(tag, day))
    return os.path.exists(os.path.join(EV, f"book_{ALIAS.get(tag, tag)}_{day}.parquet"))


def load_qt(tag, day):
    """tardis 月首日(标签 ku_xxx)或 9 月购买数据的事件 parquet(原生合约名)→ 同一套列:报价(价、张数)与成交(价、张数)。"""
    if tag.startswith("ku_"):
        d = R.find(tag, day); sym = tag[3:].upper() + "USDTM"; mult = float(R.SPECS[sym]["mult"]); tick = float(R.SPECS[sym]["tick"])
        q = pd.read_csv(os.path.join(d, f"quotes-{tag}-{day}.csv.gz"), usecols=["timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"])
        q = q[(q.bid_price > 0) & (q.ask_price > q.bid_price)]
        t = pd.read_csv(os.path.join(d, f"trades-{tag}-{day}.csv.gz"), usecols=["timestamp", "side", "price", "amount"])
        return q, t, tick, mult, sym
    sym = tag; mult = float(R.SPECS[sym]["mult"]); tick = float(R.SPECS[sym]["tick"]); a = ALIAS.get(tag, tag)
    b = pd.read_parquet(os.path.join(EV, f"book_{a}_{day}.parquet"), columns=["ts", "bb", "ba", "bq1", "aq1"]); tr = pd.read_parquet(os.path.join(EV, f"trades_{a}_{day}.parquet"))
    q = pd.DataFrame(dict(timestamp=b.ts.values, ask_amount=np.rint(b.aq1.values.astype(np.float64) / mult), ask_price=b.ba.values * tick, bid_price=b.bb.values * tick,
                          bid_amount=np.rint(b.bq1.values.astype(np.float64) / mult)))
    t = pd.DataFrame(dict(timestamp=tr.ts.values, side=np.where(tr.sgn.values > 0, "buy", "sell"), price=tr.px.values * tick, amount=np.rint(tr.qty.values.astype(np.float64) / mult)))
    return q, t, tick, mult, sym


def sim(args):
    try:
        return _sim(args)
    except Exception as e:  # noqa: BLE001
        return dict(tag=args[0], day=args[1], L=args[2], phi=args[3], error=repr(e)[:120])


def _sim(args):
    tag, day, L, phi = args
    q, t, tick, mult, sym = load_qt(tag, day)
    t["usd"] = t.price * t.amount * mult; t["sg"] = np.where(t.side == "buy", 1, -1)
    g = t.groupby(["timestamp", "sg"]).agg(pmin=("price", "min"), pmax=("price", "max"), usd=("usd", "sum"), qty=("amount", "sum")).reset_index()
    qts = q.timestamp.values.astype(np.int64); ap, bp = q.ask_price.values, q.bid_price.values; aq, bq = q.ask_amount.values, q.bid_amount.values
    mid = (ap + bp) / 2
    fills = []
    n_orders = 0
    for dside in (+1, -1):                       # +1: 我方买(bid 侧事件,拦截吃单卖);-1: 我方卖
        px = bp if dside > 0 else ap; sz = bq if dside > 0 else aq
        ev = np.where(np.r_[False, (np.diff(px) * dside) > 0])[0]
        F = mid[ev - 1]; half = (ap[ev - 1] - bp[ev - 1]) / 2
        ours = px[ev] + dside * tick
        opp = ap[ev] if dside > 0 else bp[ev]
        okv = (dside * (F - ours) >= phi * half) & (dside * (opp - ours) > tick * 0.5)
        if FR_MAX < 1:
            okv &= rolling_freq(sz[ev]) < FR_MAX
        ev, F, ours, half = ev[okv], F[okv], ours[okv], half[okv]
        n_orders += len(ev)
        et = qts[ev]; ep = px[ev]; ez = sz[ev]
        tk = g[g.sg == -dside]
        ts = tk.timestamp.values.astype(np.int64); fpx = (tk.pmax.values if dside > 0 else tk.pmin.values)
        j = np.searchsorted(et, ts - (L + 1) * 1000, side="right") - 1
        ok = (j >= 0); jj = np.where(ok, j, 0)
        ok &= (ts - et[jj]) <= (L + H_MS) * 1000
        ok &= dside * (ours[jj] - fpx) >= -tick * 0.5        # 吃单首档价不优于我方价 → 先吃我方
        k = np.where(ok)[0]
        _, first = np.unique(jj[k], return_index=True); k = k[first]     # 每个事件只成交一次
        e = jj[k]
        fills.append(pd.DataFrame(dict(ts=ts[k], d=dside, px=ours[e], usd=np.minimum(R.CLIP, tk.usd.values[k]), F=F[e], half=half[e],
                                       pair=(np.abs(fpx[k] - ep[e]) < tick * 0.5) & (tk.qty.values[k] == ez[e]), gap_ms=(ts[k] - et[e]) / 1000.0)))
    f = pd.concat(fills).sort_values("ts").reset_index(drop=True)
    hrs = (qts[-1] - qts[0]) / 3.6e9
    out = dict(tag=tag, sym=sym, day=day, L=L, phi=phi, cap_usd=CAP * R.CLIP, h_ms=H_MS, fr=FR_MAX, orders=n_orders, orders_per_s=n_orders / (hrs * 3600), fills=len(f), spr_ticks=float(np.median(np.rint((ap - bp) / tick))),
               tick_bp=float(tick / np.median(mid) * 1e4))
    if not len(f):
        return out
    def fut(h):
        return mid[np.clip(np.searchsorted(qts, f.ts.values + int(h * 1e6), side="right") - 1, 0, len(qts) - 1)]
    for h in (1, 5, 30):
        f[f"e{h}"] = f.d * (fut(h) - f.px) / f.px * f.usd
    f["eF"] = f.d * (f.F - f.px) / f.px * f.usd
    # 回合结算:库存上限 CAP clip,越限该侧不成交;期末按中价
    pos = cash = vol = 0.0; nf = 0
    for d_, p_, u_ in zip(f.d.values, f.px.values, f.usd.values):
        if d_ > 0 and pos * p_ >= CAP * R.CLIP - 1e-9:
            continue
        if d_ < 0 and pos * p_ <= -CAP * R.CLIP + 1e-9:
            continue
        qy = u_ / p_; pos += d_ * qy; cash -= d_ * u_; vol += u_; nf += 1
    leg = cash + pos * mid[-1]
    out.update(fill_usd=float(f.usd.sum()), pair_share=float(f.usd[f.pair].sum() / f.usd.sum()), gap_med=float(f.gap_ms.median()),
               eF_bp=float(f.eF.sum() / f.usd.sum() * 1e4), e1_bp=float(f.e1.sum() / f.usd.sum() * 1e4), e5_bp=float(f.e5.sum() / f.usd.sum() * 1e4),
               e30_bp=float(f.e30.sum() / f.usd.sum() * 1e4), e5_pair_bp=float(f.e5[f.pair].sum() / max(1e-9, f.usd[f.pair].sum()) * 1e4),
               e5_nonpair_bp=float(f.e5[~f.pair].sum() / max(1e-9, f.usd[~f.pair].sum()) * 1e4),
               rt_fills=nf, rt_vol=vol, rt_leg=leg, rt_net=leg + vol * R.REB, end_pos_usd=pos * mid[-1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms", required=True); ap.add_argument("--days", default="20260601,20260701,20260801,20260901")
    ap.add_argument("--L", default="2,3,4,6,10"); ap.add_argument("--phi", default="0,0.5"); ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--tag", default="")
    ns = ap.parse_args()
    jobs = [(s, d, float(l), float(p)) for s in ns.syms.split(",") for d in ns.days.split(",") for l in ns.L.split(",") for p in ns.phi.split(",") if has_data(s, d)]
    part = os.path.join(R.ROOT, "data", "research3", f"pair_intercept{ns.tag}.jsonl")
    rows = []
    if os.path.exists(part):
        rows = [json.loads(l) for l in open(part, encoding="utf-8")]
        done = {(r.get("tag"), str(r["day"]), float(r["L"]), float(r["phi"])) for r in rows}
        jobs = [j for j in jobs if (j[0], j[1], j[2], j[3]) not in done]
    print(len(jobs), "to run", flush=True)
    with ProcessPoolExecutor(ns.workers) as ex, open(part, "a", encoding="utf-8") as fh:
        for r in ex.map(sim, jobs):
            fh.write(json.dumps({k: (v.item() if hasattr(v, "item") else v) for k, v in r.items()}) + "\n"); fh.flush(); rows.append(r)
    D = pd.DataFrame(rows); D.to_csv(part.replace(".jsonl", ".csv"), index=False)
    if "error" in D:
        D = D[D.error.isna()]
    D = D[D.fills > 0]
    pd.set_option("display.width", 250)
    a = D.groupby(["sym", "phi", "L"]).agg(days=("day", "size"), ord_s=("orders_per_s", "mean"), fills=("fills", "sum"), fill_usd=("fill_usd", "sum"), pair=("pair_share", "mean"),
                                           eF=("eF_bp", "mean"), e1=("e1_bp", "mean"), e5=("e5_bp", "mean"), e30=("e30_bp", "mean"), e5_pair=("e5_pair_bp", "mean"),
                                           e5_non=("e5_nonpair_bp", "mean"), rt_vol=("rt_vol", "sum"), rt_net=("rt_net", "sum"), pos_days=("rt_net", lambda x: int((x > 0).sum())))
    print(a.round(2).to_string())


if __name__ == "__main__":
    main()
