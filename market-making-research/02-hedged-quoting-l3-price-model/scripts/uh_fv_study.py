#!/usr/bin/env python3
"""research3 H-FV:"没有成交"问题的离线实验(流程阶段 5)——公允价估得更准之后,报价能不能挂近、成交小时能不能变多而不亏。
背景(2026-10-01):MM-UH 报价挂在离模型公允价 6–7 bp,一半的小时没有成交;V3 校准显示模型公允价(两层卡尔曼的慢基差 D̂)
  相对 USDC 实际中价的缺口标准差 2.25 bp、5 分钟只回归 15%;09-02 17 时冷启动错 6 bp。69% 的真实吃单成交在"比公允价更便宜"的一侧。
假设:换一个跟得上的基差估计后,(a) 公允价误差明显变小;(b) 以它为中心,3–4 bp 处的成交对冲后仍为正;(c) 有成交的小时明显变多。
候选(全部只用过去的数据;z = USDC 中价相对 USDT 中价的偏离 bp,每秒取样):
  K0   现行:两层卡尔曼(q_d 1e-4, tau_e 300, var_e 4, gate 3, confirm 60),每小时切片重启(与回测一致)
  K0c  同上,但从当天 0 点连续运行(去掉冷启动的影响)
  M30 / M60 / M120 / M300   z 的滚动中位数(窗口秒;对几秒内回归的扫单不敏感)
评价(只用训练 32 小时;真实吃单 = 剔除单价位成对打印):
  1 跟踪误差:估计值 − 之后 1–10 分钟 z 的中位数,RMSE 与中位绝对误差
  2 真实吃单相对各公允价的打穿深度:成交在"公允价更便宜一侧"的占比、正深度均值(= 下限里的 1/k)
  3 δ 曲线:报价常挂在离该公允价 δ bp,每张真实吃单成交 min($5k, 它在我方价或更差处的额);对冲后 markout(30 s / 5 min / 30 min)
    净 = markout + 我方费率 返佣 − 我方费率 处置成本(s2d 实测);有成交的小时数;每小时美元收益。无库存上限、无撤改延迟(探索性)。
用法:Python314/python.exe -X utf8 scripts/research3/uh_fv_study.py [manifest=data/research2/btcusdc_sep_train32.json]"""
import json, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uh_val as V

CLIP, REB, DISP = 5000.0, 1.2, 0.30
DELTAS = (1, 2, 3, 4, 5, 6, 8)
WINS = (30, 60, 120, 300)
HS = (30, 300, 1800)


def roll_median_causal(z, w):
    """第 i 个值 = z[i-w+1 .. i] 的中位数(只用过去与当前;开头不足 w 个时用已有的)。"""
    return pd.Series(z).rolling(w, min_periods=5).median().values


