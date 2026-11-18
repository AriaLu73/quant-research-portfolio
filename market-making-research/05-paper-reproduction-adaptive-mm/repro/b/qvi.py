"""Step 13 —— P2 Eq. (3.5) 的拟变分不等式,mean 判据 U(x)=x、g(y)=y²,离散时间;执行模型换成 P1 的随机需求 + 自适应到达概率(任务书 Part B)。

约化(P2 Eq. 3.8)  v = x + y·p + φ(t_k, y, s, g)。单位:φ 为 tick×张;y 张;L、点差、费用均为 tick。
一步(先脉冲后挂单,EC-39)
  V_make(y,s,g;L⁺,L⁻) = Σ_{s'} P_s[s,s'] Σ_{(i,j)} P_{ij}(g) E_{(c,p)}[ φ_{k+1}(y − i·Q⁺ + j·Q⁻, s', Γ(i,j,g)) + i·L⁺Q⁺ + j·L⁻Q⁻ ] − γ y² Δt
       Q^± = min(max(c^±(p^± − L^±), 0), V_LO)(P1 需求,非负、以订单量封顶,EC-37);(c,p) 用训练窗经验分布的 N 个样本对(EC-38)
  φ_k(y,s,g) = max( V_make*(y,s,g), max_{e≠0} [ V_make*(y+e, s, g) − c(e,s) ] ),  c(e,s) = |e|·s̄/2 + f_take·|e|(比例 taker 费按参考中价折成 tick/张,EC-30;ε = 0)
终端  φ_N(y,s,g) = −|y|·s̄/2 − f_take·|y|(P2 的 L(x,y,p,s) = x + yp − |y|s/2 − ε,加比例费)
网格  y ∈ {−J·Δy, …, J·Δy};L ∈ L_GRID(tick);e ∈ Δy·{−ē/Δy … ē/Δy}。y 出界按最近网格点(P2 的 y_min/y_max 只是数值截断)。
在线决策  decide(k, y, s, g, Δ̂):用存储的 φ_{k+1} 对当前点重做一步最大化;Δ̂ ≠ 0 时按 P2 §3.3 第 2 情形把 y'·Δ̂·Δt 加进期望(Step 7 的一步预测)。
"""
import numpy as np

L_GRID = np.array([0.5, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377], float)   # EC-34:斐波那契间距的报价距离网格(tick),覆盖到 9 月 p̂ 的量级


