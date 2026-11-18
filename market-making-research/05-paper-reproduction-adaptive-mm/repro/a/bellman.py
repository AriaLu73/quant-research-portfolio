"""Step 5–6 —— P1 Eq. (10)–(22)、(3)/(43)/(A.6)、Theorem 1、Corollary 3、Lemma 2、(A.5)、(A.12);Section 2.7 的 Policy Catalog。

记号  每个时间步 k 与状态 s(g 的取值)。Λ_k(s) = α_{t_k} 在状态 s 的值;同理 h、g。
一步前瞻(A.6)   α⁰_{k+1}(s)   = Σ_{i,ℓ} α_{k+1}(Γ(i,ℓ,s)) P(i,ℓ|s)
               α^{1+}_{k+1}(s) = Σ_ℓ α_{k+1}(Γ(1,ℓ,s)) P(1,ℓ|s) / π⁺(s),  α^{1−} 对称,  α^{1,1}_{k+1}(s) = α_{k+1}(Γ(1,1,s))
               h⁰、h^{1±} 同法;g⁰ 同法。
系数(17)       ρ^± = π⁺π⁻ μ^±_c (α^{1∓} μ^∓_{c2} − μ^∓_c);ψ^± = π^∓ π(1,1) α^{1,1} μ^±_c (μ^∓_c)²;
               γ = (π(1,1) α^{1,1} μ⁺_c μ⁻_c)² − ρ⁺ρ⁻ / (π⁺π⁻ μ⁺_c μ⁻_c)
报价系数(18)    ⁽¹⁾A^± = (α^{1±}ρ^± − α^{1∓}ψ^±)/γ;⁽²⁾A^± = (h^{1±}ρ^± − h^{1∓}ψ^±)/(2γ);⁽³⁾A^± 见代码
最优距离(22)    L⁺* = ⁽¹⁾A⁺ I + ⁽²⁾A⁺ + ⁽³⁾A⁺;L⁻* = −⁽¹⁾A⁻ I − ⁽²⁾A⁻ + ⁽³⁾A⁻
递推(19)–(21)   论文的推导方法(附录 A.1):把 L* 代回 (A.5) 的二次型,比较 I²、I、常数项的系数。本实现按这个方法精确求 α、h、g
               (quad_objective + 三点插值),并把 (19)–(21) 的转录式作为对照(transcribed_recursion),单测要求二者一致。
终端(Theorem 1(i))  α_{N+1} = −λ,h_{N+1} = g_{N+1} = 0(对全部状态)。
一般中价(Eq. 31/44)  ã* = S + L⁺* + (ρ⁺−ψ⁺)/(2γ)·Δ̂,b̃* = S − L⁻* + (ρ⁻−ψ⁻)/(2γ)·Δ̂;系数 drift± 预存进 catalog。
单位  L、p 以 tick 计,c 以 张/tick 计,I 以 张 计 → α 的单位 tick/张,与 λ(Part A 用 MSFT 值 0.0005 美元/股²,见 catalog.meta 的换算)一致性由调用方负责。
π 的下限(EC-18)  ρ、(3)A 含 1/π^±;估计为 0 的状态把 π 截到 PI_FLOOR 并计数。
"""
import numpy as np

PI_FLOOR = 1e-6
SIDES = ("plus", "minus")


def _mom(m):
    return dict(c=float(m["mu_c"]), cp=float(m["mu_cp"]), c2=float(m["mu_c2"]), c2p=float(m["mu_c2p"]), c2p2=float(m["mu_c2p2"]))


class Tables:
    """到达概率表 + Γ:pi_plus[S], pi_minus[S], pi_11[S], Gamma[2,2,S]。"""

    def __init__(self, pi_plus, pi_minus, pi_11, Gamma):
        self.pp = np.maximum(np.asarray(pi_plus, float), PI_FLOOR)
        self.pm = np.maximum(np.asarray(pi_minus, float), PI_FLOOR)
        p11 = np.asarray(pi_11, float)
        self.p11 = np.clip(p11, 0.0, np.minimum(self.pp, self.pm))
        self.floored = (np.asarray(pi_plus) < PI_FLOOR) | (np.asarray(pi_minus) < PI_FLOOR)     # 一侧零到达的状态(EC-18/EC-24)
        self.n_floored = int(self.floored.sum())
        self.G = np.asarray(Gamma, np.int64)
        self.S = len(self.pp)
        # 联合律 Eq.(9):P[i, l, s]
        self.P = np.zeros((2, 2, self.S))
        self.P[1, 1] = self.p11
        self.P[1, 0] = self.pp - self.p11
        self.P[0, 1] = self.pm - self.p11
        self.P[0, 0] = 1 - self.pp - self.pm + self.p11

    def lookahead(self, u_next):
        """(A.6):u_next[S] = Λ_{k+1}。返回 u0, u1p, u1m, u11(各 [S])。"""
        U = u_next[self.G]                                   # U[i, l, s] = Λ(Γ(i,l,s))
        u0 = (U * self.P).sum(axis=(0, 1))
        u1p = (U[1, 0] * self.P[1, 0] + U[1, 1] * self.P[1, 1]) / self.pp
        u1m = (U[0, 1] * self.P[0, 1] + U[1, 1] * self.P[1, 1]) / self.pm
        u11 = U[1, 1]
        return u0, u1p, u1m, u11


