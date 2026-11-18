"""Step 4 —— P1 Eq. (45)–(47)、Assumption 4 / Eq. (42)、Remark 5:自适应到达概率。

状态函数(Eq. 45)
  g1(e_t) = (I_t^+, I_t^-, I_{t-1}^+, I_{t-1}^-, I_{t-2}^+, I_{t-2}^-)                 64 态,ϖ = 3
  g2(e_t) = (I_t^+ + I_t^-, I_{t-1}^+ + I_{t-1}^-, I_{t-2}^+ + I_{t-2}^-)             27 态,ϖ = 3
  g3(e_t) = (…, 共 4 个滞后的和)                                                      81 态,ϖ = 4
整数编码  g1:bit 2j = I_{t-j}^+, bit 2j+1 = I_{t-j}^-;g2/g3:base-3,位 j = 第 j 个滞后的和(j = 0 最新)。
转移 Γ(Eq. 42)  g1:new = ((s << 2) & 63) | i+ | (i− << 1);g2:new = (i+ + i−) + 3·(s mod 9);g3:new = (i+ + i−) + 3·(s mod 27)。
与 EventFrame 的对应  frame.ind±[k] 是区间 [t_k, t_{k+1}) 的到达指标(论文记号 1^±_{t_{k+1}})。
  决策时刻 t_k 的状态 s_k = g(ind[k-1], ind[k-2], …, ind[k-ϖ]);被预测的目标 y_k^± = ind±[k]。
  每段连续可用区间的最前 ϖ 个区间没有状态(burn-in,EC-07);缺口区间及其后 ϖ 个区间同样无状态(附录第 7 条)。
估计(Eq. 46–47)  π^±(s) = #{y^±=1, s} / #{s},π^{11}(s) = #{y^+=1, y^-=1, s} / #{s};联合律 Eq. (9)。
样本不足的状态  只报告(count、未见状态数),不改论文估计法;策略需要时用无条件频率并标记(EC-17)。
"""
import numpy as np

SPECS = {"g1": dict(n_states=64, lags=3), "g2": dict(n_states=27, lags=3), "g3": dict(n_states=81, lags=4)}


