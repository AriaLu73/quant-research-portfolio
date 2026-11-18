"""Step 15 报告:Table 11({P1 原版, P2 WoMO+费率+延迟, P2 完整+费率+延迟} × L)、延迟配对单调性(UR:同一决策配对为判据,聚合口径作诊断)、
用户 2026-10-16 吃单规则核对(15.3)。
段 PnL 重建:每段 300 s(UTC 日对齐);挂单成交现金流 ±px·qty + rebate·qty,市价单 −e·px − fee·|e|(按决策所在段计);日末残余库存按中价记。
用法  python step15_report.py <sym> <V_LO> [--gamma g]
"""
import datetime as dt
import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPRO, "a"))
sys.path.insert(0, os.path.join(REPRO, "data"))
import ladder_store as LS      # noqa: E402

with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as _fh:
    CONTRACTS = yaml.safe_load(_fh)
NS = 1_000_000_000
SEG_NS = 300 * NS


def mids(sym, day):
    files = sorted(glob.glob(os.path.join(REPRO, "data", "step01", sym, f"{day}_*.npz")))
    ts = np.concatenate([LS.load(p, keys=("bnd_ts",))["bnd_ts"] for p in files]); m = np.concatenate([LS.load(p, keys=("bnd_mid2",))["bnd_mid2"] for p in files])
    ok = m > 0
    return ts[ok], m[ok] / 2.0


def mid_at(ts_arr, mid_arr, t):
    i = np.searchsorted(ts_arr, t, side="right") - 1
    return mid_arr[np.maximum(i, 0)]