def coefficients(tb: Tables, a1p, a1m, a11, h1p, h1m, mp, mm):
    """(17)–(18)。全部按状态向量化。返回 dict。"""
    pp, pm, p11 = tb.pp, tb.pm, tb.p11
    rho_p = pp * pm * mp["c"] * (a1m * mm["c2"] - mm["c"])
    rho_m = pp * pm * mm["c"] * (a1p * mp["c2"] - mp["c"])
    psi_p = pm * p11 * a11 * mp["c"] * mm["c"] ** 2
    psi_m = pp * p11 * a11 * mm["c"] * mp["c"] ** 2
    gamma = (p11 * a11 * mp["c"] * mm["c"]) ** 2 - rho_p * rho_m / (pp * pm * mp["c"] * mm["c"])
    A1p = (a1p * rho_p - a1m * psi_p) / gamma
    A1m = (a1m * rho_m - a1p * psi_m) / gamma
    A2p = (h1p * rho_p - h1m * psi_p) / (2 * gamma)
    A2m = (h1m * rho_m - h1p * psi_m) / (2 * gamma)
    A3p = (rho_p / (2 * pp * mp["c"] * gamma)) * (pp * (mp["cp"] - 2 * a1p * mp["c2p"]) + 2 * psi_p * mm["cp"] / (pm * mm["c"] ** 2)) \
        + (psi_p / (2 * pm * mm["c"] * gamma)) * (pm * (mm["cp"] - 2 * a1m * mm["c2p"]) + 2 * psi_m * mp["cp"] / (pp * mp["c"] ** 2))
    A3m = (rho_m / (2 * pm * mm["c"] * gamma)) * (pm * (mm["cp"] - 2 * a1m * mm["c2p"]) + 2 * psi_m * mp["cp"] / (pp * mp["c"] ** 2)) \
        + (psi_m / (2 * pp * mp["c"] * gamma)) * (pp * (mp["cp"] - 2 * a1p * mp["c2p"]) + 2 * psi_p * mm["cp"] / (pm * mm["c"] ** 2))
    return dict(rho_p=rho_p, rho_m=rho_m, psi_p=psi_p, psi_m=psi_m, gamma=gamma, A1p=A1p, A1m=A1m, A2p=A2p, A2m=A2m, A3p=A3p, A3m=A3m,
                drift_p=(rho_p - psi_p) / (2 * gamma), drift_m=(rho_m - psi_m) / (2 * gamma))


def quad_objective(tb: Tables, a0, a1p, a1m, a11, h0, h1p, h1m, g0, mp, mm, I):
    """(A.5) 右端(去掉与左端相消的 I·S 项)作为 (L⁺, L⁻) 的二次型:J = a_p L⁺² + a_m L⁻² + x L⁺L⁻ + b_p L⁺ + b_m L⁻ + c0。
    返回各系数(按状态向量化;I 可以是标量或 [S])。"""
    pp, pm, p11 = tb.pp, tb.pm, tb.p11
    a_p = pp * (a1p * mp["c2"] - mp["c"])
    a_m = pm * (a1m * mm["c2"] - mm["c"])
    x = -2 * a11 * p11 * mp["c"] * mm["c"]
    b_p = pp * (mp["cp"] + h1p * mp["c"] + a1p * (2 * mp["c"] * I - 2 * mp["c2p"])) + 2 * a11 * p11 * mp["c"] * mm["cp"]
    b_m = pm * (mm["cp"] - h1m * mm["c"] + a1m * (-2 * mm["c"] * I - 2 * mm["c2p"])) + 2 * a11 * p11 * mp["cp"] * mm["c"]
    c0 = pp * (a1p * (mp["c2p2"] - 2 * mp["cp"] * I) - h1p * mp["cp"]) + pm * (a1m * (mm["c2p2"] + 2 * mm["cp"] * I) + h1m * mm["cp"]) \
        - 2 * a11 * p11 * mp["cp"] * mm["cp"] + a0 * I ** 2 + h0 * I + g0
    return a_p, a_m, x, b_p, b_m, c0


