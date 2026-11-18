"""Step 12 指标(Part A 列,任务书 Table 8):
  (1) 样本外净 PnL:实验 A 的 J_T / PnL_T(论文忠实口径,无费率;含费率版在 Step 我方费率 的 l3sim 列)。
  (2) MO 到达预测质量:对每个测试日,用其训练窗(step06 的 window)的 g1/g2/g3 模型预测下一区间 1^±,报 log-loss / Brier(基线 = 窗内无条件频率)。
  (3) Adverse selection:被动成交后 h ∈ {50 ms, 100 ms, 1 s, 5 s} 的 markout(中价变动,单位 tick,买单成交为 +(mid_{t+h} − mid_t),卖单相反);
      1 ms / 10 ms 需要 L3 时间戳,留给 Step 14 的 l3sim 列。中价取 50 ms 网格边界(ladder_store)。
  (4) Fill rate、库存:成交区间占比、std(I)、max|I|、持仓段时长分布(来自实验 A 的 series)。
  (5) 撤单 / 队列位置损失:Step 14。
输出  reports/step12/table8_partA_<sym>.md/.json
用法  python step12_metrics.py <sym> [dts]
"""
import datetime as dt
import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "data"))
import arrivals as AR            # noqa: E402
import ladder_store as LS        # noqa: E402
import step04_batch as S4        # noqa: E402
import step06_catalog as S6      # noqa: E402

NS = 1_000_000_000
HORIZONS_MS = (50, 100, 1000, 5000)


def mids_of_day(sym, day):
    files = sorted(glob.glob(os.path.join(REPRO, "data", "step01", sym, f"{day}_*.npz")))
    ts = np.concatenate([LS.load(p, keys=("bnd_ts",))["bnd_ts"] for p in files])
    mid2 = np.concatenate([LS.load(p, keys=("bnd_mid2",))["bnd_mid2"] for p in files])
    return ts, mid2


def prediction_quality(sym, day, dt_ms, tag="base"):
    p2 = os.path.join(REPRO, "data", "step02", sym, tag, f"dt{dt_ms}", f"{day}.npz")
    fr, _ = S4.frame_from_step02(p2)
    days = S6.training_window(sym, day, dt_ms, tag)
    out = {}
    for kind in ("g1", "g2", "g3"):
        g, m = S6.window_arrivals(sym, days, dt_ms, kind)
        out[kind] = AR.score(fr, m)
    return out


def markouts(sym, day, dt_ms, series, policy, ts, mid2):
    """series:expA 的 npz;对该策略每个有成交的区间 k,在 t_{k+1}(区间末)取基准中价,再看 +h 的中价变动。"""
    qp, qm = series[f"{policy}_qp"], series[f"{policy}_qm"]
    N = len(qp)
    day0 = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    t_end = day0 + (np.arange(N) + 1) * dt_ms * 1_000_000
    ok = mid2 > 0
    ts_ok, mid_ok = ts[ok], mid2[ok] / 2.0
    res = {}
    for side, q, sign in (("buy_fill", qm, +1), ("sell_fill", qp, -1)):      # 我方买单成交(qm)后希望中价上行 → +(Δmid)
        ks = np.where(q > 0)[0]
        if len(ks) == 0:
            res[side] = None
            continue
        t0 = t_end[ks]
        i0 = np.searchsorted(ts_ok, t0, side="right") - 1
        valid = i0 >= 0
        base = mid_ok[np.maximum(i0, 0)]
        r = dict(n=int(valid.sum()))
        for h in HORIZONS_MS:
            i1 = np.searchsorted(ts_ok, t0 + h * 1_000_000, side="right") - 1
            v = valid & (i1 >= 0) & (ts_ok[np.maximum(i1, 0)] - t0 <= (h + 200) * 1_000_000)   # 缺口保护:+h 的记录不能比目标晚太多
            d = sign * (mid_ok[np.maximum(i1, 0)] - base)
            w = q[ks]
            r[f"mo_{h}ms_mean"] = float(np.average(d[v], weights=w[v])) if v.any() else None
            r[f"mo_{h}ms_median"] = float(np.median(d[v])) if v.any() else None
        res[side] = r
    return res


