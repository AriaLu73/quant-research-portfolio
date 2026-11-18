#!/usr/bin/env python3
"""MIDCAP-2(流程阶段 6 的简化事件级回放,2026-10-01):贴盘口双边做市、队首口径,带库存与真实回合结算。
规则(全部事先写定,无自由参数拟合):
  - 两侧始终挂在当前盘口价(队首);clip $1,000;库存上限 ±cap clip(默认 3),越限一侧不挂。
  - 一张吃单打到我方所在侧盘口价 → 我方成交 min(clip, 该档成交额)(队首必先成交,含穿价)。
  - 状态门控(可选):只在训练日选出的 (side, imb, spr) 桶里挂该侧(桶定义同 touch_mm_scan.py)。
  - 结算:现金 + 期末库存按期末中价;返佣 我方费率 记入;另报不含返佣的价差腿。
  - 统计:日 PnL、成交额、笔数、|库存| 时间加权与峰值、库存翻转次数、买卖成交额差、每万 U 净收益。
数据:tardis_kualt / kualt2 quotes+trades(7 个月首日)。用法:Python314/python.exe scripts/research3/touch_mm_replay.py --syms ku_clo,ku_irys --cap 3
"""
import argparse, glob, json, os, re
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPECS = json.load(open(os.path.join(ROOT, "data", "research2", "kc_contract_specs.json")))
SRC = [os.path.join(ROOT, "data", "tardis_kualt"), os.path.join(ROOT, "data", "tardis_kualt2")]
CLIP, REB = float(os.environ.get("TMM_CLIP", "1000")), 0.7e-4      # clip 可由环境变量 TMM_CLIP 设(子进程继承)


def find(tag, day):
    for d in SRC:
        if os.path.exists(os.path.join(d, f"quotes-{tag}-{day}.csv.gz")):
            return d
    return None


def load(tag, day):
    d = find(tag, day)
    sym = tag[3:].upper() + "USDTM"
    sp = SPECS[sym]; tick, mult = float(sp["tick"]), float(sp["mult"])
    q = pd.read_csv(os.path.join(d, f"quotes-{tag}-{day}.csv.gz"), usecols=["timestamp", "ask_amount", "ask_price", "bid_price", "bid_amount"])
    t = pd.read_csv(os.path.join(d, f"trades-{tag}-{day}.csv.gz"), usecols=["timestamp", "side", "price", "amount"])
    q = q[(q.bid_price > 0) & (q.ask_price > q.bid_price)]
    t["usd"] = t.price * t.amount * mult; t["qty"] = t.amount * mult
    t["sg"] = np.where(t.side == "buy", 1, -1)
    g = t.groupby(["timestamp", "sg"]).price.agg(["min", "max"]).reset_index()
    g["fpx"] = np.where(g.sg > 0, g["min"], g["max"])
    lvl = t.groupby(["timestamp", "sg", "price"]).agg(usd=("usd", "sum"), qty=("qty", "sum")).reset_index()
    tot = t.groupby(["timestamp", "sg"]).usd.sum().reset_index().rename(columns={"usd": "tot"})   # 吃单全部价位总额
    fp = g[["timestamp", "sg", "fpx"]].merge(tot, on=["timestamp", "sg"])
    lvl = lvl.merge(fp, on=["timestamp", "sg"]); lvl = lvl[lvl.price == lvl.fpx]
    return q, lvl.sort_values("timestamp").reset_index(drop=True), tick, sym


