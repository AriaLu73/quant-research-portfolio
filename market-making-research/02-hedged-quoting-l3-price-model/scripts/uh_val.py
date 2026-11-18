#!/usr/bin/env python3
"""research3 → USDC 线(MM-UH)的三项验证 + "为什么一半小时没有成交"的诊断:数据表构建。只读:不改策略、不跑新回测。
输入:基线回测 data/research5/runs/UH1_train32.json(第一阶段重写版 = U15 γ s1 的决策;训练 32 小时;队首排队、1.8 ms)
      各小时的 fills.parquet / broker_sim_wal.jsonl;行情用 data/research2/events 的 book_BTC_B(USDT)、book_XBTUSDCM、trades_XBTUSDCM。
      **不读走步 8 小时(UH1_test8)与新录的考卷数据。**
先写下的问题(2026-10-01,跑之前):
  V1 实现边际恒等式:净利 = USDC 价差捕获 + 对冲腿价差 + 费用 + 基差持仓盈亏 + 未对冲方向盈亏(中价计价,逐笔可加)。
     各项每美元多少 bp?实现的处置成本(对冲腿价差 + 对冲费 + 等待期漂移)与策略先验 c_own = 1.238 bp 是否一致?
  V2 成交条件收益按状态拆:每笔 USDC 成交的"对冲后 markout" r(h) = s·[(U_h − p)/p − (A_h − A_0)/A_0](bp),h = 1/5/30/300/1800 s,
     按成交前可知的状态分组(档位、报价边际、成交前 USDT 走势、吃单大小、USDC 点差、是否加仓)。
  V3 基差滤波校准:离线复现策略的两层卡尔曼基差 D̂(先用订单日志里的二档报价反推的公允价核对复现精度);
     (a) 模型说公允价 = A·(1 + D̂),成交价偏离公允价的部分(边际 m)应当回来:r(h) 对 m 的斜率应趋于 1;
     (b) 成交之后 D̂ 是否朝不利方向移动(持续性的逆向选择)。并与"全部时刻"的回归速度对照。
  N  无成交小时:每小时 USDC 真实吃单的数量、打穿深度(相对公允价)与我方报价离公允价的距离;有多少吃单够得着我方报价。
  E  (探索性,仅训练小时)若报价离公允价 δ bp 常挂,各 δ 的可成交额与对冲后 markout —— 6 bp 左右的下限是否把绝大多数流量挡在外面。
用法:Python314/python.exe -X utf8 scripts/research3/uh_val.py [TAG=UH1_train32]   → data/research3/uh_val/;报表见 uh_val_report.py
"""
import json, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts", "research3"))
from modules.strategy.microstructure import RobustBasisKalman      # noqa: E402  策略用的同一个滤波器类
import flow_anatomy as FA                                           # noqa: E402  成对打印识别
EV = os.path.join(ROOT, "data", "research2", "events")
OUT = os.path.join(ROOT, "data", "research3", "uh_val")
TICK = 0.1
KB = dict(q_d=0.0001, tau_e=300.0, var_e=4.0, gate=3.0, confirm_s=60.0, hs_floor_bp=0.5, obs_s=1.0)   # mm_uh.py DEFAULTS(核对过)
CLIP_USD, REB_USDC, ENGINE_REB, WARMUP_US = 5000.0, 1.2, 0.7, 60_000_000
HS = (1, 5, 30, 300, 1800)
_day = {}


def day_data(day):
    if day not in _day:
        a = pd.read_parquet(os.path.join(EV, f"book_BTC_B_{day}.parquet"), columns=["ts", "bb", "ba"])
        u = pd.read_parquet(os.path.join(EV, f"book_XBTUSDCM_{day}.parquet"), columns=["ts", "bb", "ba"])
        t = pd.read_parquet(os.path.join(EV, f"trades_XBTUSDCM_{day}.parquet"), columns=["ts", "sgn", "px", "qty"])
        X = FA.anatomy("XBTUSDCM", day)[["ts", "sg", "pair", "cat"]]
        _day.clear()
        _day[day] = dict(ats=a.ts.values.astype(np.int64), amid=(a.bb.values + a.ba.values) / 2.0 * TICK,
                         uts=u.ts.values.astype(np.int64), ubb=u.bb.values * TICK, uba=u.ba.values * TICK, tr=t, anat=X)
    return _day[day]


