"""Step 12(Part B 列,任务书 Table 8 第二批):P2 策略(γ*,完整 / WoMO)对决策间隔 Δt ∈ {100, 250, 500, 1000, 2000} ms 的敏感性。
每个 Δt 的到达概率 / 需求矩 / (c,p) 池都来自该 Δt 自己的 Step 2–4 产物(不换算);QVI 目录按该 Δt 重建(300 s / Δt 步),论文忠实成交回放(sim_partB)。
样本日 = Step 13 的 γ 扫描日(EC-41 的三天;EC-49:Δt=100 ms 一套目录约 50 分钟,全部测试日 × 四个 Δt × 两合约不可行)。
每个 Δt 另报:Part A 的 N = T/Δt、Part B 步数、π(1,1) 量级、每区间无 MO 比例、(c,p) 有效样本量。
Markout 口径同 table8_partA:以成交区间末 t_{k+1} 的中价为基准,看 +h 的中价变动(买单成交取 +Δmid,卖单取 −Δmid),50 ms 网格盘口。
输出  data/step12/<sym>/partB_dt<dt>_<day>.json;reports/step12/table8_partB_<sym>.md
用法  python step12_partB.py <sym> <V_LO> [--dts 2000,500,250,100,1000] [--days d1,d2,d3]
"""
import datetime as dt
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "a"))
sys.path.insert(0, os.path.join(REPRO, "sim_l3"))
import arrivals as AR          # noqa: E402
import sim_paper as SP         # noqa: E402
import sim_partB as SB         # noqa: E402
import step13_build as S13     # noqa: E402
import step13_run as S13R      # noqa: E402
import step14_batch as S14B    # noqa: E402

NS = 1_000_000_000
HORIZONS_MS = (50, 100, 1000, 5000)


def catalog(sym, V_LO, day, g, dt_ms, eb):
    p = os.path.join(REPRO, "data", "step13", sym, f"dt{dt_ms}", f"{day}_g{g:g}_e{eb:g}.npz")
    if not os.path.exists(p):
        S13.build(sym, V_LO, day, gamma=g, dt_ms=dt_ms, e_bar=eb, store_phi=(dt_ms == 1000))
    return S13.load(p)


def dt_facts(sym, day, dt_ms, fr):
    z4 = np.load(os.path.join(REPRO, "data", "step04", sym, f"dt{dt_ms}", f"{day}.npz"))
    cnt, n11 = z4["g3_count"], z4["g3_11"]
    z2 = np.load(os.path.join(REPRO, "data", "step02", sym, "base", f"dt{dt_ms}", f"{day}.npz"))
    valid = z2["valid"]
    return dict(N_partA=int(round(86400 * 1000 / dt_ms)) - 1, steps_partB=int(round(300 * 1000 / dt_ms)),
                pi11_mean=float(n11.sum() / max(cnt.sum(), 1)), no_mo_share=float((~(fr.ind_plus | fr.ind_minus)).mean()),
                cp_valid=int(valid.sum()) if valid.ndim == 1 else int(valid.any(axis=tuple(range(1, valid.ndim))).sum()))


def markouts(fill_log, fr, dt_ms, lads, day):
    ts = np.concatenate([d["bnd_ts"] for d in lads]); m2 = np.concatenate([d["bnd_mid2"] for d in lads])
    ok = m2 > 0; ts_ok, mid_ok = ts[ok], m2[ok] / 2.0
    day0 = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    out = {}
    arr = np.asarray(fill_log, float).reshape(-1, 6)
    for side, col, sign in (("buy_fill", 2, +1), ("sell_fill", 1, -1)):          # qm = 我方买单成交,qp = 我方卖单成交
        sel = arr[:, col] > 0
        if not sel.any():
            out[side] = None
            continue
        ks = arr[sel, 0].astype(int); w = arr[sel, col]
        t0 = day0 + (ks + 1) * dt_ms * 1_000_000
        i0 = np.searchsorted(ts_ok, t0, side="right") - 1
        valid = i0 >= 0
        base = mid_ok[np.maximum(i0, 0)]
        r = dict(n=int(valid.sum()), qty=float(w[valid].sum()))
        for h in HORIZONS_MS:
            i1 = np.searchsorted(ts_ok, t0 + h * 1_000_000, side="right") - 1
            v = valid & (i1 >= 0) & (ts_ok[np.maximum(i1, 0)] - t0 <= (h + 200) * 1_000_000)
            d = sign * (mid_ok[np.maximum(i1, 0)] - base)
            r[f"mo_{h}ms_mean"] = float(np.average(d[v], weights=w[v])) if v.any() else None
            r[f"mo_{h}ms_median"] = float(np.median(d[v])) if v.any() else None
        out[side] = r
    return out


