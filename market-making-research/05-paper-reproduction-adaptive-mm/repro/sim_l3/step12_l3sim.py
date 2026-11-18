"""Step 12(l3sim 列,任务书 "对 100/250/500 ms 的回测同时跑论文忠实成交和 l3sim 两套,分开报"):
P1 目录(Part A g3)与 P2 目录(γ*)在 Δt ∈ {100, 250, 500, 1000} 下接 l3sim(1.8 ms,post-only,精确排队),样本日 = Step 13 扫描日(EC-49)。
指标:净 PnL(含费率:挂单返佣 / 市价单 taker 费,日末残余按 L3 中价)、成交 / 成交额、ahead0 = 0 占比、改价次数与放弃的 ahead、
      被动成交后 1 ms / 10 ms / 100 ms / 1 s / 5 s markout(L3 分辨率的 BBO 中价,基准 = 成交时刻中价;买单成交取 +Δmid)。
输出  reports/step12/table8_l3sim_<sym>.md;数据 data/step14/<sym>/dt<dt>/(1000 在 data/step14/<sym>/)
用法  python step12_l3sim.py <sym> <V_LO> [--dts 100,250,500,1000] [--days ...] [--wait]
"""
import datetime as dt
import glob
import json
import os
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "b"))
import step13_run as S13R      # noqa: E402
import step14_batch as S14B    # noqa: E402

PY = sys.executable
NS = 1_000_000_000
HORIZONS_MS = (1, 10, 100, 1000, 5000)
REBATE_BP = {"USDT": 0.7, "USDC": 1.2}
with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as _fh:
    CONTRACTS = yaml.safe_load(_fh)


def out_dir(sym, d):
    return os.path.join(REPRO, "data", "step14", sym) if d == 1000 else os.path.join(REPRO, "data", "step14", sym, f"dt{d}")


def markout(fl, bbo_ts, bbo_mid):
    res = {}
    for side, sign, lab in ((1, -1, "sell_fill"), (0, +1, "buy_fill")):      # side 1 = 我方卖单成交
        f = fl[fl[:, 1] == side]
        if not len(f):
            res[lab] = None
            continue
        t0 = f[:, 0]; w = f[:, 3].astype(float)
        i0 = np.searchsorted(bbo_ts, t0, side="right") - 1
        ok = i0 >= 0
        base = bbo_mid[np.maximum(i0, 0)]
        r = dict(n=int(ok.sum()), qty=float(w[ok].sum()))
        for h in HORIZONS_MS:
            i1 = np.searchsorted(bbo_ts, t0 + h * 1_000_000, side="right") - 1
            v = ok & (i1 >= 0) & (bbo_ts[np.maximum(i1, 0)] - t0 <= (h + 200) * 1_000_000)
            dlt = sign * (bbo_mid[np.maximum(i1, 0)] - base)
            r[f"mo_{h}ms_mean"] = float(np.average(dlt[v], weights=w[v])) if v.any() else None
            r[f"mo_{h}ms_median"] = float(np.median(dlt[v])) if v.any() else None
        res[lab] = r
    return res


def collect(sym, V_LO, dts, days, gamma):
    c = CONTRACTS[sym]; unit = float(c["tick"]) * float(c["mult"])
    rows = {}
    for d in dts:
        od = out_dir(sym, d)
        for day in days:
            bb = os.path.join(od, f"{day}_bbo.npz")
            if not os.path.exists(bb):
                continue
            z = np.load(bb); bbo_ts, bbo_mid = z["ts"], z["mid2"] / 2.0
            mid_end = float(bbo_mid[-1])
            # 只取本表的两套目录文件(P1 g3 / P2 γ*);dt1000 目录与 Step 14 共用,早先 γ 扫描留下的 P2_g0.0001 等文件不得混入
            cands = [os.path.join(od, f"{day}_P1_M_{k}_L1.8.npz") for k in ("g1", "g2", "g3")] + [os.path.join(od, f"{day}_P2_g{gamma:g}_L1.8.npz")]
            for p in [p for p in cands if os.path.exists(p)]:
                name = os.path.basename(p)[9:-4]                  # P1_M_g1 / P1_M_g2 / P1_M_g3 / P2_g0.01(2026-11-08 补跑后 g1/g2 行一并进表)
                z = np.load(p); rec, fl, rq, mo = z["records"], z["fills"], z["requotes"], z["mos"]
                live = rec[rec[:, 5] >= 0]; a0 = live[:, 5]
                qty = int(fl[:, 3].sum()) if len(fl) else 0
                reb_ticks = REBATE_BP[c["quote"]] * 1e-4 * mid_end
                W = float(z["W"]); I = float(z["I"])
                net = (W + I * mid_end + reb_ticks * qty) * unit                       # W 已含市价单 taker 费(agents._Base);返佣外加;残余按日末中价
                key = (d, name[:7] if name.startswith("P1") else "P2")
                r = rows.setdefault(key, dict(days=0, orders=0, rested=0, a0zero=[], fills=0, qty=0, notional=0.0, net=[], gross=[], requotes=0, rq_given=[], mo_n=0, mo_notional=0.0, t2f=[], mk=[]))
                r["days"] += 1; r["orders"] += len(rec); r["rested"] += len(live); r["a0zero"].append(a0); r["fills"] += len(fl); r["qty"] += qty
                r["notional"] += float((fl[:, 2] * fl[:, 3]).sum() * unit) if len(fl) else 0.0
                r["net"].append(net); r["gross"].append((W + I * mid_end) * unit); r["requotes"] += len(rq)
                if len(rq):
                    r["rq_given"].append(rq[:, 4])
                r["mo_n"] += len(mo); r["mo_notional"] += float((np.abs(mo[:, 1]) * mo[:, 2]).sum() * unit) if len(mo) else 0.0
                if len(fl):
                    r["t2f"].append(fl[:, 6] / 1e6); r["mk"].append(markout(fl, bbo_ts, bbo_mid))
    return rows