def replay(tag, day, cap, gate=None, mode="touch", lat_ms=0.0):
    """lat_ms(阶段 8 延迟敏感性):① 我方成交后 lat_ms 内同侧不能再成交(重挂需要 行情+下单 时间);
    ② 盘口价在成交前 lat_ms 内刚变过则本次不成交(我方还没来得及移到新价位;保守:也不算被打到旧价)。"""
    """mode touch: 排在现有盘口价的队首(乐观:别人创造的价位我们也在最前)。
    mode penny: 点差 ≥ 3 tick 时我方自己报在盘口内一档(唯一、必在最前),吃单只要愿意付到该价即先成交我方(成交额 min(clip, 该吃单总额));
                点差 ≤ 2 tick 时退回 touch 口径。penny 的半点差比 touch 少 1 tick。"""
    q, o, tick, sym = load(tag, day)
    qts = q.timestamp.values.astype(np.int64); bp, ap = q.bid_price.values, q.ask_price.values
    bq, aq = q.bid_amount.values * bp, q.ask_amount.values * ap
    # mult already in? bid_amount is contracts; convert to USD with mult:
    mult = float(SPECS[sym]["mult"]); bq, aq = bq * mult, aq * mult
    spread_ticks = np.rint((ap - bp) / tick)
    ts = o.timestamp.values.astype(np.int64); i0 = np.searchsorted(qts, ts, side="left") - 1
    ok = i0 >= 0; o, ts, i0 = o[ok], ts[ok], i0[ok]
    sg = o.sg.values; px = o.price.values; usd = o.usd.values
    touch = np.where(sg > 0, ap[i0], bp[i0])
    if mode == "penny":
        wide = spread_ticks[i0] >= 3
        ours = np.where(wide, touch - sg * tick, touch)                 # 买方吃单 → 我方卖价 = ask − 1 tick
        hit = np.where(wide, np.where(sg > 0, px >= ours - tick * 0.5, px <= ours + tick * 0.5), np.abs(px - touch) <= tick * 0.5)
        px = np.where(wide, ours, px)
        usd = np.where(wide, o.tot.values, usd)                          # 我方在最前:吃单先把我方吃完(上限 clip)
    else:
        hit = np.abs(px - touch) <= tick * 0.5
    near = np.where(sg > 0, aq[i0], bq[i0]); opp = np.where(sg > 0, bq[i0], aq[i0])
    imb = np.select([(near - opp) / (near + opp + 1e-9) <= -0.33, (near - opp) / (near + opp + 1e-9) >= 0.33], ["opp_big", "same_big"], "flat")
    spr = np.select([spread_ticks[i0] <= 1, spread_ticks[i0] == 2], ["1", "2"], "3+")
    side = np.where(sg > 0, "sell", "buy")          # our fill side
    # 盘口价变动时刻(用于延迟规则 ②):该侧最优价上一次变化的时间
    if lat_ms > 0:
        chg_a = np.r_[True, np.diff(ap) != 0]; chg_b = np.r_[True, np.diff(bp) != 0]
        last_a = np.maximum.accumulate(np.where(chg_a, qts, qts[0])); last_b = np.maximum.accumulate(np.where(chg_b, qts, qts[0]))
        fresh = np.where(sg > 0, last_a[i0], last_b[i0])
        stale_ok = (ts - fresh) >= lat_ms * 1000
    else:
        stale_ok = np.ones(len(ts), dtype=bool)
    last_fill = {"buy": -10**18, "sell": -10**18}
    # 归因(教材第 27 章恒等式,中价基准):价差腿 = 价差捕获 + 逆向选择(5 s)+ 持有盈亏
    mid_q = (bp + ap) / 2
    mid5 = mid_q[np.clip(np.searchsorted(qts, ts + 5_000_000, side="right") - 1, 0, len(qts) - 1)]
    a_spread = a_adv = a_hold = 0.0
    cash = pos = 0.0; fills = 0; vol = 0.0; buy_usd = sell_usd = 0.0; rebate = 0.0
    last_t = ts[0] if len(ts) else qts[0]; abs_pos_time = 0.0; peak = 0.0; flips = 0; prev_sign = 0
    mid_ref = (bp[i0] + ap[i0]) / 2 if len(i0) else np.array([])
    for k in range(len(ts)):
        dt = (ts[k] - last_t) / 1e6; abs_pos_time += abs(pos) * mid_ref[k] * dt; last_t = ts[k]
        if not hit[k]:
            continue
        if gate is not None and (side[k], imb[k], spr[k]) not in gate:
            continue
        if lat_ms > 0 and (not stale_ok[k] or ts[k] - last_fill[side[k]] < lat_ms * 1000):
            continue
        pos_usd = pos * mid_ref[k]
        if side[k] == "buy" and pos_usd >= cap * CLIP - 1e-9:
            continue
        if side[k] == "sell" and pos_usd <= -cap * CLIP + 1e-9:
            continue
        f_usd = min(CLIP, usd[k]); qty = f_usd / px[k]
        if side[k] == "buy":
            pos += qty; cash -= f_usd; buy_usd += f_usd
        else:
            pos -= qty; cash += f_usd; sell_usd += f_usd
        rebate += f_usd * REB; vol += f_usd; fills += 1; last_fill[side[k]] = ts[k]
        sdir = 1.0 if side[k] == "buy" else -1.0
        a_spread += sdir * (mid_ref[k] - px[k]) * qty
        a_adv += sdir * (mid5[k] - mid_ref[k]) * qty
        a_hold += sdir * (mid_q[-1] - mid5[k]) * qty
        s = np.sign(pos)
        if s != 0 and prev_sign != 0 and s != prev_sign:
            flips += 1
        if s != 0:
            prev_sign = s
        peak = max(peak, abs(pos) * mid_ref[k])
    mid_end = (bp[-1] + ap[-1]) / 2
    spread_leg = cash + pos * mid_end
    hours = (qts[-1] - qts[0]) / 3.6e9
    return dict(sym=sym, day=day, hours=hours, fills=fills, vol=vol, buy_usd=buy_usd, sell_usd=sell_usd, spread_leg=spread_leg, rebate=rebate,
                net=spread_leg + rebate, net_bp=(spread_leg + rebate) / vol * 1e4 if vol else np.nan, end_pos_usd=pos * mid_end,
                attr_spread=a_spread, attr_adverse5=a_adv, attr_holding=a_hold, attr_check=spread_leg - (a_spread + a_adv + a_hold),
                peak_pos_usd=peak, avg_abs_pos_usd=abs_pos_time / ((ts[-1] - ts[0]) / 1e6) if len(ts) > 1 else 0.0, flips=flips,
                spread_med_ticks=float(np.median(spread_ticks)), tick_bp=float(tick / np.median((bp + ap) / 2) * 1e4))


