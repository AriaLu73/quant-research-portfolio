"""Step 6(+3、4、7 的组装):为一个测试日建 Policy Catalog。
训练窗(附录第 6 条)  测试日之前最近 20 个可用日(9 月 L2 训练日 + 10 月 train/validation 的 L3 日,按日期排序取最后 20 个)。
矩(Step 3,Eq. 8)    窗内各日 data/step02 的逐区间 (c,p),只取 valid 的,汇总求 μ(两侧分别)。另算 Eq.(48) 字面口径作对照。
到达概率(Step 4)     窗内各日 data/step04 的计数相加 → ArrivalModel → Tables(未见状态按 EC-17 填充)。
递推(Step 5)         bellman.backward,N = 86400·1000/Δt(UTC 日,Part A 的 T = 日终 UTC 00:00),λ 按 EC-21。
输出  data/step06/<sym>/<tag>/dt<ms>/<test_day>_<g>.npz(catalog 压缩存储)+ 同名 .json(窗口、矩、检查)
用法  python step06_catalog.py <sym> <test_day> [dt_ms] [--g g1,g2,g3] [--tag base] [--det](确定性需求,实验 C)
"""
import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台 gbk 会在打印表格时崩

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import arrivals as AR     # noqa: E402
import bellman as BM      # noqa: E402
import moments as MO      # noqa: E402

with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as _fh:
    CONTRACTS = yaml.safe_load(_fh)
WINDOW = 20


def available_days(sym, dt_ms, tag):
    return sorted(os.path.basename(p)[:8] for p in glob.glob(os.path.join(REPRO, "data", "step02", sym, tag, f"dt{dt_ms}", "*.npz")))


def training_window(sym, test_day, dt_ms, tag, n=WINDOW):
    days = [d for d in available_days(sym, dt_ms, tag) if d < test_day]
    return days[-n:]


def window_moments(sym, days, dt_ms, tag):
    cs = [[], []]
    ps = [[], []]
    n_total = 0
    for d in days:
        z = np.load(os.path.join(REPRO, "data", "step02", sym, tag, f"dt{dt_ms}", f"{d}.npz"))
        n_total += int(len(z["t0"]) - z["gap"].sum())
        for col in (0, 1):
            v = z["valid"][:, col]
            cs[col].append(z["c"][v, col])
            ps[col].append(z["p"][v, col])
    out = {}
    for col, lab in ((0, "plus"), (1, "minus")):
        c, p = np.concatenate(cs[col]), np.concatenate(ps[col])
        out[lab] = MO.moments(c, p)
        out[lab + "_eq48"] = dict(mu_c=float(c.sum() / n_total), mu_cp=float((c * p).sum() / n_total), mu_c2=float((c * c).sum() / n_total),
                                  mu_c2p=float((c * c * p).sum() / n_total), mu_c2p2=float((c * c * p * p).sum() / n_total), n=int(n_total))
        out[lab + "_std"] = dict(c_std=float(c.std()), p_std=float(p.std()), corr=float(np.corrcoef(c, p)[0, 1]) if len(c) > 2 else None)
    out["checks"] = MO.table1_checks(out["plus"], out["minus"])
    return out


def window_arrivals(sym, days, dt_ms, kind):
    g = AR.GState(kind)
    m = AR.ArrivalModel(g)
    for d in days:
        z = np.load(os.path.join(REPRO, "data", "step04", sym, f"dt{dt_ms}", f"{d}.npz"))
        m.count += z[f"{kind}_count"]
        m.n_plus += z[f"{kind}_plus"]
        m.n_minus += z[f"{kind}_minus"]
        m.n_11 += z[f"{kind}_11"]
    return g, m.finalize()


def build(sym, test_day, dt_ms=1000, kinds=("g1", "g2", "g3"), tag="base", deterministic=False, lam_usdt=0.0005):
    days = training_window(sym, test_day, dt_ms, tag)
    if len(days) < 2:
        raise SystemExit(f"{sym} {test_day}: 训练窗不足({days})")
    mom = window_moments(sym, days, dt_ms, tag)
    mp, mm = mom["plus"], mom["minus"]
    if deterministic:
        mp, mm = MO.deterministic(mp), MO.deterministic(mm)
    tick, mult = float(CONTRACTS[sym]["tick"]), float(CONTRACTS[sym]["mult"])
    lam = lam_usdt / (tick * mult)                         # EC-21:USDT/张² → (tick×张)/张²:价值函数以 tick×张 记账,1 tick×张 = TICK·mult USDT
    N = int(round(86400 * 1000 / dt_ms)) - 1               # 决策时刻 t_0..t_N 共 N+1 个 = 当日区间数;T = t_{N+1} = 次日 UTC 00:00
    od = os.path.join(REPRO, "data", "step06", sym, tag + ("_det" if deterministic else ""), f"dt{dt_ms}")
    os.makedirs(od, exist_ok=True)
    out = {}
    for kind in kinds:
        g, am = window_arrivals(sym, days, dt_ms, kind)
        pp, pm, p11 = am.filled()
        tb = BM.Tables(pp, pm, p11, g.Gamma)
        cat = BM.backward(tb, BM._mom(mp), BM._mom(mm), N, lam)
        meta = dict(sym=sym, test_day=test_day, dt_ms=dt_ms, g=kind, window=days, lam_usdt=lam_usdt, lam_tick=lam, N=N,
                    deterministic=deterministic, moments=mom, arrivals=am.check_legal(), checks=cat.checks, catalog=cat.meta,
                    n_unseen_filled=int((am.count == 0).sum()))
        np.savez_compressed(os.path.join(od, f"{test_day}_{kind}.npz"), ks=cat._ks_arr, N=N,
                            **{f"row_{k}": v for k, v in cat.rows.items()},
                            pi_plus=pp, pi_minus=pm, pi_11=p11, count=am.count, Gamma=g.Gamma)
        with open(os.path.join(od, f"{test_day}_{kind}.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1, default=float)
        out[kind] = meta
        c = cat.checks
        print(f"{sym} {test_day} dt={dt_ms} {kind}: window {days[0]}..{days[-1]} ({len(days)} d) N={N} rows={cat.meta['n_rows']} store_gap={cat.meta['max_store_gap']:.1e} "
              f"lemma2_viol={c['lemma2_violations']} (floored-eq {c['lemma2_floored_equalities']}) gamma>=0:{c['gamma_nonneg']} A1>=0:{c['A1_nonneg']} "
              f"transcr_diff={c['max_transcription_diff']:.2e} unseen={meta['n_unseen_filled']} floored={tb.n_floored}", flush=True)
    return out


def load_catalog(path):
    z = np.load(path)
    N = int(z["N"])
    cat = BM.Catalog(N, len(z["pi_plus"]), {})
    cat._ks_arr = z["ks"]
    cat.rows = {k[4:]: z[k] for k in z.files if k.startswith("row_")}
    return cat, dict(pi_plus=z["pi_plus"], pi_minus=z["pi_minus"], pi_11=z["pi_11"], count=z["count"], Gamma=z["Gamma"])


if __name__ == "__main__":
    sym, test_day = sys.argv[1], sys.argv[2]
    dt_ms = int(sys.argv[3]) if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else 1000
    kinds = tuple(sys.argv[sys.argv.index("--g") + 1].split(",")) if "--g" in sys.argv else ("g1", "g2", "g3")
    tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else "base"
    build(sym, test_day, dt_ms, kinds, tag, deterministic="--det" in sys.argv)
