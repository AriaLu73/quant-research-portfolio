#!/usr/bin/env python3
"""research3:把 MM-UH-FV2 移植到另一个 USDC 合约所需的全部合约相关量(9 月 8 个训练日全天),方法与 BTC 相同:
  被挑损失表 R(d)(research5/uh2b_prep.loss_increments,反应时间 1.8 ms)、USDT 波动先验(hedge_sig)、基差波动先验(sk_sb)、
  √B = 4 clip × σ_ref(用户确认的风险预算口径)、行情中断阈值(每小时超过一次的间隔,research5/stale_study.gap_threshold)、
  深度与到达率先验 + γ(s1)(uh_fv_priors_sym.py 的口径)。处置成本先验用 BTC 9 月值且权重极小(0.523, n0 0.0438),由在线估计接管。
用法:Python314/python.exe -X utf8 scripts/research3/uh_fv_prep_sym.py ETH ETHUSDCM ETHUSDTM <clip_usd>
输出 data/research3/uh_val/params_FV2_<SYM>.json 与 pick_<SYM>.json(损失表,需嵌入策略文件)。"""
import json, math, os, subprocess, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research5"))
import uh2b_prep as U2
import stale_study as SS
EV = os.path.join(ROOT, "data", "research2", "events")
SPECS = json.load(open(os.path.join(ROOT, "data", "research2", "kc_contract_specs.json")))
DAYS = ["20260901", "20260902", "20260903", "20260910", "20260911", "20260914", "20260917", "20260918"]
sym, usdc, usdt, clip = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
tc, ta = float(SPECS[usdc]["tick"]), float(SPECS[usdt]["tick"])
at = lambda ts, v, t: v[np.clip(np.searchsorted(ts, t, "right") - 1, 0, len(v) - 1)]
tabs, sig_d, sb_d, sig_var, sb_var, gaps, secs_tot = [], [], [], [], [], [], 0.0
for d in DAYS:
    a = pd.read_parquet(os.path.join(EV, f"book_{usdt}_{d}.parquet"), columns=["ts", "bb", "ba"]); u = pd.read_parquet(os.path.join(EV, f"book_{usdc}_{d}.parquet"), columns=["ts", "bb", "ba"])
    ok = ((a.bb > 0) & (a.ba > a.bb)).to_numpy(); ats = a.ts.to_numpy().astype(np.int64)[ok]; am = ((a.bb.to_numpy() + a.ba.to_numpy()) / 2.0 * ta)[ok]
    ch = np.r_[True, np.diff(am) != 0]; secs = (ats[-1] - ats[0]) / 1e6
    dn, up = U2.loss_increments(ats[ch], am[ch], 1800, U2.GRID); tabs.append((dn + up) / 2 / secs)
    g = np.arange(max(ats[0], u.ts.iloc[0]) + 1_000_000, min(ats[-1], u.ts.iloc[-1]), 1_000_000)
    A = at(ats, am, g); x = np.abs(np.diff(np.log(A))) * 1e4; sig_d.append(x.mean()); sig_var.append(x.var())
    uts = u.ts.to_numpy().astype(np.int64); um = (u.bb.to_numpy() + u.ba.to_numpy()) / 2.0 * tc
    z = (at(uts, um, g) / A - 1.0) * 1e4; y = np.abs(np.diff(z)); sb_d.append(y.mean()); sb_var.append(y.var())
    gaps.append(np.diff(ats) / 1e6); secs_tot += secs
    print(d, f"sigma_h {x.mean() * math.sqrt(math.pi / 2):.3f}  sb {y.mean():.3f}  R(1) {tabs[-1][20]:.5f}", flush=True)
sig_m0, sb_m0 = float(np.mean(sig_d)), float(np.mean(sb_d))
sig_n0 = float(np.mean(sig_var) / max(np.var(sig_d, ddof=1), 1e-12)); sb_n0 = float(np.mean(sb_var) / max(np.var(sb_d, ddof=1), 1e-12))
stale = SS.gap_threshold(np.concatenate(gaps), secs_tot, 24.0)
sigma_ref = sig_m0 * math.sqrt(math.pi / 2); sig_b = sb_m0 * math.sqrt(math.pi / 2)
json.dump(dict(sym=sym, tau_s=0.0018, sigma_ref=sigma_ref, step_bp=0.05, rate=[float(f"{v:.4g}") for v in np.mean(tabs, axis=0)]), open(os.path.join(ROOT, "data", "research3", "uh_val", f"pick_{sym}.json"), "w"))
r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "research3", "uh_fv_priors_sym.py"), usdc, usdt, str(sb_m0)], capture_output=True, text=True, encoding="utf-8")
print(r.stdout[-900:], r.stderr[-300:])
f = json.load(open(os.path.join(ROOT, "data", "research3", "uh_val", f"fv_priors_{usdc}.json")))
mc, ma = float(SPECS[usdc]["mult"]), float(SPECS[usdt]["mult"])
P = dict(symbols=f"{sym}-USDC", anchor_symbol=f"{sym}-USDT", tick_size=SPECS[usdc]["tick"], lot_size=repr(mc).rstrip("0").rstrip(".") if mc < 1 else str(int(mc)),
         hedge_lot=repr(ma).rstrip("0").rstrip(".") if ma < 1 else str(int(ma)), hedge_tick=SPECS[usdt]["tick"], clip_usd=clip,
         fl_k_alpha0=f["fl_k_alpha0"], fl_k_beta0=f["fl_k_beta0"], sk_A_alpha0=f["sk_A_alpha0"], sk_A_beta0=f["sk_A_beta0"], sk_gamma=f["sk_gamma_s1"],
         sk_sb_m0=sb_m0, sk_sb_n0=sb_n0, sk_sqrtB=4.0 * sig_b, fl_c_m0=0.523, fl_c_n0=0.0438, hedge_sig_m0=sig_m0, hedge_sig_n0=sig_n0, anchor_stale_s=round(stale, 2))
json.dump(P, open(os.path.join(ROOT, "data", "research3", "uh_val", f"params_FV2_{sym}.json"), "w"), indent=1)
print(P); print(f"sigma_ref {sigma_ref:.3f} bp/√s;1/k {f['invk_ref']:.2f} bp;A {f['A_ref'] * 3600:.1f}/小时;半点差 {f['half_spread_bp']:.2f} bp;中断阈值 {stale:.2f} s")