def quad_argmax(a_p, a_m, x, b_p, b_m):
    """二次型驻点(2×2 线性方程组):2a_p L⁺ + x L⁻ = −b_p;x L⁺ + 2a_m L⁻ = −b_m。"""
    D = 4 * a_p * a_m - x ** 2
    Lp = (-2 * a_m * b_p + x * b_m) / D
    Lm = (-2 * a_p * b_m + x * b_p) / D
    return Lp, Lm, D


def quad_value(a_p, a_m, x, b_p, b_m, c0, Lp, Lm):
    return a_p * Lp ** 2 + a_m * Lm ** 2 + x * Lp * Lm + b_p * Lp + b_m * Lm + c0


def step(tb: Tables, alpha_next, h_next, g_next, mp, mm):
    """一步向后递推:给定 Λ_{k+1}(α, h, g 各 [S]),返回 k 时刻的 α, h, g 与报价系数(全部 [S])。"""
    a0, a1p, a1m, a11 = tb.lookahead(alpha_next)
    h0, h1p, h1m, _ = tb.lookahead(h_next)
    g0, _, _, _ = tb.lookahead(g_next)
    co = coefficients(tb, a1p, a1m, a11, h1p, h1m, mp, mm)
    # α, h, g:最优 L*(I) 代回 (A.5),J*(I) 是 I 的二次式 → 三点精确插值
    vals = []
    for I in (-1.0, 0.0, 1.0):
        a_p, a_m, x, b_p, b_m, c0 = quad_objective(tb, a0, a1p, a1m, a11, h0, h1p, h1m, g0, mp, mm, I)
        Lp = co["A1p"] * I + co["A2p"] + co["A3p"]
        Lm = -co["A1m"] * I - co["A2m"] + co["A3m"]
        vals.append(quad_value(a_p, a_m, x, b_p, b_m, c0, Lp, Lm))
    Jm, J0, Jp = vals
    alpha = (Jp + Jm) / 2 - J0
    h = (Jp - Jm) / 2
    g = J0
    co.update(alpha=alpha, h=h, g=g, a0=a0, a1p=a1p, a1m=a1m, a11=a11, h0=h0, h1p=h1p, h1m=h1m, g0=g0)
    return co


def transcribed_recursion(tb: Tables, co, mp, mm):
    """(19)–(21) 的逐字转录(用于与 step() 的精确值对拍)。δ = +1 (plus) / −1 (minus)。"""
    pp, pm, p11 = tb.pp, tb.pm, tb.p11
    a1, h1, A1, A2, A3, mom, pi = {}, {}, {}, {}, {}, {}, {}
    a1["+"], a1["-"], h1["+"], h1["-"] = co["a1p"], co["a1m"], co["h1p"], co["h1m"]
    A1["+"], A1["-"], A2["+"], A2["-"], A3["+"], A3["-"] = co["A1p"], co["A1m"], co["A2p"], co["A2m"], co["A3p"], co["A3m"]
    mom["+"], mom["-"], pi["+"], pi["-"] = mp, mm, pp, pm
    a11 = co["a11"]
    alpha = co["a0"].copy()
    h = co["h0"].copy()
    g = co["g0"].copy()
    for d, s in (("+", 1.0), ("-", -1.0)):
        m, p, A1d, A2d, A3d, a1d, h1d = mom[d], pi[d], A1[d], A2[d], A3[d], a1[d], h1[d]
        alpha = alpha + p * ((a1d * m["c2"] - m["c"]) * A1d ** 2 + 2 * a1d * m["c"] * A1d)
        h = h + p * (2 * (a1d * m["c2"] - m["c"]) * A1d * (A2d + s * A3d) + 2 * a1d * m["c"] * (s * A3d + A2d) - 2 * (s * a1d) * m["cp"]
                     + (s * A1d) * (m["cp"] + (s * h1d) * m["c"] - 2 * a1d * m["c2p"]))
        g = g + p * ((a1d * m["c2"] - m["c"]) * (A3d + s * A2d) ** 2 + a1d * m["c2p2"] - (s * h1d) * m["cp"]
                     + (m["cp"] + (s * h1d) * m["c"] - 2 * a1d * m["c2p"]) * (A3d + s * A2d))
    cc = 2 * a11 * p11 * mp["c"] * mm["c"]
    alpha = alpha + cc * A1["+"] * A1["-"]
    h = h - cc * (A1["+"] * (A3["-"] - A2["-"]) - A1["-"] * (A2["+"] + A3["+"]) + A1["-"] * mp["cp"] / mp["c"] - A1["+"] * mm["cp"] / mm["c"])
    g = g - cc * ((A2["+"] + A3["+"]) * (A3["-"] - A2["-"]) - (mp["cp"] / mp["c"]) * (A3["-"] - A2["-"]) - (mm["cp"] / mm["c"]) * (A2["+"] + A3["+"])
                  + mp["cp"] * mm["cp"] / (mm["c"] * mp["c"]))
    return alpha, h, g


