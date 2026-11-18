"""PnL 归因(用户 2026-11-08 问:为什么 P2 比 P1 差):把 Table 8 l3sim 列(1000 ms,1.8 ms,10-16/17/18)的 P1_M_g3 与 P2_g{γ*} 的 PnL 拆成
  价差腿   = Σ 挂单成交 (成交价相对下单时刻中价的距离) × 张数           —— 报价距离兑现的点差(用户口径 spread)
  注:不用成交时刻中价,因为 l3sim 里挂单只在真实吃单扫到时成交,盘口穿过我方价位后单子仍挂着,成交时刻中价已偏离(见 2026-11-08 核对)
  市价单腿 = −Σ |e| × (对手价 − 当时中价)                               —— 脉冲与段末清算付的半点差
  taker 费 = −Σ |e| × fee
  持仓腿   = 其余(总 PnL − 上三项):成交后持有库存到平掉 / 到日末计价期间的中价变动(= 用户口径的 alpha,可正可负)
  返佣     = 成交张数 × r(单列,不进"不含返佣")
用法  python pnl_attrib_p1p2.py <sym> [--days 20261016,20261017,20261018]
"""
import os
import sys

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import step14_batch as S14B    # noqa: E402

REBATE_BP = {"USDT": 0.7, "USDC": 1.2}
with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as fh:
    C = yaml.safe_load(fh)


def attrib(sym, days):
    c = C[sym]; unit = float(c["tick"]) * float(c["mult"]); gamma = S14B.gamma_star(sym)
    od = os.path.join(REPRO, "data", "step14", sym)
    rows = {}
    for day in days:
        z = np.load(os.path.join(od, f"{day}_bbo.npz")); bts, bmid = z["ts"], z["mid2"] / 2.0
        mid_end = float(bmid[-1])
        for pol, fn in (("P1", f"{day}_P1_M_g3_L1.8.npz"), ("P2", f"{day}_P2_g{gamma:g}_L1.8.npz")):
            z = np.load(os.path.join(od, fn)); fl, mo = z["fills"], z["mos"]
            W, I = float(z["W"]), float(z["I"])
            gross = W + I * mid_end                                     # 不含返佣,已扣 taker 费(tick×张)
            # 价差腿
            S = 0.0; qty = 0
            if len(fl):
                i0 = np.searchsorted(bts, fl[:, 9], side="right") - 1         # 下单时刻(born)的中价:价差腿 = 报价距离 × 张数;之后的中价变动全归持仓腿
                m = bmid[np.maximum(i0, 0)]
                sign = np.where(fl[:, 1] == 1, 1.0, -1.0)             # 卖单成交:tick − mid;买单:mid − tick
                S = float((sign * (fl[:, 2] - m) * fl[:, 3]).sum()); qty = int(fl[:, 3].sum())
            # 市价单腿 + 费
            M = 0.0; fee = 0.0; mo_qty = 0
            if len(mo):
                e, px, mid = mo[:, 1], mo[:, 2], mo[:, 4]
                M = -float((np.abs(e) * np.abs(px - mid)).sum()); mo_qty = int(np.abs(e).sum())
                # taker 费:W 里已扣,fee_ticks 不在文件里 → 用 gross 恒等式反推不了;按 我方费率 × 当时中价估
                fee = -float((np.abs(e) * OUR_FEE * mid).sum())
            H = gross - S - M - fee
            reb = REBATE_BP[c["quote"]] * 1e-4 * mid_end * qty
            r = rows.setdefault(pol, dict(n=0, gross=0.0, S=0.0, M=0.0, fee=0.0, H=0.0, reb=0.0, qty=0, mo_qty=0, fills=0, I_end=[]))
            r["n"] += 1; r["gross"] += gross; r["S"] += S; r["M"] += M; r["fee"] += fee; r["H"] += H; r["reb"] += reb
            r["qty"] += qty; r["mo_qty"] += mo_qty; r["fills"] += len(fl); r["I_end"].append(abs(I))
            r.setdefault("perday", []).append((day, gross * unit, S * unit, H * unit, (fee + M) * unit, reb * unit))
    q = c["quote"]
    print(f"# {sym} PnL 归因(l3sim 1000 ms,1.8 ms,{','.join(days)},日均 {q};目录队首口径,γ* = {gamma:g})")
    print(f"| 方案 | 挂单成交 张/日 | 价差腿 | 市价单半点差腿 | taker 费 | 持仓腿(alpha) | 不含返佣合计 | 返佣 | 含返佣合计 | 市价单 张/日 | 日末 |I| 均值 张 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for pol in ("P1", "P2"):
        r = rows[pol]; n = r["n"]; u = unit / n
        print(f"| {pol} | {r['qty'] / n:,.0f} | {r['S'] * u:+.1f} | {r['M'] * u:+.1f} | {r['fee'] * u:+.1f} | {r['H'] * u:+.1f} | {r['gross'] * u:+.1f} | {r['reb'] * u:+.1f} | {(r['gross'] + r['reb']) * u:+.1f} | {r['mo_qty'] / n:,.0f} | {np.mean(r['I_end']):,.0f} |")
        # 每张成交的价差腿(tick)
        for d_, g_, s_, h_, f_, rb_ in r["perday"]:
            print(f"  {pol} {d_}:不含返佣 {g_:+.1f} = 价差 {s_:+.1f} + 持仓 {h_:+.1f} + 市价单半点差与费 {f_:+.1f};返佣 {rb_:+.1f}")
        print(f"  {pol}:价差腿每张 {r['S'] / max(r['qty'], 1):+.2f} tick,持仓腿每张 {r['H'] / max(r['qty'], 1):+.2f} tick")


if __name__ == "__main__":
    sym = sys.argv[1]
    arg = lambda f, d: sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d
    attrib(sym, arg("--days", "20261016,20261017,20261018").split(","))