def main():
    man = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "research2", "btcusdc_sep_train32.json")
    jobs = json.load(open(os.path.join(V.ROOT, man), encoding="utf-8"))
    rows_t, rows_e = [], []
    kc_cache = {}
    for feed, _sym, _s, _e in jobs:
        day, hh = feed.split("/")[1].split("_")
        d = V.day_data(day)
        ats, amid, uts = d["ats"], d["amid"], d["uts"]; umid = (d["ubb"] + d["uba"]) / 2
        t0 = int(pd.Timestamp(f"{day[:4]}-{day[4:6]}-{day[6:]}T{hh}:00:00", tz="UTC").timestamp() * 1e6); t1 = t0 + 3_600_000_000
        day0 = t0 - int(hh) * 3_600_000_000
        # 1 秒网格上的 z(从切片开始前 300 秒起,保证滚动中位数在预热后是满窗的)
        g = np.arange(max(t0 - 300_000_000, max(uts[0], ats[0]) + 1_000_000), t1 + 1_800_000_000 + 1, 1_000_000)
        z = (V.at(uts, umid, g) / V.at(ats, amid, g) - 1.0) * 1e4
        est = {}
        ot, od, _ = V.replicate_basis(d, t0, t1 + 1_800_000_000); est["K0"] = (ot, od)
        if day not in kc_cache:
            kc_cache.clear(); kc_cache[day] = V.replicate_basis(d, max(day0, uts[0]), day0 + 86_400_000_000)[:2]
        est["K0c"] = kc_cache[day]
        for w in WINS:
            est[f"M{w}"] = (g, roll_median_causal(z, w))

        def D(name, t, strict=True):
            ts_, v_ = est[name]
            return V.at(ts_, v_, t, strict)

        # ---- 1 跟踪误差(5 秒网格,切片预热 60 秒后)
        gt = np.arange(t0 + 60_000_000, t1, 5_000_000)
        zi = np.searchsorted(g, gt)                                   # g 上的位置
        fut = np.array([np.median(z[i + 60:i + 600]) for i in zi])    # 之后 1–10 分钟的 z 中位
        for name in est:
            err = D(name, gt, strict=False) - fut
            rows_e.append(dict(feed=feed, est=name, rmse=float(np.sqrt(np.nanmean(err ** 2))), mae=float(np.nanmedian(np.abs(err))), bias=float(np.nanmean(err))))
        # ---- 真实吃单
        tk = d["tr"]; T = tk[(tk.ts.values >= t0 + 60_000_000) & (tk.ts.values < t1)]
        if not len(T):
            continue
        T = T.assign(usd=T.px * V.TICK * T.qty, p=T.px * V.TICK)
        Tg = T.groupby(["ts", "sgn"]).agg(pmin=("p", "min"), pmax=("p", "max"), usd=("usd", "sum")).reset_index()
        Tg = Tg.merge(d["anat"].rename(columns={"sg": "sgn"}), on=["ts", "sgn"], how="left")
        Tg["pair"] = Tg.pair.fillna(False).astype(bool) & (Tg.pmax == Tg.pmin)
        Tg = Tg[~Tg.pair]
        if not len(Tg):
            continue
        T = T.merge(Tg[["ts", "sgn"]], on=["ts", "sgn"], how="inner")
        tt, sg = Tg.ts.values, Tg.sgn.values
        a0 = V.at(ats, amid, tt, strict=True)
        far = np.where(sg > 0, Tg.pmax.values, Tg.pmin.values)
        fut_px = {h: (V.at(uts, umid, tt + h * 1_000_000), V.at(ats, amid, tt + h * 1_000_000)) for h in HS}
        for name in est:
            f0 = a0 * (1 + D(name, tt) / 1e4)
            depth = sg * (far - f0) / f0 * 1e4
            rec0 = dict(feed=feed, est=name, n_real=len(Tg), neg_share=float((depth < 0).mean()), pos_n=int((depth > 0).sum()), pos_sum=float(depth[depth > 0].sum()))
            Tm = T.merge(pd.DataFrame(dict(ts=tt, sgn=sg, f0=f0)), on=["ts", "sgn"])
            dd = Tm.sgn.values * (Tm.p.values - Tm.f0.values) / Tm.f0.values * 1e4
            for dl in DELTAS:
                x = Tm[dd >= dl].groupby(["ts", "sgn"]).usd.sum().clip(upper=CLIP)
                rec = dict(rec0, delta=dl, fills=len(x), f_usd=float(x.sum()))
                if len(x):
                    idx = pd.MultiIndex.from_arrays([tt, sg]); pos = idx.get_indexer(x.index)
                    q = f0[pos] * (1 + sg[pos] * dl / 1e4); s = -sg[pos]
                    for h in HS:
                        U, A = fut_px[h]
                        r = s * ((U[pos] - q) / q - (A[pos] - a0[pos]) / a0[pos]) * 1e4
                        rec[f"rw{h}"] = float((r * x.values).sum())
                rows_t.append(rec)
        print(feed, "real takers", len(Tg), flush=True)
    E = pd.DataFrame(rows_e); T = pd.DataFrame(rows_t).fillna(0.0)
    out = os.path.join(V.OUT, "fv_study"); os.makedirs(out, exist_ok=True)
    E.to_csv(os.path.join(out, "tracking.csv"), index=False); T.to_csv(os.path.join(out, "delta.csv"), index=False)
    pd.set_option("display.width", 230)
    nh = len(jobs)
    print(f"\n== 1 跟踪误差(估计值 − 之后 1–10 分钟的实际基差;{nh} 小时;bp)==")
    print(E.groupby("est").agg(rmse=("rmse", lambda x: float(np.sqrt((x ** 2).mean()))), mae_med=("mae", "median"), worst_hour_rmse=("rmse", "max"), hours_rmse_gt3=("rmse", lambda x: int((x > 3).sum()))).round(2).to_string())
    print("\n== 2 真实吃单相对各公允价的位置 ==")
    A = T[T.delta == DELTAS[0]].groupby("est").agg(n=("n_real", "sum"), neg=("neg_share", "mean"), pos_n=("pos_n", "sum"), pos_sum=("pos_sum", "sum"))
    A["成交在公允价更便宜一侧的占比"] = A.neg; A["正深度均值bp(1/k)"] = A.pos_sum / A.pos_n; A["正深度张数/小时"] = A.pos_n / nh
    print(A[["n", "成交在公允价更便宜一侧的占比", "正深度均值bp(1/k)", "正深度张数/小时"]].round(2).to_string())
    print("\n== 3 δ 曲线(净 = 对冲后 markout + 1.2 − 0.30;$/h = 5 分钟净 × 成交额 / 小时数)==")
    rng = np.random.default_rng(3)
    for name in ["K0", "K0c"] + [f"M{w}" for w in WINS]:
        X = T[T.est == name]; res = []
        for dl in DELTAS:
            G = X[X.delta == dl].groupby("feed").agg(f=("f_usd", "sum"), fills=("fills", "sum"), r30=("rw30", "sum"), r300=("rw300", "sum"), r1800=("rw1800", "sum"))
            G = G[G.f > 0]
            if not len(G):
                continue
            idx = rng.integers(0, len(G), (3000, len(G)))
            b = G.r300.values[idx].sum(1) / G.f.values[idx].sum(1) + REB - DISP
            res.append(dict(delta=dl, fills=int(G.fills.sum()), hours=len(G), usd_h=G.f.sum() / nh, net30=G.r30.sum() / G.f.sum() + REB - DISP, net300=G.r300.sum() / G.f.sum() + REB - DISP,
                            lo300=np.percentile(b, 2.5), hi300=np.percentile(b, 97.5), net1800=G.r1800.sum() / G.f.sum() + REB - DISP,
                            usd_profit_h=(G.r300.sum() / G.f.sum() + REB - DISP) / 1e4 * G.f.sum() / nh, pos_hours=int(((G.r300 / G.f + REB - DISP) > 0).sum())))
        print(f"-- {name}"); print(pd.DataFrame(res).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