def at(ts, v, t, strict=False):
    """v 在时刻 t(含;strict 则不含)之前的最后一个值。"""
    return v[np.clip(np.searchsorted(ts, t, "left" if strict else "right") - 1, 0, len(v) - 1)]


def replicate_basis(d, t0, t_end):
    """离线复现策略的基差滤波:每个 USDC 盘口帧、距上次观测 ≥ 1 s 时喂一次。→ (obs_ts, D_hat, z)"""
    kal = RobustBasisKalman(KB["q_d"], KB["tau_e"], KB["var_e"], gate=KB["gate"], confirm_s=KB["confirm_s"])
    uts, ubb, uba = d["uts"], d["ubb"], d["uba"]
    i0, i1 = np.searchsorted(uts, t0), np.searchsorted(uts, t_end)
    j0 = np.searchsorted(d["ats"], t0)                    # 策略在 t0 之后收到第一条 USDT 行情才有参考价
    first_ref = d["ats"][j0] if j0 < len(d["ats"]) else t_end
    ot, od, oz = [], [], []
    obs_ts = 0
    for i in range(i0, i1):
        ts = int(uts[i])
        if ts < first_ref or ts - obs_ts < KB["obs_s"] * 1e6:
            continue
        obs_ts = ts
        ref = float(at(d["ats"], d["amid"], ts))
        um = (ubb[i] + uba[i]) / 2
        sp = (uba[i] - ubb[i]) / um * 1e4
        kal.update((um / ref - 1.0) * 1e4, max(sp / 2, KB["hs_floor_bp"]) ** 2 / 3, ts / 1e6)
        ot.append(ts); od.append(kal.value); oz.append((um / ref - 1.0) * 1e4)
    return np.array(ot, dtype=np.int64), np.array(od), np.array(oz)