class QVI:
    def __init__(self, V_LO, dy, y_max, chain_P, spread_rep, pp, pm, p11, Gamma, cp_plus, cp_minus, gamma, dt_ms, e_bar, fee_take_ticks,
                 L_grid=L_GRID, n_joint=8, seed=0, terminal="p2", lam_quadratic=None, rebate_ticks=0.0, q_clip=True):
        self.V_LO, self.dy = float(V_LO), float(dy)
        J = int(np.ceil(y_max / dy))
        self.y = np.arange(-J, J + 1) * dy                      # Y
        self.Y = len(self.y)
        self.P = np.asarray(chain_P)                            # S×S,一步点差转移
        self.srep = np.asarray(spread_rep, float)               # S
        self.S = len(self.srep)
        self.pp, self.pm, self.p11 = np.asarray(pp), np.asarray(pm), np.asarray(p11)
        self.G = len(self.pp)
        self.Gam = np.asarray(Gamma)                            # [2,2,G]
        self.Pev = np.stack([1 - self.pp - self.pm + self.p11, self.pp - self.p11, self.pm - self.p11, self.p11])   # [4,G]: 00,10,01,11
        self.gsucc = np.stack([self.Gam[0, 0], self.Gam[1, 0], self.Gam[0, 1], self.Gam[1, 1]])                   # [4,G]
        self.gamma, self.dt = float(gamma), dt_ms / 1000.0
        self.fee = float(fee_take_ticks)
        self.L = np.asarray(L_grid, float)
        self.nL = len(self.L)
        rng = np.random.default_rng(seed)
        self.cpp = cp_plus                                      # (c[N], p[N])
        self.cpm = cp_minus
        N = len(cp_plus[0])
        self.q_clip = q_clip
        if q_clip:                                                # EC-37:Q 非负、以 V_LO 封顶
            self.Qp = np.minimum(np.maximum(cp_plus[0][None, :] * (cp_plus[1][None, :] - self.L[:, None]), 0.0), self.V_LO)    # [nL, N]
            self.Qm = np.minimum(np.maximum(cp_minus[0][None, :] * (cp_minus[1][None, :] - self.L[:, None]), 0.0), self.V_LO)
        else:                                                     # P1 字面:Q = c(p − L),可为负(Remark 1.3),无封顶;只用于 Step 13.8 对拍
            self.Qp = cp_plus[0][None, :] * (cp_plus[1][None, :] - self.L[:, None])
            self.Qm = cp_minus[0][None, :] * (cp_minus[1][None, :] - self.L[:, None])
        # Step 15 / EC-45:maker 返佣 r(tick/张,比例费按参考中价折算)进入挂单收入:(L + r)·Q;等价于 P1 需求里 p 平移 r 而 c 不变(推导见 step15 报告)
        self.rebate = float(rebate_ticks)
        Lr = self.L + self.rebate
        self.Rp = (Lr[:, None] * self.Qp).mean(1)               # [nL]  E[(L + r) Q]
        self.Rm = (Lr[:, None] * self.Qm).mean(1)
        jp, jm = rng.integers(0, N, n_joint), rng.integers(0, len(cp_minus[0]), n_joint)
        self.Qp_j, self.Qm_j = self.Qp[:, jp], self.Qm[:, jm]  # [nL, n_joint]
        self.R11 = (Lr[:, None, None] * self.Qp_j[:, None, :] + Lr[None, :, None] * self.Qm_j[None, :, :]).mean(2)   # [nL, nL]
        ne = int(np.floor(e_bar / dy + 1e-9))
        self.e_steps = np.array([k for k in range(-ne, ne + 1) if k != 0], int)
        self.terminal, self.lam_q = terminal, lam_quadratic
        self.phi = None            # [n+1, Y, S, G]
        self.pol = None            # dict of int arrays [n, Y, S, G]: Lp_idx, Lm_idx, e_steps

    # ---- 插值工具:φ[Y,S,G] 在 y' 上的线性插值(y' 任意形状)→ [..., S, G]
    def _interp(self, phi, yq):
        pos = np.clip((yq + self.y[-1]) / self.dy, 0, self.Y - 1 - 1e-9)
        lo = np.floor(pos).astype(int)
        w = (pos - lo)[..., None, None]
        return phi[lo] * (1 - w) + phi[lo + 1] * w

    def _succ_tables(self, phi_next):
        """对每类到达事件 ev ∈ {00,10,01,11}:后继 g' = Γ_ev(g) 只取少数不同值(g3 下各 27 个),
        先对下一点差 s' 取期望 φ̃_ev = P·φ_next[:, :, cols_ev](期望与 y 插值都是线性的,可交换),再只对这些列插值。"""
        out = []
        for ev in range(4):
            cols, inv = np.unique(self.gsucc[ev], return_inverse=True)
            phit = np.einsum("ij,yjg->yig", self.P, phi_next[:, :, cols])     # [Y,S,|cols|]
            out.append((phit, inv))
        return out

    def _vmake(self, phi_next):
        """V_make[Y, nL, nL, S, G](已含 −γy²Δt)。"""
        (p00, i00), (p10, i10), (p01, i01), (p11, i11) = self._succ_tables(phi_next)
        Fp = np.stack([self._interp(p10, self.y[:, None] - self.Qp[a][None, :]).mean(1) for a in range(self.nL)], axis=1)    # [Y,nL,S,c10]
        Fm = np.stack([self._interp(p01, self.y[:, None] + self.Qm[b][None, :]).mean(1) for b in range(self.nL)], axis=1)    # [Y,nL,S,c01]
        F11 = np.empty((self.Y, self.nL, self.nL, self.S, p11.shape[2]))
        for a in range(self.nL):
            for b in range(self.nL):
                F11[:, a, b] = self._interp(p11, self.y[:, None] - self.Qp_j[a][None, :] + self.Qm_j[b][None, :]).mean(1)
        Pe = self.Pev[:, None, None, None, None, :]                            # [4,1,1,1,1,G]
        V = (Pe[0] * p00[:, :, i00][:, None, None, :, :]
             + Pe[1] * (Fp[:, :, :, i10] + self.Rp[None, :, None, None])[:, :, None, :, :]
             + Pe[2] * (Fm[:, :, :, i01] + self.Rm[None, :, None, None])[:, None, :, :, :]
             + Pe[3] * (F11[:, :, :, :, i11] + self.R11[None, :, :, None, None]))
        V -= (self.gamma * self.y ** 2 * self.dt)[:, None, None, None, None]
        return V

    def _impulse(self, Vm):
        """φ = max(Vm, max_e Vm(y+e) − c(e,s));返回 φ[Y,S,G], e_step[Y,S,G](0 = 不吃单)。"""
        best, ebest = Vm.copy(), np.zeros(Vm.shape, np.int16)
        for k in self.e_steps:
            cand = np.full_like(Vm, -np.inf)
            e = abs(k) * self.dy
            cost = (e * self.srep / 2 + self.fee * e)[None, :, None]      # [1,S,1]
            if k > 0:
                cand[:-k] = Vm[k:] - cost
            else:
                cand[-k:] = Vm[:k] - cost
            better = cand > best + 1e-9
            best = np.where(better, cand, best)
            ebest = np.where(better, k, ebest)
        return best, ebest

    def terminal_phi(self):
        if self.terminal == "quadratic":                          # 对拍 P1 用:α_T = −λ(tick×张 / 张²)
            return np.broadcast_to((-self.lam_q * self.y ** 2)[:, None, None], (self.Y, self.S, self.G)).copy()
        return np.broadcast_to((-np.abs(self.y)[:, None] * (self.srep[None, :] / 2 + self.fee))[:, :, None], (self.Y, self.S, self.G)).copy()

    def backward(self, n_steps, store_phi=True):
        phi = self.terminal_phi()
        self.phi = np.empty((n_steps + 1, self.Y, self.S, self.G)) if store_phi else None
        if store_phi:
            self.phi[n_steps] = phi
        self.pol = dict(Lp=np.zeros((n_steps, self.Y, self.S, self.G), np.int8), Lm=np.zeros((n_steps, self.Y, self.S, self.G), np.int8),
                        e=np.zeros((n_steps, self.Y, self.S, self.G), np.int16))
        for k in range(n_steps - 1, -1, -1):
            V = self._vmake(phi)                                  # [Y,nL,nL,S,G]
            Vflat = V.reshape(self.Y, self.nL * self.nL, self.S, self.G)
            arg = Vflat.argmax(1)                                 # [Y,S,G]
            Vm = np.take_along_axis(Vflat, arg[:, None], 1)[:, 0]
            self.pol["Lp"][k], self.pol["Lm"][k] = (arg // self.nL).astype(np.int8), (arg % self.nL).astype(np.int8)
            phi, e = self._impulse(Vm)
            self.pol["e"][k] = e
            if store_phi:
                self.phi[k] = phi
        return self

    # ---- 在线决策(含可选漂移 Δ̂,tick / 步)
    def decide(self, k, y, s, g, delta_hat=0.0):
        """返回 (L⁺, L⁻, e):先决定市价单 e(张,Δy 的整数倍),再在 y+e 上决定挂单距离。全部用 φ_{k+1} 现算(与离线表一致;Δ̂≠0 时加漂移项)。"""
        phi_next = self.phi[k + 1]
        succ = self.gsucc[:, g]
        Pe = self.Pev[:, g]
        P_s = self.P[s]

        def vmake_at(yv):
            # 对单点 y 的 V_make[nL,nL]
            def E(yq, gi):                                        # yq: [..] → Σ_{s'} P_s[s'] φ(yq, s', gi)
                v = self._interp(phi_next, yq)[..., :, gi]        # [..., S]
                return v @ P_s
            v00 = E(np.array([yv]), succ[0])[0]
            vp = np.array([E(yv - self.Qp[a], succ[1]).mean() + self.Rp[a] for a in range(self.nL)])
            vm = np.array([E(yv + self.Qm[b], succ[2]).mean() + self.Rm[b] for b in range(self.nL)])
            v11 = np.array([[E(yv - self.Qp_j[a] + self.Qm_j[b], succ[3]).mean() + self.R11[a, b] for b in range(self.nL)] for a in range(self.nL)])
            V = Pe[0] * v00 + Pe[1] * vp[:, None] + Pe[2] * vm[None, :] + Pe[3] * v11 - self.gamma * yv ** 2 * self.dt
            if delta_hat:
                # 漂移:E[y'] Δ̂ Δt,y' = yv − i Q⁺ + j Q⁻(每步 Δ̂ 以 tick/步 计,Δt 已含在 Δ̂ 的定义里:Δ̂ = E[S_{k+1} − S_k])
                EQp, EQm = self.Qp.mean(1), self.Qm.mean(1)
                Ey = yv - (Pe[1] + Pe[3]) * EQp[:, None] + (Pe[2] + Pe[3]) * EQm[None, :]
                V = V + Ey * delta_hat
            return V

        V0 = vmake_at(y)
        best = V0.max()
        ebest = 0
        for kstep in self.e_steps:
            e = kstep * self.dy
            y2 = y + e
            if abs(y2) > self.y[-1]:
                continue
            cand = vmake_at(y2).max() - (abs(e) * self.srep[s] / 2 + self.fee * abs(e))
            if cand > best + 1e-9:
                best, ebest = cand, kstep
        V = vmake_at(y + ebest * self.dy) if ebest else V0
        a, b = np.unravel_index(V.argmax(), V.shape)
        return float(self.L[a]), float(self.L[b]), ebest * self.dy

    def regions(self, k):
        """Figure 3 型:每个 (y, s) 在 g 上多数的区:0 = 挂单区 M,+1 = 买入吃单,−1 = 卖出吃单。"""
        e = self.pol["e"][k]
        return np.sign(np.median(e, axis=2))
