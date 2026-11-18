"""Step 13 —— 为一个 (合约, 测试日, γ, Δt, ē) 组装 P2 控制问题的输入并求解 QVI,存 data/step13/<sym>/dt<ms>/<day>_g<γ>_e<ē>.npz。
输入来源
  随机需求 (c,p) 经验分布:训练窗(step06.training_window,与 Part A 相同的滚动 20 日)各日 step02 的 valid (c,p) 池,每侧抽 N_SAMPLES 对(固定种子,EC-38)。
  到达概率 π(g)、Γ:训练窗 step04 计数相加(与 Part A 相同)。
  点差链:data.yaml 的 train 区间 L3 日(10-01…10-18T04:31)一次性估计(任务书 Step 13.3 "在 train 区间估计";对落在 train 内的测试日为样本内,EC-40);Δt 转移用窗内时均 λ̄(EC-35)。
  费用:taker OUR_FEE 按参考中价(训练窗末日中价中位数)折成 tick/张(EC-30);ε = 0。
  网格:Δy = round(V_LO/3)(EC-42),y_max = Y_MAX_MULT·V_LO(暂定 20,Step 16 校准后复核,EC-31);ē = V_LO(P2 Table 4b:ē = ℓ̄,EC-32)。
用法  python step13_build.py <sym> <V_LO> <test_day> [--gamma 1e-4] [--dt 1000] [--ebar V_LO|0] [--kind g3]
"""
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
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "a"))
sys.path.insert(0, os.path.join(REPRO, "data"))
import arrivals as AR            # noqa: E402
import ladder_store as LS        # noqa: E402
import qvi as Q                  # noqa: E402
import spread_chain as SC        # noqa: E402
import step06_catalog as S6      # noqa: E402

with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as _fh:
    CONTRACTS = yaml.safe_load(_fh)
N_SAMPLES = 48
Y_MAX_MULT = 20
DY_DIV = 3
T_SEG_S = 300
FEE_TAKE = OUR_FEE