class Catalog:
    """Policy[k, s]。k = 0..N 为决策时刻;α/h/g 另存(含 k = N+1 终端)。
    存储(EC-19):递推逐步精确算到 k = 0;只在"任一报价系数相对上一存储点变化 > tol_store(1e-3 tick)"或距上一存储点
    已 max_stride 步时保存一行;查表取 ≤ k 的最近存储点(相邻存储点间系数差 < tol_store,对取整到 tick 的报价无影响;
    误差上界写进 meta)。store_all=True 时逐步保存(单测 / 对照用)。"""
    KEYS = ("A1p", "A2p", "A3p", "A1m", "A2m", "A3m", "drift_p", "drift_m", "gamma", "alpha", "h", "g")

    def __init__(self, N, S, meta):
        self.N, self.S, self.meta = N, S, meta
        self.rows = {k: [] for k in self.KEYS}
        self.ks = []                  # 每行对应的 k(递减追加,最后反转为升序)
        self._ks_arr = None

    def _finalize(self):
        order = np.argsort(self.ks)
        self._ks_arr = np.asarray(self.ks)[order]
        for key in self.KEYS:
            self.rows[key] = np.asarray(self.rows[key])[order]

    def get(self, key, k):
        """k 的系数:取存储点中 ≤ k 的最近一个(k = N+1 只对 alpha/h/g 有意义,返回终端行)。"""
        i = int(np.searchsorted(self._ks_arr, k, side="right")) - 1
        return self.rows[key][max(i, 0)]


