"""Step 3 —— P1 Eq. (7)–(8)、(48):随机需求的矩 μ^±_{c^m p^n} = E[(c^±)^m (p^±)^n | 1^± = 1]。
口径(任务书 Step 3,登记表 EC-12):按 Eq. (8) 只对 1^±=1 且回归有效的区间求平均;Eq. (48) 的"全部秒平均"另算一列对照。
递推 (17)–(21) 用到的矩:μ_c, μ_p, μ_cp, μ_c2, μ_c2p, μ_c2p2(任务书 Step 3 列表)。
"""
import numpy as np

KEYS = ("mu_c", "mu_p", "mu_cp", "mu_c2", "mu_c2p", "mu_c2p2")


def moments(c, p):
    c, p = np.asarray(c, float), np.asarray(p, float)
    return dict(mu_c=float(c.mean()), mu_p=float(p.mean()), mu_cp=float((c * p).mean()), mu_c2=float((c * c).mean()),
                mu_c2p=float((c * c * p).mean()), mu_c2p2=float((c * c * p * p).mean()), n=int(len(c)))


def from_params(dp, col):
    """dp: demand.DemandParams;col 0 = +,1 = −。返回 Eq.(8) 条件口径的矩。"""
    v = dp.valid[:, col]
    if v.sum() == 0:
        return None
    return moments(dp.c[v, col], dp.p[v, col])


def from_params_eq48(dp, col, n_total):
    """Eq. (48) 字面:分母为全部区间数 N(无 MO 区间按 c=0、p 无定义 → 乘积按 0 计)。只作对照。"""
    v = dp.valid[:, col]
    c, p = dp.c[v, col], dp.p[v, col]
    return dict(mu_c=float(c.sum() / n_total), mu_p=float(p.sum() / n_total), mu_cp=float((c * p).sum() / n_total),
                mu_c2=float((c * c).sum() / n_total), mu_c2p=float((c * c * p).sum() / n_total), mu_c2p2=float((c * c * p * p).sum() / n_total), n=int(n_total))


def deterministic(m):
    """Step 10 实验 C:确定性需求,高阶矩由一阶矩生成。"""
    return dict(mu_c=m["mu_c"], mu_p=m["mu_p"], mu_cp=m["mu_c"] * m["mu_p"], mu_c2=m["mu_c"] ** 2,
                mu_c2p=m["mu_c"] ** 2 * m["mu_p"], mu_c2p2=m["mu_c"] ** 2 * m["mu_p"] ** 2, n=m["n"])


def table1_checks(mp, mm):
    """Table 1 的结构性检查:两侧接近(Eq. 33)、slope 随机性、μ_cp vs μ_c μ_p、μ_c2p vs μ_c2 μ_p(Eq. 35)。"""
    def rel(a, b):
        return abs(a - b) / max(abs(a), abs(b), 1e-12)
    return dict(sym_c=rel(mp["mu_c"], mm["mu_c"]), sym_p=rel(mp["mu_p"], mm["mu_p"]),
                plus=dict(cv_c=float(np.sqrt(max(mp["mu_c2"] - mp["mu_c"] ** 2, 0)) / mp["mu_c"]),
                          mu_cp_over_mucmup=mp["mu_cp"] / (mp["mu_c"] * mp["mu_p"]), mu_c2p_over_muc2mup=mp["mu_c2p"] / (mp["mu_c2"] * mp["mu_p"])),
                minus=dict(cv_c=float(np.sqrt(max(mm["mu_c2"] - mm["mu_c"] ** 2, 0)) / mm["mu_c"]),
                           mu_cp_over_mucmup=mm["mu_cp"] / (mm["mu_c"] * mm["mu_p"]), mu_c2p_over_muc2mup=mm["mu_c2p"] / (mm["mu_c2"] * mm["mu_p"])))