def gate_from_scan(sym, train_days):
    S = pd.read_csv(os.path.join(ROOT, "data", "research3", "touch_mm_scan.csv"))
    S = S[(S.sym == sym) & (S.day.astype(str).isin(train_days))]
    g = S.groupby(["side", "imb", "spr"]).agg(n=("n", "sum"), fill=("fill_usd", "sum"), e5=("e5", "sum"))
    g["net5"] = g.e5 / g.fill + 0.7
    return set(g[(g.net5 > 0) & (g.n >= 50)].index)


def one(args):
    tag, day, cap, gated, mode, lat = args
    try:
        gate = gate_from_scan(tag[3:].upper() + "USDTM", ["20260601", "20260701", "20260801"]) if gated else None
        r = replay(tag, day, cap, gate, mode, lat); r["gated"] = gated; r["mode"] = mode; r["lat_ms"] = lat
        return r
    except Exception as e:  # noqa: BLE001
        return dict(sym=tag, day=day, error=str(e)[:120], gated=gated, mode=mode, lat_ms=lat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms", required=True)
    ap.add_argument("--cap", type=float, default=3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--modes", default="touch,penny")
    ap.add_argument("--tag", default="")
    ap.add_argument("--lat", default="0")
    ap.add_argument("--gated", default="0,1")
    ns = ap.parse_args()
    days = ["20251001", "20260101", "20260401", "20260601", "20260701", "20260801", "20260901"]
    jobs = [(s, d, ns.cap, g, m, float(l)) for s in ns.syms.split(",") for d in days for g in [bool(int(x)) for x in ns.gated.split(",")]
            for m in ns.modes.split(",") for l in ns.lat.split(",") if find(s, d)]
    # 增量落盘 + 断点续跑(后台任务多次被无声终止:每完成一个就追加一行 jsonl,重启时跳过已完成的)
    part = os.path.join(ROOT, "data", "research3", f"touch_mm_replay_cap{ns.cap:g}{ns.tag}.jsonl")
    done, rows = set(), []
    if os.path.exists(part):
        for line in open(part, encoding="utf-8"):
            r = json.loads(line); rows.append(r)
            done.add((r.get("tag"), str(r["day"]), bool(r["gated"]), r["mode"], float(r.get("lat_ms", 0))))
    todo = [j for j in jobs if (j[0], j[1], j[3], j[4], j[5]) not in done]
    print(f"{len(jobs)} jobs, {len(done)} done, {len(todo)} to run", flush=True)
    with ProcessPoolExecutor(ns.workers) as ex, open(part, "a", encoding="utf-8") as fh:
        for j, r in zip(todo, ex.map(one, todo)):
            r["tag"] = j[0]
            fh.write(json.dumps({k: (float(v) if isinstance(v, (np.floating,)) else (int(v) if isinstance(v, (np.integer,)) else (bool(v) if isinstance(v, (np.bool_,)) else v))) for k, v in r.items()}) + "\n")
            fh.flush(); rows.append(r)
    R = pd.DataFrame(rows)
    out = os.path.join(ROOT, "data", "research3", f"touch_mm_replay_cap{ns.cap:g}{ns.tag}.csv")
    R.to_csv(out, index=False)
    pd.set_option("display.width", 260)
    ok = R[R.error.isna()] if "error" in R else R
    if "error" in R:
        print("errors:", int(R.error.notna().sum()), R[R.error.notna()][["sym", "day", "error"]].head(5).to_string(index=False))
    print("\n== per sym × mode × gated: sum net, days>0, vol/day ==")
    print(ok.groupby(["sym", "mode", "gated"]).agg(net=("net", "sum"), pos_days=("net", lambda x: int((x > 0).sum())), days=("net", "size"),
                                              vol_day=("vol", "mean"), avg_abs_pos=("avg_abs_pos_usd", "mean"), peak=("peak_pos_usd", "max")).to_string(float_format=lambda v: f"{v:,.1f}"))
    print("saved", out)


if __name__ == "__main__":
    main()