def backward(tb: Tables, mp, mm, N, lam, tol_store=1e-3, max_stride=1000, store_all=False, checks=True):
    """从 k = N+1 向前递推到 k = 0。返回 Catalog 与检查结果(Lemma 2、(A.12)、⁽¹⁾A± < 0、(19)–(21) 转录对拍)。
    Lemma 2 检查排除 π 被截的状态(那里 α⁰ ≡ α,严格不等号退化为等号),这些状态单独计数。"""
    tb0 = tb(N) if callable(tb) else tb          # tb 可为 callable(k) → Tables:时变、无状态的非自适应 π(实验 B)
    S = tb0.S
    cat = Catalog(N, S, dict(N=N, lam=lam, S=S, n_pi_floored=tb0.n_floored, tol_store=tol_store, max_stride=max_stride))
    alpha = np.full(S, -float(lam))
    h = np.zeros(S)
    g = np.zeros(S)
    term = dict(alpha=alpha.copy(), h=h.copy(), g=g.copy())
    for key in Catalog.KEYS:
        cat.rows[key].append(term.get(key, np.full(S, np.nan)))
    cat.ks.append(N + 1)
    chk = dict(lemma2_violations=0, lemma2_floored_equalities=0, gamma_nonneg=0, A1_nonneg=0, max_transcription_diff=0.0, steps=0,
               max_store_gap=0.0, n_rows=0)
    last = None
    since = 0
    for k in range(N, -1, -1):
        tbk = tb(k) if callable(tb) else tb
        ok = ~tbk.floored
        co = step(tbk, alpha, h, g, mp, mm)
        if checks:
            # Lemma 2 带数值容差(EC-29):α 由 (A.5) 三点插值得到,存在 ~1e-10 的抵消误差;只有 α⁰ 超过 α 的量 > 1e-6·|α| 才算违反
            tol = 1e-6 * np.abs(co["alpha"]) + 1e-12
            l2 = (co["a0"] < co["alpha"] + tol) & (co["alpha"] < 0)
            chk["lemma2_violations"] += int(np.any(~l2[ok]))
            if np.any(~l2[ok]):                                   # 记录违反量级与状态,便于区分数值等号与真违反
                bad = ok & ~l2
                chk["lemma2_max_gap"] = max(chk.get("lemma2_max_gap", 0.0), float(np.max(co["a0"][bad] - co["alpha"][bad])))
                chk["lemma2_max_alpha"] = max(chk.get("lemma2_max_alpha", -np.inf), float(np.max(co["alpha"][bad])))
                chk.setdefault("lemma2_states", set()).update(int(s) for s in np.where(bad)[0])
            chk["lemma2_floored_equalities"] += int(np.any(~l2[~ok]))
            chk["gamma_nonneg"] += int(np.any(co["gamma"] >= 0))
            chk["A1_nonneg"] += int(np.any(co["A1p"][ok] >= 0) or np.any(co["A1m"][ok] >= 0))
            if k % max(N // 50, 1) == 0 or k >= N - 5:
                ta, th, tg = transcribed_recursion(tbk, co, mp, mm)
                chk["max_transcription_diff"] = max(chk["max_transcription_diff"], float(np.max(np.abs(ta - co["alpha"]) + np.abs(th - co["h"]) + np.abs(tg - co["g"]))))
        since += 1
        if last is None:
            diff = np.inf
        else:
            diff = max(float(np.max(np.abs(co[key][ok] - last[key][ok]))) for key in ("A1p", "A2p", "A3p", "A1m", "A2m", "A3m", "drift_p", "drift_m"))
        if store_all or diff > tol_store or since >= max_stride or k == 0:
            for key in Catalog.KEYS:
                cat.rows[key].append(co[key])
            cat.ks.append(k)
            last, since = co, 0
        else:
            chk["max_store_gap"] = max(chk["max_store_gap"], diff)
        alpha, h, g = co["alpha"], co["h"], co["g"]
        chk["steps"] += 1
    cat._finalize()
    chk["n_rows"] = int(len(cat.ks))
    if "lemma2_states" in chk:                       # 可写 json(集合 → 有序列表)
        chk["lemma2_states"] = sorted(chk["lemma2_states"])
    cat.meta.update(n_rows=chk["n_rows"], max_store_gap=chk["max_store_gap"])
    cat.checks = chk
    return cat


def optimal_L(cat: Catalog, k, s, I, delta_hat=0.0):
    """(22) + (31)/(44):返回 (L⁺, L⁻)(tick 距离;L⁻ 为正表示在中价下方)。"""
    A1p, A2p, A3p = cat.get("A1p", k)[s], cat.get("A2p", k)[s], cat.get("A3p", k)[s]
    A1m, A2m, A3m = cat.get("A1m", k)[s], cat.get("A2m", k)[s], cat.get("A3m", k)[s]
    Lp = A1p * I + A2p + A3p
    Lm = -A1m * I - A2m + A3m
    if delta_hat:
        Lp = Lp + cat.get("drift_p", k)[s] * delta_hat          # ã = S + L⁺ + drift⁺·Δ̂
        Lm = Lm - cat.get("drift_m", k)[s] * delta_hat          # b̃ = S − L⁻ + drift⁻·Δ̂  → L⁻ 减小
    return float(Lp), float(Lm)


def to_quotes(mid2, Lp, Lm):
    """价格有效性规则(Section 2.2 Definition 1 之后、3.1.1)+ 取整(EC-20:四舍五入到最近 tick,远离中价方向断平)。
    mid2 = bb + ba(2×中价,整数 tick)。返回 (bid_tick, ask_tick, flag):flag 记录触发了哪条规则。"""
    mid = mid2 / 2.0
    a, b = mid + Lp, mid - Lm
    flag = 0
    if a < b:
        flag |= 1
    if a < mid:
        flag |= 2
    if b > mid:
        flag |= 4
    up = int(np.floor(mid)) + 1          # 中价上方紧邻的 tick
    dn = int(np.ceil(mid)) - 1           # 中价下方紧邻的 tick
    if flag & (1 | 2):
        at = up
    else:
        at = int(np.floor(a + 0.5)) if (a - np.floor(a)) != 0.5 else int(np.ceil(a))
        at = max(at, up)
    if flag & (1 | 4):
        bt = dn
    else:
        bt = int(np.floor(b + 0.5)) if (b - np.floor(b)) != 0.5 else int(np.floor(b))
        bt = min(bt, dn)
    return bt, at, flag