class GState:
    def __init__(self, kind):
        assert kind in SPECS
        self.kind = kind
        self.n_states = SPECS[kind]["n_states"]
        self.lags = SPECS[kind]["lags"]
        # 整表 Gamma[i_plus, i_minus, s]
        self.Gamma = np.zeros((2, 2, self.n_states), np.int64)
        for ip in (0, 1):
            for im in (0, 1):
                for s in range(self.n_states):
                    self.Gamma[ip, im, s] = self.gamma(ip, im, s)

    def gamma(self, i_plus, i_minus, s):
        if self.kind == "g1":
            return ((s << 2) & 63) | i_plus | (i_minus << 1)
        if self.kind == "g2":
            return (i_plus + i_minus) + 3 * (s % 9)
        return (i_plus + i_minus) + 3 * (s % 27)

    def encode(self, hist_plus, hist_minus):
        """hist_*[j] = 第 j 个滞后(j = 0 最新)的指标,长度 ≥ ϖ。"""
        s = 0
        for j in range(self.lags):
            ip, im = int(hist_plus[j]), int(hist_minus[j])
            if self.kind == "g1":
                s |= (ip << (2 * j)) | (im << (2 * j + 1))
            else:
                s += (ip + im) * (3 ** j)
        return s

    def decode(self, s):
        if self.kind == "g1":
            return [((s >> (2 * j)) & 1, (s >> (2 * j + 1)) & 1) for j in range(self.lags)]
        return [(s // 3 ** j) % 3 for j in range(self.lags)]

    def label(self, s):
        d = self.decode(s)
        return "".join(f"{a}{b}" for a, b in d) if self.kind == "g1" else "".join(str(x) for x in d)

    def states(self, frame):
        """返回 s[k](−1 = 无状态)。用 Γ 逐步推进:段首 ϖ 个可用区间后才有状态;遇到缺口清零。"""
        N = len(frame)
        s = np.full(N, -1, np.int64)
        cur, run = None, 0
        for k in range(N):
            if frame.gap[k]:
                cur, run = None, 0
                continue
            if run >= self.lags:
                s[k] = cur
            ip, im = int(frame.ind_plus[k]), int(frame.ind_minus[k])
            if run == self.lags - 1 and cur is None:
                # 刚凑齐 ϖ 个历史:用 encode 建初始状态(最新在前)
                hp = [int(frame.ind_plus[k - j]) for j in range(self.lags)]
                hm = [int(frame.ind_minus[k - j]) for j in range(self.lags)]
                cur = self.encode(hp, hm)
            elif cur is not None:
                cur = int(self.Gamma[ip, im, cur])
            run += 1
        return s


class ArrivalModel:
    def __init__(self, g: GState):
        self.g = g
        n = g.n_states
        self.count = np.zeros(n, np.int64)
        self.n_plus = np.zeros(n, np.int64)
        self.n_minus = np.zeros(n, np.int64)
        self.n_11 = np.zeros(n, np.int64)
        self.base = dict(pi_plus=np.nan, pi_minus=np.nan, pi_11=np.nan, n=0)   # 无条件频率(备用,EC-17)

    def add(self, frame, states=None):
        s = self.g.states(frame) if states is None else states
        m = (s >= 0) & (~frame.gap)
        ss = s[m]
        yp, ym = frame.ind_plus[m], frame.ind_minus[m]
        np.add.at(self.count, ss, 1)
        np.add.at(self.n_plus, ss, yp.astype(np.int64))
        np.add.at(self.n_minus, ss, ym.astype(np.int64))
        np.add.at(self.n_11, ss, (yp & ym).astype(np.int64))
        return self

    def finalize(self):
        n = self.count.sum()
        self.base = dict(pi_plus=self.n_plus.sum() / max(n, 1), pi_minus=self.n_minus.sum() / max(n, 1), pi_11=self.n_11.sum() / max(n, 1), n=int(n))
        with np.errstate(invalid="ignore", divide="ignore"):
            self.pi_plus = np.where(self.count > 0, self.n_plus / self.count, np.nan)
            self.pi_minus = np.where(self.count > 0, self.n_minus / self.count, np.nan)
            self.pi_11 = np.where(self.count > 0, self.n_11 / self.count, np.nan)
        return self

    def filled(self):
        """未见状态用无条件频率填充的三张表(供递推用;填充了多少个状态由 n_unseen 报告)。"""
        f = lambda a, b: np.where(np.isnan(a), b, a)
        return f(self.pi_plus, self.base["pi_plus"]), f(self.pi_minus, self.base["pi_minus"]), f(self.pi_11, self.base["pi_11"])

    def joint(self):
        """Eq. (9):P(0,0), P(1,0), P(0,1), P(1,1) 每个状态一行 [S,4]。"""
        pp, pm, p11 = self.filled()
        return np.stack([1 - pp - pm + p11, pp - p11, pm - p11, p11], axis=1)

    def check_legal(self):
        pp, pm, p11 = self.pi_plus, self.pi_minus, self.pi_11
        seen = self.count > 0
        bad11 = seen & (p11 > np.minimum(pp, pm) + 1e-12)
        bad00 = seen & (1 - pp - pm + p11 < -1e-12)
        return dict(n_states=int(self.g.n_states), n_seen=int(seen.sum()), n_unseen=int((~seen).sum()),
                    min_count_seen=int(self.count[seen].min()) if seen.any() else 0,
                    states_lt_30=int((seen & (self.count < 30)).sum()),
                    pi11_gt_min=int(bad11.sum()), P00_negative=int(bad00.sum()),
                    pi_range=dict(plus=[float(np.nanmin(pp)), float(np.nanmax(pp))], minus=[float(np.nanmin(pm)), float(np.nanmax(pm))]))

    def table(self):
        rows = []
        for s in range(self.g.n_states):
            rows.append(dict(state=s, label=self.g.label(s), count=int(self.count[s]),
                             pi_plus=float(self.pi_plus[s]), pi_minus=float(self.pi_minus[s]), pi_11=float(self.pi_11[s])))
        return rows


def predict_series(frame, model: ArrivalModel):
    """每个区间的预测 π̂^±_k(用 s_k 查表;无状态 = NaN)。Figure 5 与 log-loss / Brier 用。"""
    s = model.g.states(frame)
    pp, pm, _ = model.filled()
    out_p = np.where(s >= 0, pp[np.maximum(s, 0)], np.nan)
    out_m = np.where(s >= 0, pm[np.maximum(s, 0)], np.nan)
    return s, out_p, out_m


def score(frame, model: ArrivalModel, eps=1e-6):
    """样本外预测质量:对 1^± 的 log-loss 与 Brier(只在有状态且非缺口的区间)。基线 = 训练集无条件频率。"""
    s, pp, pm = predict_series(frame, model)
    m = (s >= 0) & (~frame.gap)
    out = {}
    for lab, pred, y, base in (("plus", pp, frame.ind_plus, model.base["pi_plus"]), ("minus", pm, frame.ind_minus, model.base["pi_minus"])):
        p = np.clip(pred[m], eps, 1 - eps)
        yy = y[m].astype(float)
        ll = -np.mean(yy * np.log(p) + (1 - yy) * np.log(1 - p))
        b = np.clip(base, eps, 1 - eps)
        ll0 = -np.mean(yy * np.log(b) + (1 - yy) * np.log(1 - b))
        out[lab] = dict(n=int(m.sum()), logloss=float(ll), logloss_base=float(ll0), brier=float(np.mean((p - yy) ** 2)),
                        brier_base=float(np.mean((b - yy) ** 2)), mean_pred=float(p.mean()), mean_actual=float(yy.mean()))
    return out


def figure5_series(frame, model_g1: ArrivalModel, half=250):
    """Remark 5:M_k = 1^+ 在 [k−250, k+250] 的均值,P_k = π̂^+(g1) 同窗均值。双侧窗诊断,不进策略。"""
    s, pp, _ = predict_series(frame, model_g1)
    y = frame.ind_plus.astype(float)
    ok = (s >= 0) & (~frame.gap)
    w = 2 * half + 1
    ker = np.ones(w)
    num_y = np.convolve(np.where(ok, y, 0.0), ker, "same")
    num_p = np.convolve(np.where(ok, np.nan_to_num(pp), 0.0), ker, "same")
    den = np.convolve(ok.astype(float), ker, "same")
    with np.errstate(invalid="ignore", divide="ignore"):
        M = np.where(den > w * 0.8, num_y / den, np.nan)
        P = np.where(den > w * 0.8, num_p / den, np.nan)
    return frame.t0, M, P