def run(sym, V_LO, day, dt_ms, g):
    c = S13R.CONTRACTS[sym]
    pols = []
    for eb, lab in ((V_LO, "full"), (0, "WoMO")):
        q, meta = catalog(sym, V_LO, day, g, dt_ms, eb)
        pols.append(SB.P2Policy(f"P2_{lab}", q, q.edges))
    fee = meta["fee_take_ticks"]
    segs, fr, fl = SB.simulate_day(sym, day, dt_ms, pols, AR.GState("g3"), V_LO, float(c["tick"]), float(c["mult"]), fee, log_fills=True)
    lads = SP.load_day(sym, day)
    out = dict(sym=sym, day=day, dt_ms=dt_ms, gamma=g, facts=dt_facts(sym, day, dt_ms, fr), policies={})
    for n, s in segs.items():
        S = SB.summarize(s, dt_ms)
        S["markout"] = markouts(fl[n], fr, dt_ms, lads, day)
        S["liq_qty_mean"] = float(np.mean([abs(x["Y_T"]) for x in s])); S["liq_qty_p90"] = float(np.percentile([abs(x["Y_T"]) for x in s], 90))
        S["hold_all_s"] = [float(h) for x in s for h in x["hold_s"]]
        out["policies"][n] = S
    od = os.path.join(REPRO, "data", "step12", sym); os.makedirs(od, exist_ok=True)
    with open(os.path.join(od, f"partB_dt{dt_ms}_{day}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, default=float)
    print(f"{sym} {day} dt={dt_ms}: " + " | ".join(f"{n}: m={S['m']:+.3f} sd={S['sd']:.3f} fills/seg={S['fills']:.2f} mo/seg={S['n_mo']:.2f} max|Y|={S['maxY_mean']:.0f}" for n, S in out["policies"].items()), flush=True)
    return out


def table(sym, dts, days):
    rows = {}
    facts = {}
    for d in dts:
        for day in days:
            p = os.path.join(REPRO, "data", "step12", sym, f"partB_dt{d}_{day}.json")
            if not os.path.exists(p):
                continue
            j = json.load(open(p, encoding="utf-8"))
            facts.setdefault(d, []).append(j["facts"])
            for n, S in j["policies"].items():
                rows.setdefault((d, n), []).append(S)
    md = [f"# Table 8(Part B 列)—— {sym}:P2 策略(γ*,完整 / WoMO)对决策间隔 Δt 的敏感性(论文忠实成交,300 s 段,段末清算;样本日 {','.join(days)},EC-49)", "",
          "## 每个 Δt 的事实(样本日均值)", "", "| Δt ms | Part A 目录长度 N | Part B 步数 300 s/Δt | π(1,1) 量级(g3,计数加权) | 每区间无 MO 比例 | (c,p) 有效样本/日(两侧合计) |", "|---|---|---|---|---|---|"]
    for d in dts:
        if d in facts:
            f = facts[d]
            md.append(f"| {d} | {f[0]['N_partA']} | {f[0]['steps_partB']} | {np.mean([x['pi11_mean'] for x in f]):.4f} | {np.mean([x['no_mo_share'] for x in f]):.1%} | {np.mean([x['cp_valid'] for x in f]):.0f} |")
    md += ["", "## 指标(同 Step 12;PnL 无费率,费率 / 延迟见 Step 15)", "",
           "| Δt ms | 方案 | 段数 | m(X_T) USDT | σ(X_T) | IR | 日均 PnL | 成交笔/段 | 成交额/日 | 市价单/段 | 市价单成交额/日 | max\\|Y\\| 均值 | 段末 \\|Y_T\\| 均值 / p90 | 段末清零占比 | 持仓段 p50 / p90 / max s | >300 s | markout 买成交 50ms/100ms/1s/5s(tick) | markout 卖成交 50ms/100ms/1s/5s |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in dts:
        for n in ("P2_full", "P2_WoMO"):
            rs = rows.get((d, n))
            if not rs:
                continue
            xs_m = np.mean([r["m"] for r in rs]); nseg = sum(r["n_seg"] for r in rs)
            hold = np.concatenate([np.asarray(r["hold_all_s"]) for r in rs]) if any(len(r["hold_all_s"]) for r in rs) else np.zeros(1)
            def mo(side):
                vals = []
                for h in HORIZONS_MS:
                    v = [r["markout"][side][f"mo_{h}ms_mean"] for r in rs if r["markout"].get(side) and r["markout"][side].get(f"mo_{h}ms_mean") is not None]
                    w = [r["markout"][side]["qty"] for r in rs if r["markout"].get(side) and r["markout"][side].get(f"mo_{h}ms_mean") is not None]
                    vals.append(f"{np.average(v, weights=w):+.2f}" if v else "–")
                return "/".join(vals)
            md.append(f"| {d} | {n} | {nseg} | {xs_m:+.3f} | {np.mean([r['sd'] for r in rs]):.3f} | {np.mean([r['IR'] for r in rs]):+.3f} | {np.mean([r['pnl_sum'] for r in rs]):+.1f} | "
                      f"{np.mean([r['fills'] for r in rs]):.2f} | ${np.mean([r['notional'] for r in rs]):,.0f} | {np.mean([r['n_mo'] for r in rs]):.2f} | ${np.mean([r['mo_notional'] for r in rs]):,.0f} | "
                      f"{np.mean([r['maxY_mean'] for r in rs]):.0f} | {np.mean([r['liq_qty_mean'] for r in rs]):.1f} / {np.mean([r['liq_qty_p90'] for r in rs]):.0f} | {np.mean([r['YT_zero_share'] for r in rs]):.1%} | "
                      f"{np.median(hold):.0f} / {np.percentile(hold, 90):.0f} / {hold.max():.0f} | {sum(r['hold_gt_300s'] for r in rs)} | {mo('buy_fill')} | {mo('sell_fill')} |")
    md += ["", "说明:持仓段 > 300 s 为 0 是 300 s 段末清算的机械结果(任务书 Step 13 第 2 条),所以同时报段末被清算的 |Y_T| 分布;段末清零占比 = 段末 Y_T = 0 的段。"]
    rep = os.path.join(REPRO, "reports", "step12"); os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"table8_partB_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    arg = lambda f, d: sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d
    dts = [int(x) for x in arg("--dts", "1000,2000,500,250,100").split(",")]
    days = arg("--days", ",".join(S13R.SCAN_DAYS)).split(",")
    g = S14B.gamma_star(sym)
    print("gamma*", g, "dts", dts, "days", days, flush=True)
    for d in dts:
        for day in days:
            run(sym, V_LO, day, d, g)
        table(sym, dts, days)
    print("STEP12B_DONE", flush=True)
