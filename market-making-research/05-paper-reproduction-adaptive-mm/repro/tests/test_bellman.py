r"""Step 5 数学单测(任务书 Step 5):
(1) Lemma 2:α⁰_{k+1} < α_k < 0 对全部 k、s;(2) (A.12):γ < 0;(3) ⁽¹⁾A^± < 0;
(4) 短期限暴力数值优化 (A.5) 的二次型,与解析报价 (18)/(22) 一致(scipy 与 2×2 线性解两种);
(5) (19)–(21) 转录式与"代回 (A.5) 比较系数"的精确值一致;(6) 价格有效性规则与取整。
随机到达表 + 随机矩(满足 μ_c2 ≥ μ_c²、μ_c2p2 ≥ 0)。"""
import os
import sys

import numpy as np
from scipy.optimize import minimize

REPRO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPRO, "a"))
import arrivals as AR     # noqa: E402
import bellman as BM      # noqa: E402


def random_setup(seed, kind="g2"):
    rng = np.random.default_rng(seed)
    g = AR.GState(kind)
    pp = rng.uniform(0.05, 0.6, g.n_states)
    pm = rng.uniform(0.05, 0.6, g.n_states)
    p11 = rng.uniform(0, 1, g.n_states) * np.minimum(pp, pm) * 0.8
    tb = BM.Tables(pp, pm, p11, g.Gamma)

    def mom():
        c, p = rng.uniform(0.2, 3), rng.uniform(2, 30)
        cv, corr = rng.uniform(0.3, 1.5), rng.uniform(-0.3, 0.5)
        sc, sp = cv * c, 0.5 * p
        mu_c2 = c * c + sc * sc
        mu_cp = c * p + corr * sc * sp
        mu_c2p = mu_c2 * p + 2 * c * corr * sc * sp          # 近似三阶矩(只需数值合理)
        mu_c2p2 = mu_c2 * (p * p + sp * sp) + 4 * c * p * corr * sc * sp
        return dict(mu_c=c, mu_p=p, mu_cp=mu_cp, mu_c2=mu_c2, mu_c2p=mu_c2p, mu_c2p2=mu_c2p2)
    return tb, BM._mom(mom()), BM._mom(mom()), g


def test_lemma2_gamma_A1_and_transcription():
    for seed in range(6):
        tb, mp, mm, g = random_setup(seed)
        cat = BM.backward(tb, mp, mm, N=400, lam=0.0005 * (seed + 1), store_all=True)
        c = cat.checks
        assert c["lemma2_violations"] == 0, c
        assert c["gamma_nonneg"] == 0 and c["A1_nonneg"] == 0, c
        assert c["max_transcription_diff"] < 1e-7, c


def test_bruteforce_optimality():
    tb, mp, mm, g = random_setup(11)
    cat = BM.backward(tb, mp, mm, N=30, lam=0.001, store_all=True)
    rng = np.random.default_rng(3)
    for k in (30, 20, 5, 0):
        a_next, h_next, g_next = cat.get("alpha", k + 1), cat.get("h", k + 1), cat.get("g", k + 1)
        a0, a1p, a1m, a11 = tb.lookahead(a_next)
        h0, h1p, h1m, _ = tb.lookahead(h_next)
        g0, _, _, _ = tb.lookahead(g_next)
        for s in rng.integers(0, tb.S, 5):
            I = float(rng.integers(-50, 50))
            a_p, a_m, x, b_p, b_m, c0 = (v[s] if np.ndim(v) else v for v in BM.quad_objective(tb, a0, a1p, a1m, a11, h0, h1p, h1m, g0, mp, mm, I))
            f = lambda L: -(a_p * L[0] ** 2 + a_m * L[1] ** 2 + x * L[0] * L[1] + b_p * L[0] + b_m * L[1] + c0)
            res = minimize(f, x0=np.zeros(2), method="BFGS", options=dict(gtol=1e-10))
            Lp, Lm = BM.optimal_L(cat, k, int(s), I)
            assert np.allclose(res.x, [Lp, Lm], rtol=1e-4, atol=1e-4), (k, s, res.x, Lp, Lm)    # BFGS 数值精度 ~1e-5 相对
            assert -res.fun <= f([Lp, Lm]) * -1 + 1e-9 * max(1, abs(res.fun))                     # 解析解的目标值不低于数值解
            Lp2, Lm2, D = BM.quad_argmax(a_p, a_m, x, b_p, b_m)
            assert D > 0 and a_p < 0 and a_m < 0                     # 负定 → 全局最大
            assert np.allclose([Lp2, Lm2], [Lp, Lm], atol=1e-9)      # 驻点(精确线性解)与 (18) 一致
            # α, h, g 的二次式:J*(I) = α I² + h I + g
            Jstar = -res.fun
            al, hh, gg = cat.get("alpha", k)[s], cat.get("h", k)[s], cat.get("g", k)[s]
            assert abs(Jstar - (al * I * I + hh * I + gg)) < 1e-6 * max(1, abs(Jstar))


def test_inventory_direction_and_state_dependence():
    tb, mp, mm, g = random_setup(5, "g3")
    cat = BM.backward(tb, mp, mm, N=200, lam=0.01, store_all=True)
    k = 190
    s = 0
    Lp0, Lm0 = BM.optimal_L(cat, k, s, 0.0)
    Lp1, Lm1 = BM.optimal_L(cat, k, s, 20.0)
    assert Lp1 < Lp0 and Lm1 > Lm0                      # 多头库存:卖单靠近中价、买单远离(Corollary 3 后第 1 条)
    Ls = {ss: BM.optimal_L(cat, k, ss, 0.0) for ss in range(tb.S)}
    assert len({round(v[0], 9) for v in Ls.values()}) > 1   # 不同状态报价不同


def test_quote_rules():
    assert BM.to_quotes(2001, 1.6, 2.4) == (998, 1002, 0)         # mid 1000.5:ask 1002.1→1002,bid 998.1→998
    bt, at, flag = BM.to_quotes(2001, -0.7, 1.0)                  # ask 低于中价 → 中价上方紧邻 tick
    assert at == 1001 and flag & 2
    bt, at, flag = BM.to_quotes(2000, 0.2, 0.2)                   # a=1000.2,b=999.8 → 取整后会相等;规则:≥ up / ≤ dn
    assert at == 1001 and bt == 999
    bt, at, flag = BM.to_quotes(2000, -3.0, -1.0)                 # a<b 且越过中价
    assert at == 1001 and bt == 999 and flag & 1


if __name__ == "__main__":
    for f in (test_lemma2_gamma_A1_and_transcription, test_bruteforce_optimality, test_inventory_direction_and_state_dependence, test_quote_rules):
        f()
        print("ok", f.__name__)