def read_slice(row):
    day, hh = row["feed"].split("/")[1].split("_")
    d = day_data(day)
    t0 = int(pd.Timestamp(f"{day[:4]}-{day[4:6]}-{day[6:]}T{hh}:00:00", tz="UTC").timestamp() * 1e6)
    orders, cancels = {}, {}
    wal = os.path.join(row["out_dir"], "broker_sim_wal.jsonl")
    if os.path.exists(wal):
        for line in open(wal, encoding="utf-8"):
            o = json.loads(line)
            if o["t"] == "order":
                orders[o["id"]] = dict(sym=o["symbol"], side=1 if o["side"] == "buy" else -1, px=float(o["price"]) if o["price"] else np.nan,
                                       qty=float(o["qty"]), typ=o["order_type"], ts=o["ts_ns"] // 1000)
            elif o["t"] == "cancel":
                cancels[o["id"]] = o["ts_ns"] // 1000
    fp = os.path.join(row["out_dir"], "fills.parquet")
    F = pd.read_parquet(fp) if os.path.exists(fp) else pd.DataFrame()
    if len(F):
        F = F.assign(px=F.price.astype(float), q=F.qty.astype(float), fee=F.fee.astype(float), s=np.where(F.side == "buy", 1, -1), ts=F.ts_ns.values // 1000)
    return dict(day=day, hh=hh, d=d, t0=t0, t1=t0 + 3_600_000_000, orders=orders, cancels=cancels, F=F)


def rng_bp(x):
    return float((x.max() / x.min() - 1) * 1e4) if len(x) else np.nan


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "UH1_train32"
    rows = json.load(open(os.path.join(ROOT, "data", "research5", "runs", tag + ".json"), encoding="utf-8"))
    os.makedirs(OUT, exist_ok=True)
    ident, fills_tab, hours, takers_all, grid_all, walchk, trades_all = [], [], [], [], [], [], []
    for row in rows:
        S = read_slice(row)
        d, t0, t1, F = S["d"], S["t0"], S["t1"], S["F"]
        ats, amid, uts = d["ats"], d["amid"], d["uts"]
        umid = (d["ubb"] + d["uba"]) / 2
        ot, od, _ = replicate_basis(d, t0, t1 + 1_800_000_000)

        def Dhat(t, strict=False):
            return at(ot, od, t, strict)

        A_end, U_end = float(at(ats, amid, t1)), float(at(uts, umid, t1))
        # ---------------- V1 恒等式(中价计价)
        r = dict(feed=row["feed"], hh=S["hh"], engine_net=row["net"], engine_net_corr=row["net_corr"], usdc_usd=0.0, n_usdc=0)
        if len(F):
            isu = (F.symbol == "BTC-USDC").values
            A0 = at(ats, amid, F.ts.values, strict=True)
            U0 = at(uts, umid, F.ts.values, strict=True)
            M0 = np.where(isu, U0, A0)
            sq = F.s.values * F.q.values
            usd = (F.px * F.q).values
            fee_fix = (REB_USDC - ENGINE_REB) / 1e4 * float(usd[isu].sum())
            r["usdc_usd"] = float(usd[isu].sum()); r["n_usdc"] = int(F[isu].groupby(["order_id", "ts"]).ngroups)
            r["hedge_usd"] = float(usd[~isu].sum()); r["hedge_taker_usd"] = float(usd[~isu & ~F.maker.values].sum())
            r["A_usdc_spread"] = float((sq * (M0 - F.px.values))[isu].sum())
            r["B_hedge_touch"] = float((sq * (M0 - F.px.values))[~isu].sum())
            r["C_fee_usdc"] = float(-F.fee.values[isu].sum()) + fee_fix
            r["C_fee_hedge"] = float(-F.fee.values[~isu].sum())
            r["D_basis"] = float((sq * ((U_end - A_end) - (U0 - A0)))[isu].sum())
            r["E_direction"] = float((sq * (A_end - A0)).sum())
            pos_u, pos_a = float(sq[isu].sum()), float(sq[~isu].sum())
            r["net_mid"] = float(-(sq * F.px.values).sum()) + pos_u * U_end + pos_a * A_end - float(F.fee.sum()) + fee_fix
            r["sum_parts"] = r["A_usdc_spread"] + r["B_hedge_touch"] + r["C_fee_usdc"] + r["C_fee_hedge"] + r["D_basis"] + r["E_direction"]
            r["end_pos_usdc"], r["end_net_pos"] = pos_u, pos_u + pos_a
        ident.append(r)
        # ---------------- 我方 USDC 报价时间线(按 侧 × 档)
        last_fill = F.groupby("order_id").ts.max().to_dict() if len(F) else {}
        filled_q = F.groupby("order_id").q.sum().to_dict() if len(F) else {}
        Q = []
        for oid, o in S["orders"].items():
            if o["sym"] != "BTC-USDC":
                continue
            off = S["cancels"].get(oid)
            if off is None:
                off = last_fill[oid] if filled_q.get(oid, 0.0) >= o["qty"] - 1e-9 else t1
            Q.append((o["side"], 2 if o["px"] * o["qty"] > 1.5 * CLIP_USD else 1, o["px"], o["ts"], off))
        Q = pd.DataFrame(Q, columns=["side", "lvl", "px", "on", "off"])
        slot = {k: g.sort_values("on") for k, g in Q.groupby(["side", "lvl"])} if len(Q) else {}

        def quote_at(side, lvl, t):
            g = slot.get((side, lvl))
            if g is None:
                return np.nan
            i = np.searchsorted(g.on.values, t, "right") - 1
            return g.px.values[i] if i >= 0 and t <= g.off.values[i] else np.nan   # 含成交那一刻(成交即下线)

        # 复现精度核对:同一时刻发出的二档买、卖价的中点 = 当时的(偏斜后)公允价;只取空仓时刻
        if len(Q):
            m = Q[(Q.side == 1) & (Q.lvl == 2)].merge(Q[(Q.side == -1) & (Q.lvl == 2)], on="on", suffixes=("_b", "_a"))
            if len(m):
                p_at = np.zeros(len(m))
                if len(F):
                    pu = F[F.symbol == "BTC-USDC"].sort_values("ts")
                    if len(pu):
                        p_at = np.r_[0.0, np.cumsum(pu.s.values * pu.q.values)][np.searchsorted(pu.ts.values, m.on.values, "right")]
                fw = (m.px_b.values + m.px_a.values) / 2
                fr = at(ats, amid, m.on.values) * (1 + Dhat(m.on.values) / 1e4)
                walchk.append(pd.DataFrame(dict(feed=row["feed"], diff_bp=((fr - fw) / fw * 1e4)[np.abs(p_at) < 1e-9])))
        # ---------------- 每笔 USDC 成交(V2 / V3)
        if len(F) and (F.symbol == "BTC-USDC").any():
            Fu = F[F.symbol == "BTC-USDC"].assign(usd=lambda x: x.px * x.q)
            G = Fu.groupby(["order_id", "ts"]).agg(s=("s", "first"), usd=("usd", "sum"), q=("q", "sum")).reset_index().sort_values("ts").reset_index(drop=True)
            G["px"] = G.usd / G.q
            G["pos_before"] = np.r_[0.0, np.cumsum(G.s.values * G.q.values)][:-1]
            tk = d["tr"]
            for g in G.itertuples():
                t, s, p = int(g.ts), int(g.s), float(g.px)
                a0 = float(at(ats, amid, t, strict=True)); u_pre = float(at(uts, umid, t, strict=True)); dh = float(Dhat(t, strict=True))
                f0 = a0 * (1 + dh / 1e4)
                o = S["orders"].get(g.order_id, {})
                k = tk[(tk.ts.values >= t - 3000) & (tk.ts.values <= t + 3000) & (tk.sgn.values == -s)]
                i_u = max(np.searchsorted(uts, t, "left") - 1, 0)
                rec = dict(feed=row["feed"], hh=S["hh"], ts=t, s=s, px=p, usd=float(g.usd), lvl=2 if o.get("px", 0) * o.get("qty", 0) > 1.5 * CLIP_USD else 1,
                           m=s * (f0 - p) / p * 1e4, e0=s * (u_pre - p) / p * 1e4, gap=s * (dh - (u_pre / a0 - 1) * 1e4),
                           pre500=s * (a0 / float(at(ats, amid, t - 500_000)) - 1) * 1e4, taker_usd=float((k.px * TICK * k.qty).sum()),
                           spr_bp=float((d["uba"][i_u] - d["ubb"][i_u]) / u_pre * 1e4), adds=bool(s * g.pos_before >= -1e-12),
                           rng60=rng_bp(amid[np.searchsorted(ats, t - 60_000_000):np.searchsorted(ats, t)]))
                for h in HS:
                    th = t + h * 1_000_000
                    ah = float(at(ats, amid, th))
                    rec[f"r{h}"] = s * ((float(at(uts, umid, th)) - p) / p - (ah - a0) / a0) * 1e4
                    rec[f"dD{h}"] = s * (float(Dhat(th)) - dh)
                    rec[f"dA{h}"] = s * (ah / a0 - 1) * 1e4            # 不对冲时 USDT 给这笔仓位带来的盈亏(+ = 有利)
                fills_tab.append(rec)
        # ---------------- 全部时刻的回归速度(5 s 网格,滤波已预热 60 s)
        gt = np.arange(t0 + WARMUP_US, t1, 5_000_000)
        gz = (at(uts, umid, gt) / at(ats, amid, gt) - 1) * 1e4
        rec = dict(feed=row["feed"], ts=gt, gap=Dhat(gt) - gz)
        for h in (30, 300, 1800):
            rec[f"dz{h}"] = (at(uts, umid, gt + h * 1_000_000) / at(ats, amid, gt + h * 1_000_000) - 1) * 1e4 - gz
        grid_all.append(pd.DataFrame(rec))
        # ---------------- 吃单与"够不够得着"(N、E)
        tk = d["tr"]
        T = tk[(tk.ts.values >= t0 + WARMUP_US) & (tk.ts.values < t1)]
        T = T.assign(usd=T.px * TICK * T.qty, p=T.px * TICK)
        Tg = pd.DataFrame(columns=["usd", "depth", "our_dist", "short_by", "pair"])
        if len(T):
            Tg = T.groupby(["ts", "sgn"]).agg(pmin=("p", "min"), pmax=("p", "max"), usd=("usd", "sum")).reset_index()
            Tg = Tg.merge(d["anat"].rename(columns={"sg": "sgn"}), on=["ts", "sgn"], how="left")
            Tg["pair"] = Tg.pair.fillna(False).astype(bool)
            tt, sg = Tg.ts.values, Tg.sgn.values
            far = np.where(sg > 0, Tg.pmax.values, Tg.pmin.values)
            a0 = at(ats, amid, tt, strict=True)
            f0 = a0 * (1 + Dhat(tt, strict=True) / 1e4)
            Tg["depth"] = sg * (far - f0) / f0 * 1e4
            Tg["f0"], Tg["a0"] = f0, a0
            q1 = np.array([quote_at(-s_, 1, t_) for s_, t_ in zip(sg, tt)]); q2 = np.array([quote_at(-s_, 2, t_) for s_, t_ in zip(sg, tt)])
            qb = np.where(sg > 0, np.fmin(q1, q2), np.fmax(q1, q2))                 # 被打一侧我方最靠前的价
            Tg["our_dist"] = sg * (qb - f0) / f0 * 1e4
            Tg["short_by"] = sg * (qb - far) / f0 * 1e4                              # > 0:吃单差这么多 bp 没够着我方
            Tg["feed"], Tg["hh"] = row["feed"], S["hh"]
            for h in (30, 300, 1800):
                Tg[f"U{h}"] = at(uts, umid, tt + h * 1_000_000); Tg[f"A{h}"] = at(ats, amid, tt + h * 1_000_000)
            takers_all.append(Tg)
            T = T.merge(Tg[["ts", "sgn", "pair", "f0"]], on=["ts", "sgn"], how="left")
            T["feed"] = row["feed"]; T["d"] = T.sgn * (T.p - T.f0) / T.f0 * 1e4
            trades_all.append(T[["feed", "ts", "sgn", "usd", "d", "pair"]])
        real = Tg[~Tg.pair.astype(bool)] if len(Tg) else Tg
        dur = t1 - t0 - WARMUP_US
        pres = {f"pres_{'b' if k[0] > 0 else 'a'}{k[1]}": float((np.minimum(g.off.values, t1) - g.on.values).clip(min=0).sum() / dur) for k, g in slot.items()}
        i_g = np.clip(np.searchsorted(uts, gt, "right") - 1, 0, len(uts) - 1)
        hours.append(dict(feed=row["feed"], hh=S["hh"], our_fills=r["n_usdc"], our_usd=r["usdc_usd"], net=row["net_corr"], orders=row["orders"],
                          takers=len(Tg), taker_usd=float(Tg.usd.sum()) if len(Tg) else 0.0, real_takers=len(real), real_usd=float(real.usd.sum()) if len(real) else 0.0,
                          depth_p50=real.depth.median() if len(real) else np.nan, depth_p90=real.depth.quantile(.9) if len(real) else np.nan,
                          depth_max=real.depth.max() if len(real) else np.nan, our_dist_med=real.our_dist.median() if len(real) else np.nan,
                          reach=int((real.short_by <= 1e-9).sum()) if len(real) else 0, short_by_min=real.short_by.min() if len(real) else np.nan,
                          real_ge2=int((real.depth >= 2).sum()) if len(real) else 0, real_ge4=int((real.depth >= 4).sum()) if len(real) else 0,
                          real_ge6=int((real.depth >= 6).sum()) if len(real) else 0,
                          usdc_half_spr=float(np.median((d["uba"][i_g] - d["ubb"][i_g]) / umid[i_g] * 1e4 / 2)),
                          usdt_rng60=float(np.nanmedian([rng_bp(amid[np.searchsorted(ats, x - 60_000_000):np.searchsorted(ats, x)]) for x in gt[::12]])), **pres))
        print(row["feed"], "fills", r["n_usdc"], "real takers", len(real), flush=True)
    pd.DataFrame(ident).fillna(0.0).to_csv(os.path.join(OUT, f"{tag}_identity.csv"), index=False)
    pd.DataFrame(fills_tab).to_csv(os.path.join(OUT, f"{tag}_fills.csv"), index=False)
    pd.DataFrame(hours).to_csv(os.path.join(OUT, f"{tag}_hours.csv"), index=False)
    pd.concat(takers_all, ignore_index=True).to_parquet(os.path.join(OUT, f"{tag}_takers.parquet"))
    pd.concat(grid_all, ignore_index=True).to_parquet(os.path.join(OUT, f"{tag}_grid.parquet"))
    pd.concat(trades_all, ignore_index=True).to_parquet(os.path.join(OUT, f"{tag}_trades.parquet"))
    if walchk:
        W = pd.concat(walchk, ignore_index=True)
        W.to_csv(os.path.join(OUT, f"{tag}_walcheck.csv"), index=False)
        a = W.diff_bp.abs()
        print(f"复现精度(二档报价反推的公允价 对 离线复现;空仓时刻 {len(W)} 个):差的中位 {W.diff_bp.median():+.3f} bp,|差| 中位 {a.median():.3f},90% 分位 {a.quantile(.9):.3f},99% {a.quantile(.99):.3f}")
    print("saved to", OUT)


if __name__ == "__main__":
    main()