def train_interval_days(sym):
    with open(os.path.join(REPRO, "config", "splits", f"{sym}.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cut = cfg["cuts"]["train_validation_utc"][:10].replace("-", "")
    days = sorted({os.path.basename(p)[:8] for p in glob.glob(os.path.join(REPRO, "data", "step01", sym, "202610*.npz"))})
    return [d for d in days if d <= cut]


def spread_chain_for(sym, refit=False):
    p = os.path.join(REPRO, "data", "step13", sym, "spread_chain_train.json")
    if os.path.exists(p) and not refit:
        return SC.SpreadChain.from_json(json.load(open(p, encoding="utf-8")))
    ch = SC.fit(sym, train_interval_days(sym))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(ch.to_json(), open(p, "w", encoding="utf-8"), indent=1)
    return ch


def cp_samples(sym, days, dt_ms, tag="base", n=N_SAMPLES, seed=0):
    rng = np.random.default_rng(seed)
    out = {}
    for col, lab in ((0, "plus"), (1, "minus")):
        cs, ps = [], []
        for d in days:
            z = np.load(os.path.join(REPRO, "data", "step02", sym, tag, f"dt{dt_ms}", f"{d}.npz"))
            v = z["valid"][:, col]
            cs.append(z["c"][v, col]); ps.append(z["p"][v, col])
        c, p = np.concatenate(cs), np.concatenate(ps)
        idx = rng.integers(0, len(c), n)
        out[lab] = (c[idx], p[idx])
        out[lab + "_pool"] = int(len(c))
    return out


def ref_mid_ticks(sym, day):
    files = sorted(glob.glob(os.path.join(REPRO, "data", "step01", sym, f"{day}_*.npz")))
    m = np.concatenate([LS.load(p, keys=("bnd_mid2",))["bnd_mid2"] for p in files])
    return float(np.median(m[m > 0]) / 2.0)


def build(sym, V_LO, test_day, gamma=1e-4, dt_ms=1000, e_bar=None, kind="g3", tag="base", terminal="p2", lam_q=None, save=True, rebate_bp=0.0, store_phi=True, q_clip=True):
    c = CONTRACTS[sym]
    days = S6.training_window(sym, test_day, dt_ms, tag)
    samp = cp_samples(sym, days, dt_ms, tag)
    g, am = S6.window_arrivals(sym, days, dt_ms, kind)
    pp, pm, p11 = am.filled()
    ch = spread_chain_for(sym)
    lam_bar = float(np.nanmean(ch.lam_hourly))
    P = SC.expm(lam_bar * (ch.rho - np.eye(ch.m)) * dt_ms / 1000.0)
    mid_ref = ref_mid_ticks(sym, days[-1])
    fee_ticks = FEE_TAKE * mid_ref
    e_bar = V_LO if e_bar is None else e_bar
    dy = max(1, int(round(V_LO / DY_DIV)))
    rebate_ticks = rebate_bp * 1e-4 * mid_ref                    # Step 15:maker 返佣(负费率的绝对值,bp)→ tick/张
    q = Q.QVI(V_LO=V_LO, dy=dy, y_max=Y_MAX_MULT * V_LO, chain_P=P, spread_rep=ch.rep, pp=pp, pm=pm, p11=p11, Gamma=g.Gamma,
              cp_plus=samp["plus"], cp_minus=samp["minus"], gamma=gamma, dt_ms=dt_ms, e_bar=e_bar, fee_take_ticks=fee_ticks,
              terminal=terminal, lam_quadratic=lam_q, rebate_ticks=rebate_ticks, q_clip=q_clip)
    n_steps = int(round(T_SEG_S * 1000 / dt_ms))
    q.backward(n_steps, store_phi=store_phi)                 # Step 12 的 Δt 敏感性不存 φ(100 ms 时 φ 有 1.4 GB;查表策略只用 pol)
    meta = dict(sym=sym, test_day=test_day, gamma=gamma, dt_ms=dt_ms, e_bar=e_bar, kind=kind, window=days, n_samples=N_SAMPLES, V_LO=V_LO,
                pool=dict(plus=samp["plus_pool"], minus=samp["minus_pool"]), spread_chain=dict(m=ch.m, rep=ch.rep.tolist(), lam_bar=lam_bar, edges=ch.edges.tolist()),
                mid_ref_ticks=mid_ref, fee_take_ticks=fee_ticks, dy=dy, y_max=Y_MAX_MULT * V_LO, n_steps=n_steps, L_grid=q.L.tolist(),
                n_unseen=int((am.count == 0).sum()), terminal=terminal, rebate_bp=rebate_bp, rebate_ticks=rebate_ticks)
    if save:
        od = os.path.join(REPRO, "data", "step13", sym, f"dt{dt_ms}")
        os.makedirs(od, exist_ok=True)
        name = f"{test_day}_g{gamma:g}_e{e_bar:g}" + ("" if terminal == "p2" else "_quad") + (f"_reb{rebate_bp:g}" if rebate_bp else "")
        np.savez_compressed(os.path.join(od, name + ".npz"), **({"phi": q.phi.astype(np.float32)} if q.phi is not None else {}), Lp=q.pol["Lp"], Lm=q.pol["Lm"], e=q.pol["e"],
                            y=q.y, L=q.L, srep=q.srep, P=q.P, pp=pp, pm=pm, p11=p11, Gamma=g.Gamma,
                            cpp_c=samp["plus"][0], cpp_p=samp["plus"][1], cpm_c=samp["minus"][0], cpm_p=samp["minus"][1],
                            edges=ch.edges, meta=np.bytes_(json.dumps(meta, default=float).encode()))
    sh = float((q.pol["e"] != 0).mean())
    print(f"{sym} {test_day} dt={dt_ms} γ={gamma:g} ē={e_bar:g}: Y={q.Y} S={q.S} G={q.G} steps={n_steps} fee={fee_ticks:.1f} tick/张 "
          f"吃单区占比(全时段)={sh:.3f} 近 T(k=n−1)={float((q.pol['e'][-1] != 0).mean()):.3f} 远 T(k=0)={float((q.pol['e'][0] != 0).mean()):.3f} "
          f"L+@y=0,s=2,g=mode: {q.L[q.pol['Lp'][0, q.Y // 2, min(2, q.S - 1), int(np.argmax(am.count))]]}", flush=True)
    return q, meta


def load(path):
    z = np.load(path)
    meta = json.loads(bytes(z["meta"]).decode())
    q = Q.QVI.__new__(Q.QVI)
    q.y, q.L, q.srep, q.P = z["y"], z["L"], z["srep"], z["P"]
    q.Y, q.nL, q.S = len(q.y), len(q.L), len(q.srep)
    q.dy = float(q.y[1] - q.y[0])
    q.pp, q.pm, q.p11, q.Gam = z["pp"], z["pm"], z["p11"], z["Gamma"]
    q.G = len(q.pp)
    q.Pev = np.stack([1 - q.pp - q.pm + q.p11, q.pp - q.p11, q.pm - q.p11, q.p11])
    q.gsucc = np.stack([q.Gam[0, 0], q.Gam[1, 0], q.Gam[0, 1], q.Gam[1, 1]])
    q.gamma, q.dt = meta["gamma"], meta["dt_ms"] / 1000.0
    q.fee, q.V_LO = meta["fee_take_ticks"], float(meta.get("V_LO", 0) or 0)
    cpp, cpm = (z["cpp_c"], z["cpp_p"]), (z["cpm_c"], z["cpm_p"])
    q.Qp = np.minimum(np.maximum(cpp[0][None, :] * (cpp[1][None, :] - q.L[:, None]), 0.0), max(q.V_LO, 1e9) if q.V_LO == 0 else q.V_LO)
    q.Qm = np.minimum(np.maximum(cpm[0][None, :] * (cpm[1][None, :] - q.L[:, None]), 0.0), max(q.V_LO, 1e9) if q.V_LO == 0 else q.V_LO)
    q.rebate = float(meta.get("rebate_ticks", 0.0))
    Lr = q.L + q.rebate
    q.Rp, q.Rm = (Lr[:, None] * q.Qp).mean(1), (Lr[:, None] * q.Qm).mean(1)
    rng = np.random.default_rng(0)
    jp, jm = rng.integers(0, len(cpp[0]), 8), rng.integers(0, len(cpm[0]), 8)
    q.Qp_j, q.Qm_j = q.Qp[:, jp], q.Qm[:, jm]
    q.R11 = (Lr[:, None, None] * q.Qp_j[:, None, :] + Lr[None, :, None] * q.Qm_j[None, :, :]).mean(2)
    ne = int(np.floor(meta["e_bar"] / q.dy + 1e-9))
    q.e_steps = np.array([k for k in range(-ne, ne + 1) if k != 0], int)
    q.phi = z["phi"].astype(float) if "phi" in z.files else None     # 无 φ 的目录只能查表(P2Policy 鞅版),不能 decide(漂移版)
    q.pol = dict(Lp=z["Lp"], Lm=z["Lm"], e=z["e"])
    q.edges = z["edges"]
    return q, meta


if __name__ == "__main__":
    sym, V_LO, day = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    arg = lambda f, d: sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d
    eb = arg("--ebar", None)
    build(sym, V_LO, day, gamma=float(arg("--gamma", "1e-4")), dt_ms=int(arg("--dt", "1000")), e_bar=None if eb is None else float(eb), kind=arg("--kind", "g3"))