def main(sym, dts):
    rows = []
    for dt_ms in dts:
        od = os.path.join(REPRO, "data", "step10", sym, "base", f"dt{dt_ms}")
        for p in sorted(glob.glob(os.path.join(od, "expA_*.json"))):
            day = os.path.basename(p)[5:13]
            res = json.load(open(p, encoding="utf-8"))
            series = np.load(os.path.join(od, f"expA_{day}_series.npz"))
            ts, mid2 = mids_of_day(sym, day)
            pq = prediction_quality(sym, day, dt_ms)
            for pol in ("M_g3", "G_g3", "Level1", "Level3"):
                r = res[pol]
                mo = markouts(sym, day, dt_ms, series, pol, ts, mid2)
                rows.append(dict(sym=sym, day=day, dt_ms=dt_ms, policy=pol, J=r["J_T_usdt"], PnL=r["PnL_T_usdt"], fills=r["n_fills"], notional=r["notional_usdt"],
                                 std_I=r["std_I"], max_I=r["max_abs_I"], hold_p50=r["hold_p50_s"], hold_max=r["hold_max_s"], hold_gt300=r["hold_gt_300s"],
                                 n_intervals=len(series[f"{pol}_qp"]), fill_rate=float(((series[f"{pol}_qp"] > 0) | (series[f"{pol}_qm"] > 0)).mean()),
                                 markout=mo, pq={k: {s: v[s]["logloss"] for s in ("plus", "minus")} for k, v in pq.items()},
                                 pq_base=pq["g3"]["plus"]["logloss_base"], brier={k: pq[k]["plus"]["brier"] for k in pq}, brier_base=pq["g3"]["plus"]["brier_base"]))
            print(f"{sym} {day} dt={dt_ms}: M_g3 fill_rate={rows[-4]['fill_rate']:.4f} logloss g1/g2/g3={pq['g1']['plus']['logloss']:.4f}/{pq['g2']['plus']['logloss']:.4f}/{pq['g3']['plus']['logloss']:.4f} (base {pq['g3']['plus']['logloss_base']:.4f})", flush=True)
    rep = os.path.join(REPRO, "reports", "step12")
    os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"table8_partA_{sym}.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1, default=float)
    md = [f"# Table 8(Part A 列)—— {sym}:P1 策略对决策间隔 Δt 的敏感性(论文忠实成交;费率 / l3sim / 撤单列见 Step 14–15)", "",
          "| Δt ms | 方案 | 天 | J_T 均值 | PnL_T 均值 | 成交笔数/日 | 成交额/日 | 成交区间占比 | std(I) | max\\|I\\| | 持仓段>300 s/日 | markout 买成交 50ms/100ms/1s/5s(tick) | markout 卖成交 50ms/100ms/1s/5s | log-loss g1/g2/g3(基线) | Brier g3(基线) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for dt_ms in dts:
        for pol in ("M_g3", "G_g3", "Level1", "Level3"):
            rs = [r for r in rows if r["dt_ms"] == dt_ms and r["policy"] == pol]
            if not rs:
                continue
            def mo(side):
                vals = []
                for h in HORIZONS_MS:
                    xs = [r["markout"][side][f"mo_{h}ms_mean"] for r in rs if r["markout"][side] and r["markout"][side][f"mo_{h}ms_mean"] is not None]
                    vals.append(f"{np.mean(xs):+.2f}" if xs else "–")
                return "/".join(vals)
            md.append(f"| {dt_ms} | {pol} | {len(rs)} | {np.mean([r['J'] for r in rs]):+.1f} | {np.mean([r['PnL'] for r in rs]):+.1f} | {np.mean([r['fills'] for r in rs]):.0f} | ${np.mean([r['notional'] for r in rs]):,.0f} | "
                      f"{np.mean([r['fill_rate'] for r in rs]):.4f} | {np.mean([r['std_I'] for r in rs]):.0f} | {np.mean([r['max_I'] for r in rs]):.0f} | {np.mean([r['hold_gt300'] for r in rs]):.1f} | {mo('buy_fill')} | {mo('sell_fill')} | "
                      f"{np.mean([r['pq']['g1']['plus'] for r in rs]):.4f}/{np.mean([r['pq']['g2']['plus'] for r in rs]):.4f}/{np.mean([r['pq']['g3']['plus'] for r in rs]):.4f} ({np.mean([r['pq_base'] for r in rs]):.4f}) | "
                      f"{np.mean([r['brier']['g3'] for r in rs]):.5f} ({np.mean([r['brier_base'] for r in rs]):.5f}) |")
    with open(os.path.join(rep, f"table8_partA_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    sym = sys.argv[1]
    dts = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [100, 250, 500, 1000, 2000]
    main(sym, dts)