def segment_pnl(z, day0, meta_fee, meta_reb, ts_m, mid_m):
    fl, mo = z["fills"], z["mos"]
    cash = {}
    inv = {}
    rebc = {}                                                    # 每段返佣(tick×张),用于单列"不含返佣"
    def add(seg, v, dq):
        cash[seg] = cash.get(seg, 0.0) + v; inv[seg] = inv.get(seg, 0.0) + dq
    for r in fl:
        ts, side, tick, qty = int(r[0]), int(r[1]), int(r[2]), int(r[3])
        seg = int((ts - day0) // SEG_NS)
        add(seg, (tick * qty if side == 1 else -tick * qty) + meta_reb * qty, -qty if side == 1 else qty)
        rebc[seg] = rebc.get(seg, 0.0) + meta_reb * qty
    for r in mo:
        ts, e, px, seg = r[0], r[1], r[2], int(r[3])
        add(seg, -e * px - meta_fee * abs(e), e)
    # 段末残余(清算 MO 已计入上一段;若仍有残余按段末中价记)
    out = []
    for seg in sorted(cash):
        resid = inv.get(seg, 0.0)
        t_end = day0 + (seg + 1) * SEG_NS
        v = cash[seg] + (resid * mid_at(ts_m, mid_m, t_end) if resid else 0.0)
        out.append((seg, v, resid, rebc.get(seg, 0.0)))
    return out


def main(sym, V_LO, gamma):
    c = CONTRACTS[sym]; unit = float(c["tick"]) * float(c["mult"])
    files = sorted(glob.glob(os.path.join(REPRO, "data", "step15", sym, "*_P2_*.npz")))
    days = sorted({os.path.basename(p)[:8] for p in files})
    agents = sorted({os.path.basename(p)[9:-4] for p in files}, key=lambda n: (n.split("_L")[0], float(n.split("_L")[1])))
    reb_p = os.path.join(REPRO, "data", "step13", sym, "dt1000")
    meta = json.loads(bytes(np.load(glob.glob(os.path.join(reb_p, f"{days[0]}_g{gamma:g}_e{V_LO}_reb*.npz"))[0])["meta"]).decode())
    fee, reb = meta["fee_take_ticks"], meta["rebate_ticks"]
    table = {a: dict(x=[], x0=[], fills=0, qty=0, notional=0.0, mo=0, mo_notional=0.0, fee=0.0, rebate=0.0, maxY=[], resid=[]) for a in agents}
    paired = {}
    audit = dict(unwind=0, unwind_ok=0, increase=0, rt_bp=[])
    for day in days:
        day0 = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
        ts_m, mid_m = mids(sym, day)
        fills_by = {}
        for a in agents:
            p = os.path.join(REPRO, "data", "step15", sym, f"{day}_{a}.npz")
            if not os.path.exists(p):
                continue
            z = np.load(p); t = table[a]
            got = {seg: (v, resid, rb) for seg, v, resid, rb in segment_pnl(z, day0, fee, reb, ts_m, mid_m)}
            hours = sorted(int(os.path.basename(q)[9:11]) for q in glob.glob(os.path.join(REPRO, "data", "step01", sym, f"{day}_*.npz")))
            for seg in [h * 12 + j for h in hours for j in range(12)]:      # 全部段(无事件的段 PnL = 0),与 sim_partB 的段数口径一致
                v, resid, rb = got.get(seg, (0.0, 0.0, 0.0))
                t["x"].append(v * unit); t["x0"].append((v - rb) * unit); t["resid"].append(abs(resid))
            fl, mo = z["fills"], z["mos"]
            t["fills"] += len(fl); t["qty"] += int(fl[:, 3].sum()) if len(fl) else 0
            t["notional"] += float((fl[:, 2] * fl[:, 3]).sum() * unit) if len(fl) else 0.0
            t["rebate"] += float(reb * fl[:, 3].sum() * unit) if len(fl) else 0.0
            t["mo"] += len(mo); t["mo_notional"] += float((np.abs(mo[:, 1]) * mo[:, 2]).sum() * unit) if len(mo) else 0.0
            t["fee"] += float(fee * np.abs(mo[:, 1]).sum() * unit) if len(mo) else 0.0
            # 库存路径 max|Y|(全天,段内归零由 MO 实现)
            ev = sorted([(int(r[0]), (-r[3] if r[1] == 1 else r[3])) for r in fl] + [(int(r[0]), r[1]) for r in mo])
            y, my = 0.0, 0.0
            for _, dq in ev:
                y += dq; my = max(my, abs(y))
            t["maxY"].append(my)
            fills_by[a] = fl
            # 15.3 吃单规则核对(完整策略、1.8 ms):MO 减少 |Y| = 平仓;与被平的挂单开仓价(FIFO)比,一开一平净 ≥ 0.1 bp?
            if a == "P2_full_L1.8":
                evs = sorted([(int(r[0]), 0, (-int(r[3]) if r[1] == 1 else int(r[3])), float(r[2])) for r in fl] + [(int(r[0]), 1, float(r[1]), float(r[2])) for r in mo])
                lots = []   # (qty signed, price)
                for ts_, kind, dq, px in evs:
                    if kind == 0:
                        lots.append([dq, px]); continue
                    cur = sum(l[0] for l in lots)
                    if cur * dq < 0:                                   # 减仓
                        audit["unwind"] += 1
                        remain, pnl, qsum = abs(dq), 0.0, 0.0
                        while remain > 0 and lots and lots[0][0] * dq < 0:
                            take = min(remain, abs(lots[0][0]))
                            side = 1 if lots[0][0] > 0 else -1          # 多头被卖出
                            pnl += side * (px - lots[0][1]) * take + (reb - fee) * take
                            qsum += take; lots[0][0] -= side * take; remain -= take
                            if lots[0][0] == 0:
                                lots.pop(0)
                        if remain > 0:
                            lots.append([dq + (abs(dq) - remain) * (1 if dq < 0 else -1), px])
                        if qsum > 0:
                            bp = pnl / (qsum * px) * 1e4
                            audit["rt_bp"].append(bp); audit["unwind_ok"] += int(bp >= 0.1)
                    else:
                        audit["increase"] += 1; lots.append([dq, px])
        # 配对单调性:同一决策(born, side, tick)在相邻延迟下
        for lab in ("full", "WoMO"):
            names = [a for a in agents if a.startswith(f"P2_{lab}_L")]
            keyed = {}
            for a in names:
                fl = fills_by.get(a)
                if fl is None:
                    continue
                d = {}
                for r in fl:
                    k = (int(r[9]), int(r[1]), int(r[2]))
                    q0 = d.get(k, [0, None]); q0[0] += int(r[3]); q0[1] = int(r[0]) if q0[1] is None else min(q0[1], int(r[0]))
                    d[k] = q0
                keyed[a] = d
            for a1, a2 in zip(names[:-1], names[1:]):
                if a1 not in keyed or a2 not in keyed:
                    continue
                both = set(keyed[a1]) & set(keyed[a2])
                n_qty_worse = n_qty_same = n_time_worse = 0
                mo5 = []
                for k in both:
                    q1, t1 = keyed[a1][k]; q2, t2 = keyed[a2][k]
                    n_qty_worse += int(q2 < q1); n_qty_same += int(q2 == q1); n_time_worse += int(t2 > t1)
                    sign = -1 if k[1] == 1 else 1
                    m1 = sign * (mid_at(ts_m, mid_m, t1 + 5 * NS) - k[2]); m2 = sign * (mid_at(ts_m, mid_m, t2 + 5 * NS) - k[2])
                    mo5.append(m2 - m1)
                pr = paired.setdefault((lab, a1, a2), dict(n_both=0, only1=0, only2=0, qty_worse=0, qty_same=0, time_worse=0, mo5=[]))
                pr["n_both"] += len(both); pr["only1"] += len(set(keyed[a1]) - both); pr["only2"] += len(set(keyed[a2]) - both)
                pr["qty_worse"] += n_qty_worse; pr["qty_same"] += n_qty_same; pr["time_worse"] += n_time_worse; pr["mo5"] += mo5
    md = [f"# Table 11 —— {sym}:P2 完整 / WoMO + 费率(maker {reb:.0f} tick/张返佣, taker {fee:.0f} tick/张)+ 延迟,l3sim 精确排队,γ* = {gamma:g},{len(days)} 天(每天 288 段)", "",
          "PnL 口径:**含返佣** = 挂单成交 ± 价款 + 返佣 − 市价单与段末清算的 taker 费;**不含返佣** = 同上但不加返佣(taker 费仍扣)。单位 " + c["quote"] + ";m(X_T) 为每段(300 s)PnL 均值。", "",
          "| 方案 | L ms | 段数 | m(X_T) 含返佣 /段 | m(X_T) 不含返佣 /段 | σ(X_T) 含返佣 | σ(X_T) 不含返佣 | IR 含返佣 | IR 不含返佣 | 日均 PnL 含返佣 | 日均 PnL 不含返佣 | 日均返佣 | 挂单成交次数 | 成交张数 | 挂单成交额 | 市价单笔数 | 市价单成交额 | 占成交额 | taker 费合计 | 返佣合计 | max\\|Y\\| 日均 | 段末残余>0 占比 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in agents:
        t = table[a]; x = np.array(t["x"]); x0 = np.array(t["x0"])
        if len(x) == 0:
            continue
        lab, lm = a.split("_L")
        tot = t["notional"] + t["mo_notional"]
        ir = lambda v: v.mean() / v.std(ddof=1) if v.std() > 0 else 0.0
        md.append(f"| {lab} | {lm} | {len(x)} | {x.mean():+.3f} | {x0.mean():+.3f} | {x.std(ddof=1):.3f} | {x0.std(ddof=1):.3f} | {ir(x):+.3f} | {ir(x0):+.3f} | {x.sum() / len(days):+.1f} | {x0.sum() / len(days):+.1f} | {(x.sum() - x0.sum()) / len(days):+.1f} | {t['fills']:,} | {t['qty']:,} | ${t['notional']:,.0f} | "
                  f"{t['mo']:,} | ${t['mo_notional']:,.0f} | {t['mo_notional'] / tot if tot else 0:.1%} | ${t['fee']:,.2f} | ${t['rebate']:,.2f} | {np.mean(t['maxY']):.0f} | {np.mean(np.array(t['resid']) > 0):.1%} |")
    # 论文忠实 + 费率对照
    pj = [json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob(os.path.join(REPRO, "data", "step15", sym, "*_paper.json")))]
    if pj:
        md += ["", "对照(论文忠实成交 + 费率,无延迟,50 ms 网格盘口;队首口径,用户 2026-11-07 裁决后只作历史对照):", "", "| 方案 | 段数 | m(X_T) 含返佣 /段(已扣 taker 费;不含返佣值未单独保存) | σ | 成交笔/段 | 市价单笔/段 |", "|---|---|---|---|---|---|"]
        for n in ("P2_full_paper", "P2_WoMO_paper", "alpha_c"):
            m = np.mean([j[n]["m"] for j in pj]); sd = np.mean([j[n]["sd"] for j in pj])
            md.append(f"| {n} | {sum(j[n]['n_seg'] for j in pj)} | {m:+.3f} | {sd:.3f} | {np.mean([j[n]['fills'] for j in pj]):.2f} | {np.mean([j[n]['n_mo'] for j in pj]):.2f} |")
    md += ["", f"P1 原版(Part A,无费率、无延迟、队首假设)见 reports/step10/expA_{sym}_dt1000_base.md。", "",
           "## 延迟单调性(UR:同一决策配对为判据;聚合口径见上表)", "",
           "| 方案 | L_a → L_b | 两边都成交的决策 | 仅 L_a 成交 | 仅 L_b 成交 | L_b 成交量更少 | 相同 | L_b 成交更晚 | 5 s markout 差(L_b − L_a)均值 tick | 差 ≤ 0 占比 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for (lab, a1, a2), pr in sorted(paired.items(), key=lambda kv: (kv[0][0], float(kv[0][1].split("_L")[1]))):
        mo5 = np.array(pr["mo5"])
        md.append(f"| {lab} | {a1.split('_L')[1]} → {a2.split('_L')[1]} | {pr['n_both']:,} | {pr['only1']:,} | {pr['only2']:,} | {pr['qty_worse'] / max(pr['n_both'], 1):.1%} | {pr['qty_same'] / max(pr['n_both'], 1):.1%} | "
                  f"{pr['time_worse'] / max(pr['n_both'], 1):.1%} | {mo5.mean() if len(mo5) else float('nan'):+.2f} | {(mo5 <= 0).mean() if len(mo5) else float('nan'):.1%} |")
    rt = np.array(audit["rt_bp"])
    md += ["", "## 吃单规则核对(用户 2026-10-16;P2 完整 1.8 ms)", "",
           f"市价单共 {audit['unwind'] + audit['increase']} 笔:减仓 {audit['unwind']} 笔(其中一开一平净 ≥ 0.1 bp 的 {audit['unwind_ok']} 笔,净 bp 中位 {np.median(rt) if len(rt) else float('nan'):.2f}),加仓 {audit['increase']} 笔(规则要求预期收益 ≥ 我方费率 + 半价差,P2 的价值函数比较不产生该量,全部列为不满足)。"]
    # 各测试日回放小时(用户 2026-11-07:数据残缺的日子标出每天交易了多少小时)
    import csv as _csv
    gaps = {r["day"]: r for r in _csv.DictReader(open(os.path.join(REPRO, "reports", "step00", f"gaps_{sym}.csv"), encoding="utf-8"))}
    md += ["", "## 各测试日回放小时(数据残缺标记)", "",
           "回放小时 = 该 UTC 日有 L3 数据的整点小时数,回测只在这些小时里报价与成交;有效覆盖 h = 扣除小时内缺口后的实际覆盖。段数 = 回放小时 × 12。", "",
           "| 测试日 | 回放小时 | 有效覆盖 h | 覆盖率 | 段数 | 数据完整? |", "|---|---|---|---|---|---|"]
    for d in days:
        n = len(glob.glob(os.path.join(REPRO, "data", "step01", sym, f"{d}_*.npz"))); r = gaps.get(d)
        ch = float(r["covered_h"]) if r else float("nan"); cf = float(r["cover_frac"]) if r else float("nan")
        md.append(f"| {d} | {n} h | {ch:.1f} h | {cf:.0%} | {n * 12} | {('完整(切点 21:41 后为 final_test 锁定,不回放)' if n < 24 else '完整') if cf >= 0.99 else '残缺'} |")
    rep = os.path.join(REPRO, "reports", "step15"); os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"table11_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    g = float(sys.argv[sys.argv.index("--gamma") + 1]) if "--gamma" in sys.argv else 1e-4
    main(sym, V_LO, g)