def table(sym, V_LO, dts, days, gamma):
    rows = collect(sym, V_LO, dts, days, gamma)
    md = [f"# Table 8(l3sim 列)—— {sym}:P1(Part A 目录,g1 / g2 / g3)与 P2(γ* = {gamma:g},g3)在各 Δt 下接 l3sim(1.8 ms,post-only,精确排队);样本日 {','.join(days)}(每行的\"天\"列 = 实际有回放的天数)", "",
          "| Δt ms | 方案 | 天 | 下单数/日 | 改价次数/日 | 改价放弃 ahead p50/p90(张) | ahead0=0 占比 | 挂单成交次数/日 | 成交张数/日 | 成交额/日 | PnL/日 含返佣(已扣 taker 费) | PnL/日 不含返佣(已扣 taker 费) | 返佣/日 | 市价单/日 | 市价单成交额/日 | 进簿→成交 p50 ms | markout 买成交 1ms/10ms/100ms/1s/5s(tick) | markout 卖成交 1ms/10ms/100ms/1s/5s |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in dts:
        for pol in ("P1_M_g1", "P1_M_g2", "P1_M_g3", "P2"):
            r = rows.get((d, pol))
            if not r:
                continue
            a0 = np.concatenate(r["a0zero"]) if r["a0zero"] else np.zeros(0)
            rq = np.concatenate(r["rq_given"]) if r["rq_given"] else np.zeros(0)
            t2f = np.concatenate(r["t2f"]) if r["t2f"] else np.zeros(0)
            def mo(lab):
                vals = []
                for h in HORIZONS_MS:
                    v = [m[lab][f"mo_{h}ms_mean"] for m in r["mk"] if m.get(lab) and m[lab].get(f"mo_{h}ms_mean") is not None]
                    w = [m[lab]["qty"] for m in r["mk"] if m.get(lab) and m[lab].get(f"mo_{h}ms_mean") is not None]
                    vals.append(f"{np.average(v, weights=w):+.2f}" if v else "–")
                return "/".join(vals)
            n = r["days"]
            md.append(f"| {d} | {pol} | {n} | {r['orders'] / n:,.0f} | {r['requotes'] / n:,.0f} | {np.percentile(rq, 50) if len(rq) else 0:.0f}/{np.percentile(rq, 90) if len(rq) else 0:.0f} | "
                      f"{(a0 == 0).mean() if len(a0) else 0:.1%} | {r['fills'] / n:,.0f} | {r['qty'] / n:,.0f} | ${r['notional'] / n:,.0f} | {np.mean(r['net']):+.1f} | {np.mean(r['gross']):+.1f} | {np.mean(r['net']) - np.mean(r['gross']):+.1f} | "
                      f"{r['mo_n'] / n:.0f} | ${r['mo_notional'] / n:,.0f} | {np.median(t2f) if len(t2f) else 0:.0f} | {mo('buy_fill')} | {mo('sell_fill')} |")
    md += ["", "说明:本表为 l3sim 精确排队口径(用户 2026-11-07 裁决后唯一口径;table8_partA / table8_partB 的队首口径只作历史对照)。PnL 口径:含返佣 = 挂单成交价款 + 返佣 − 市价单 taker 费 + 日末残余按日末中价计价;不含返佣 = 同上不加返佣。P1 在 l3sim 里无市价单。"]
    rep = os.path.join(REPRO, "reports", "step12"); os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"table8_l3sim_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    sym, V_LO = sys.argv[1], int(sys.argv[2])
    arg = lambda f, d: sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d
    dts = [int(x) for x in arg("--dts", "1000,500,250,100").split(",")]
    days = arg("--days", ",".join(S13R.SCAN_DAYS)).split(",")
    if "--wait" in sys.argv:
        logp = os.path.join(REPRO, "logs", f"step12_partB_{sym}.log")
        while not (os.path.exists(logp) and "STEP12B_DONE" in open(logp, encoding="utf-8", errors="replace").read()):
            print("waiting step12_partB", flush=True); time.sleep(300)
    gamma = S14B.gamma_star(sym)
    for d in dts:
        for day in days:
            subprocess.run([PY, os.path.join(HERE, "step14_run.py"), sym, str(V_LO), day, "--lat", "1.8", "--gamma", f"{gamma:g}", "--dt", str(d), "--bbo"], cwd=REPRO)
        table(sym, V_LO, dts, days, gamma)
    print("STEP12L3_DONE", flush=True)
