#!/usr/bin/env python3
"""因子实验室(Factor Lab):从 extract_kucoin_tardis 的 L1/top-5 状态与逐笔成交构造候选因子,
按 prompt §10/§11 输出未来 markout 与 Bid/Ask fill-conditioned markout 的检验。

事件时间规则:所有因子只用 t 及 t 之前的事件(窗口用 cumsum + searchsorted(ts - w, 'right'))。

用法:
  python scripts/research/factor_lab.py build   --days 20251001,...   # -> data/research/factors/<day>.parquet + events_<day>.parquet
  python scripts/research/factor_lab.py analyze --days ...           # -> docs/research/factor_report.md + json
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KU = os.path.join(ROOT, "data", "research", "kucoin")
OKX = os.path.join(ROOT, "data", "research", "okx")
FOUT = os.path.join(ROOT, "data", "research", "factors")
TICK = 0.1
HORIZONS_MS = [10, 25, 50, 100, 250, 500, 1000, 5000, 30000]
US = 1000  # ms -> us


# ----------------------------------------------------------------------------- helpers
def _win_idx(ts: np.ndarray, w_us: int) -> np.ndarray:
    """对每个 i 返回 j = 首个 ts[j] > ts[i]-w 的下标(窗口 (t-w, t] 的左端)。"""
    return np.searchsorted(ts, ts - w_us, side="right")


def _wsum(cum: np.ndarray, j: np.ndarray) -> np.ndarray:
    """cum 为带前导 0 的累计和(len n+1);窗口和 = cum[i+1]-cum[j]。"""
    n = len(cum) - 1
    return cum[1:n + 1] - cum[j]


def _at_or_before(ts_ref: np.ndarray, ts_q: np.ndarray) -> np.ndarray:
    """ts_ref 中 ≤ ts_q 的最后下标(无则 -1)。"""
    return np.searchsorted(ts_ref, ts_q, side="right") - 1


def _sweep_groups(tr: pd.DataFrame) -> pd.DataFrame:
    """同一 (ts, side) 的连续成交视为一次主动单扫单(一个成交事件)。"""
    key = (tr["ts"].values != np.r_[-1, tr["ts"].values[:-1]]) | (tr["side"].values != np.r_[0, tr["side"].values[:-1]])
    gid = np.cumsum(key)
    g = tr.groupby(gid)
    out = pd.DataFrame({"ts": g["ts"].first(), "side": g["side"].first(), "price": g["price"].first(),
                        "px_last": g["price"].last(), "qty": g["qty"].sum(), "n": g["qty"].size()})
    return out.reset_index(drop=True)


# ----------------------------------------------------------------------------- build
def build_day(day: str) -> str:
    l1 = pq.read_table(os.path.join(KU, f"l1_{day}.parquet")).to_pandas()
    tr = pq.read_table(os.path.join(KU, f"trades_{day}.parquet")).to_pandas()
    # 单调时间轴:交易所时间偶有回跳(审计 ~10ms 级),回跳行按上一有效时间钳制(不丢事件、不前视)
    ts = np.maximum.accumulate(l1["ts"].values)
    l1["ts"] = ts
    n = len(l1)
    bb = l1["bb"].values; ba = l1["ba"].values
    bq = np.stack([l1[f"bq{k}"].values for k in range(1, 6)], 1)
    aq = np.stack([l1[f"aq{k}"].values for k in range(1, 6)], 1)
    mid = (bb + ba) / 2
    spread_t = np.round((ba - bb) / TICK)
    valid = (spread_t >= 1) & (spread_t <= 20) & (bq[:, 0] > 0) & (aq[:, 0] > 0)
    F: dict[str, np.ndarray] = {"ts": ts, "mid": mid, "bb": bb, "ba": ba, "valid": valid,
                                 "hour": ((ts // 1_000_000) % 86400 // 3600).astype(np.int8)}
    # ---- LOB
    F["spread_ticks"] = spread_t
    F["imb1"] = (bq[:, 0] - aq[:, 0]) / (bq[:, 0] + aq[:, 0] + 1e-12)
    sb5 = bq.sum(1); sa5 = aq.sum(1)
    F["imb5"] = (sb5 - sa5) / (sb5 + sa5 + 1e-12)
    F["imb2"] = (bq[:, :2].sum(1) - aq[:, :2].sum(1)) / (bq[:, :2].sum(1) + aq[:, :2].sum(1) + 1e-12)
    F["depth_conc_b"] = bq[:, 0] / (sb5 + 1e-12)
    F["depth_conc_a"] = aq[:, 0] / (sa5 + 1e-12)
    F["depth_conc_imb"] = F["depth_conc_b"] - F["depth_conc_a"]
    bt = np.maximum(1, np.round((bb - l1["bp5"].values) / TICK) + 1)
    at = np.maximum(1, np.round((l1["ap5"].values - ba) / TICK) + 1)
    F["slope_b"] = sb5 / bt; F["slope_a"] = sa5 / at
    F["slope_imb"] = (F["slope_b"] - F["slope_a"]) / (F["slope_b"] + F["slope_a"] + 1e-12)
    F["liq_asym"] = np.log((sb5 + 1e-6) / (sa5 + 1e-6))
    F["bq1"] = bq[:, 0]; F["aq1"] = aq[:, 0]
    F["bq1_usd"] = bq[:, 0] * bb; F["aq1_usd"] = aq[:, 0] * ba
    # 参考深度尺度:顶档量的滚动均值(过去 2000 行)
    ref_depth = pd.Series((bq[:, 0] + aq[:, 0]) / 2).rolling(2000, min_periods=50).mean().bfill().values
    # ---- OFI (Cont-Kukanov-Stoikov)
    pbb = np.r_[bb[0], bb[:-1]]; pba = np.r_[ba[0], ba[:-1]]
    pbq = np.r_[bq[0, 0], bq[:-1, 0]]; paq = np.r_[aq[0, 0], aq[:-1, 0]]
    e = (np.where(bb >= pbb, bq[:, 0], 0) - np.where(bb <= pbb, pbq, 0)
         - np.where(ba <= pba, aq[:, 0], 0) + np.where(ba >= pba, paq, 0))
    e[~valid] = 0.0
    e[0] = 0.0
    cum_e = np.r_[0.0, np.cumsum(e)]
    for w in (100, 500, 1000, 5000):
        F[f"ofi_{w}ms"] = _wsum(cum_e, _win_idx(ts, w * US)) / (ref_depth + 1e-9)
    # ---- 成交流(只用 ts_trade <= ts)
    tts = tr["ts"].values; tside = tr["side"].values.astype(np.float64); tqty = tr["qty"].values
    tpx = tr["price"].values
    cum_sf = np.r_[0.0, np.cumsum(tside * tqty)]
    cum_v = np.r_[0.0, np.cumsum(tqty)]
    cum_n = np.arange(len(tr) + 1, dtype=np.float64)
    cum_buy = np.r_[0.0, np.cumsum(np.where(tside > 0, tqty, 0.0))]
    cum_sell = np.r_[0.0, np.cumsum(np.where(tside < 0, tqty, 0.0))]
    jt = np.searchsorted(tts, ts, side="right")           # 成交数 ≤ t
    for w in (1000, 5000, 30000):
        jw = np.searchsorted(tts, ts - w * US, side="right")
        sf = cum_sf[jt] - cum_sf[jw]; v = cum_v[jt] - cum_v[jw]
        F[f"tflow_{w}ms"] = sf / (ref_depth + 1e-9)
        F[f"timb_{w}ms"] = sf / (v + 1e-9)
        F[f"buyflow_{w}ms"] = (cum_buy[jt] - cum_buy[jw]) / (ref_depth + 1e-9)
        F[f"sellflow_{w}ms"] = (cum_sell[jt] - cum_sell[jw]) / (ref_depth + 1e-9)
        F[f"tint_{w}ms"] = cum_n[jt] - cum_n[jw]
    jw = np.searchsorted(tts, ts - 100 * US, side="right")
    F["tcluster_100ms"] = cum_n[jt] - cum_n[jw]
    last_t = np.where(jt > 0, tts[np.maximum(jt - 1, 0)], ts - 60_000_000)
    F["t_since_trade_ms"] = np.minimum((ts - last_t) / US, 60000.0)
    # L1 事件到达强度(过去 1s 的行数)
    F["arr_int_1s"] = np.arange(1, n + 1) - _win_idx(ts, 1000 * US)
    # ---- 撤单分解:同价位顶档减量 − 该价位同期成交量 = 撤单;增量 = 新挂
    same_b = bb == pbb; same_a = ba == pba
    dqb = bq[:, 0] - pbq; dqa = aq[:, 0] - paq
    # 区间 (ts_{i-1}, ts_i] 内在 bb 成交的卖方主动量 / 在 ba 成交的买方主动量
    pts = np.r_[ts[0] - 1, ts[:-1]]
    j0 = np.searchsorted(tts, pts, side="right"); j1 = jt
    cum_sell_at = np.r_[0.0, np.cumsum(np.where(tside < 0, tqty, 0.0))]
    cum_buy_at = np.r_[0.0, np.cumsum(np.where(tside > 0, tqty, 0.0))]
    tv_b = cum_sell_at[j1] - cum_sell_at[j0]          # 近似:区间内所有卖方主动量(bb 档)
    tv_a = cum_buy_at[j1] - cum_buy_at[j0]
    cancel_b = np.where(same_b & valid, np.maximum(0.0, -dqb - tv_b), 0.0)
    cancel_a = np.where(same_a & valid, np.maximum(0.0, -dqa - tv_a), 0.0)
    add_b = np.where(same_b & valid, np.maximum(0.0, dqb), 0.0)
    add_a = np.where(same_a & valid, np.maximum(0.0, dqa), 0.0)
    ccb = np.r_[0.0, np.cumsum(cancel_b)]; cca = np.r_[0.0, np.cumsum(cancel_a)]
    cab = np.r_[0.0, np.cumsum(add_b)]; caa = np.r_[0.0, np.cumsum(add_a)]
    for w in (500, 2000):
        j = _win_idx(ts, w * US)
        cb = _wsum(ccb, j); ca = _wsum(cca, j); ab = _wsum(cab, j); aa = _wsum(caa, j)
        F[f"cancel_b_{w}ms"] = cb / (ref_depth + 1e-9); F[f"cancel_a_{w}ms"] = ca / (ref_depth + 1e-9)
        F[f"cancel_imb_{w}ms"] = (ca - cb) / (ca + cb + 1e-9)
        F[f"add_imb_{w}ms"] = (ab - aa) / (ab + aa + 1e-9)
        jw2 = np.searchsorted(tts, ts - w * US, side="right")
        F[f"cancel_trade_ratio_{w}ms"] = (ca + cb) / (cum_v[jt] - cum_v[jw2] + 1e-9)
    F["cancel_accel"] = F["cancel_b_500ms"] * 4 - F["cancel_b_2000ms"]     # 短窗年化 − 长窗(买侧)
    F["cancel_accel_a"] = F["cancel_a_500ms"] * 4 - F["cancel_a_2000ms"]
    # 队列耗尽率(同价位):1 - q(t)/q(t-w)
    for w in (200, 1000):
        j = np.maximum(_win_idx(ts, w * US) - 1, 0)
        same = bb == bb[j]
        F[f"qdepl_b_{w}ms"] = np.where(same, 1 - bq[:, 0] / (bq[j, 0] + 1e-9), np.where(bb > bb[j], -1.0, 1.0))
        same = ba == ba[j]
        F[f"qdepl_a_{w}ms"] = np.where(same, 1 - aq[:, 0] / (aq[j, 0] + 1e-9), np.where(ba < ba[j], -1.0, 1.0))
        F[f"qdepl_imb_{w}ms"] = F[f"qdepl_a_{w}ms"] - F[f"qdepl_b_{w}ms"]
    # 队列周转:5s 内成交量 / 顶档量
    jw = np.searchsorted(tts, ts - 5000 * US, side="right")
    F["qturn_b"] = (cum_sell[jt] - cum_sell[jw]) / (bq[:, 0] + 1e-9)
    F["qturn_a"] = (cum_buy[jt] - cum_buy[jw]) / (aq[:, 0] + 1e-9)
    # ---- 短期动态
    for w in (1000, 5000, 30000):
        j = np.maximum(_win_idx(ts, w * US) - 1, 0)
        F[f"ret_{w}ms"] = (mid - mid[j]) / mid * 1e4
    j1s = np.maximum(_win_idx(ts, 1000 * US) - 1, 0)
    F["accel_1s"] = F["ret_1000ms"] - F["ret_1000ms"][j1s]
    dm = np.r_[0.0, np.diff(mid)] / mid * 1e4
    cum_sq = np.r_[0.0, np.cumsum(dm * dm)]
    for w in (10000, 60000):
        F[f"vol_{w}ms"] = np.sqrt(_wsum(cum_sq, _win_idx(ts, w * US)))
    F["spread_chg_1s"] = spread_t - spread_t[j1s]
    F["depth_chg_1s"] = np.log((sb5 + sa5 + 1e-6) / (sb5[j1s] + sa5[j1s] + 1e-6))
    # ---- VPIN(成交量桶 = 当日成交量/500,50 桶滚动)
    total_v = cum_v[-1]
    bucket = max(total_v / 500.0, 1e-6)
    bkt_id = np.floor(cum_v[1:] / bucket).astype(np.int64)
    bs = pd.DataFrame({"b": bkt_id, "buy": np.where(tside > 0, tqty, 0.0), "sell": np.where(tside < 0, tqty, 0.0), "ts": tts})
    g = bs.groupby("b").agg(buy=("buy", "sum"), sell=("sell", "sum"), ts=("ts", "max"))
    g["oi"] = (g["buy"] - g["sell"]).abs() / (g["buy"] + g["sell"] + 1e-12)
    g["vpin"] = g["oi"].rolling(50, min_periods=10).mean()
    gts = g["ts"].values; gv = g["vpin"].fillna(g["oi"].expanding().mean()).values
    k = _at_or_before(gts, ts)
    F["vpin"] = np.where(k >= 0, gv[np.maximum(k, 0)], np.nan)
    # ---- 跨所领先(OKX BBO,交易所时间对齐,零传输延迟假设 —— 标注 ESTIMATED)
    okx_p = os.path.join(OKX, f"quotes_{day}.parquet")
    if os.path.exists(okx_p):
        q = pq.read_table(okx_p).to_pandas()
        qts = np.maximum.accumulate(q["ts"].values); qmid = ((q["bb"] + q["ba"]) / 2).values
        k = _at_or_before(qts, ts)
        om = np.where(k >= 0, qmid[np.maximum(k, 0)], np.nan)
        F["xlead_okx_bp"] = (om - mid) / mid * 1e4
        # 去均值(基差):减去过去 60s 的均值
        s = pd.Series(F["xlead_okx_bp"])
        F["xlead_okx_dm"] = (s - s.rolling(3000, min_periods=100).mean()).values
        ot = pq.read_table(os.path.join(OKX, f"trades_{day}.parquet")).to_pandas()
        ots = np.maximum.accumulate(ot["ts"].values)
        ocs = np.r_[0.0, np.cumsum(ot["side"].values * ot["qty"].values)]
        ocv = np.r_[0.0, np.cumsum(ot["qty"].values)]
        jo = np.searchsorted(ots, ts, side="right")
        for w in (1000, 5000):
            jow = np.searchsorted(ots, ts - w * US, side="right")
            F[f"okx_timb_{w}ms"] = (ocs[jo] - ocs[jow]) / (ocv[jo] - ocv[jow] + 1e-9)
    # ---- 标签:未来 mid 变动(bp)
    for h in HORIZONS_MS:
        k = np.searchsorted(ts, ts + h * US, side="left")
        ok = k < n
        fm = np.where(ok, mid[np.minimum(k, n - 1)], np.nan)
        F[f"dmid_{h}ms"] = (fm - mid) / mid * 1e4
    # ---- 成交事件(扫单组)与 fill-conditioned markout
    ev = _sweep_groups(tr)
    ev = ev[(ev["ts"].values >= ts[0]) & (ev["ts"].values <= ts[-1])].reset_index(drop=True)
    k = np.searchsorted(ts, ev["ts"].values, side="left") - 1     # 成交前最后簿状态
    ev = ev[k >= 0].reset_index(drop=True); k = k[k >= 0]
    ev["row"] = k
    ev["bb_pre"] = bb[k]; ev["ba_pre"] = ba[k]
    # bid fill:卖方主动且成交价 ≤ 成交前 bb(我方挂 bb 的单会被成交);ask fill 对称
    ev["is_bid_fill"] = (ev["side"] == -1) & (ev["price"] <= ev["bb_pre"] + 1e-9)
    ev["is_ask_fill"] = (ev["side"] == 1) & (ev["price"] >= ev["ba_pre"] - 1e-9)
    ev["sweep"] = np.where(ev["side"] == -1, ev["px_last"] < ev["bb_pre"] - 1e-9, ev["px_last"] > ev["ba_pre"] + 1e-9)
    fill_px = np.where(ev["side"] == -1, ev["bb_pre"], ev["ba_pre"])
    sgn = np.where(ev["side"] == -1, 1.0, -1.0)      # 我方买入:mid 上涨为正
    for h in HORIZONS_MS:
        kk = np.searchsorted(ts, ev["ts"].values + h * US, side="left")
        ok = kk < n
        fm = np.where(ok, mid[np.minimum(kk, n - 1)], np.nan)
        ev[f"mk_{h}ms"] = sgn * (fm - fill_px) / fill_px * 1e4
    ev["fill_px"] = fill_px
    # 事件对应的因子值(成交前状态)
    fac_cols = [c for c in F if c not in ("ts", "mid", "bb", "ba", "valid", "hour") and not c.startswith("dmid_")]
    for c in fac_cols:
        ev[c] = F[c][k]
    ev["valid"] = valid[k]; ev["hour"] = F["hour"][k]
    os.makedirs(FOUT, exist_ok=True)
    tbl = pa.table({c: (v.astype(np.float32) if v.dtype == np.float64 else v) for c, v in F.items()})
    pq.write_table(tbl, os.path.join(FOUT, f"{day}.parquet"), compression="zstd")
    pq.write_table(pa.Table.from_pandas(ev, preserve_index=False), os.path.join(FOUT, f"events_{day}.parquet"), compression="zstd")
    return f"{day}: rows {n:,} events {len(ev):,} bid_fill {int(ev['is_bid_fill'].sum()):,} ask_fill {int(ev['is_ask_fill'].sum()):,} factors {len(fac_cols)}"


# ----------------------------------------------------------------------------- analyze
def _ic(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 200:
        return np.nan, np.nan
    xs = pd.Series(x[m]); ys = pd.Series(y[m])
    return float(xs.corr(ys)), float(xs.corr(ys, method="spearman"))


def _decile(x, y, q=10):
    m = np.isfinite(x) & np.isfinite(y)
    x = x[m]; y = y[m]
    if len(x) < 500:
        return None
    try:
        b = pd.qcut(x, q, labels=False, duplicates="drop")
    except ValueError:
        return None
    df = pd.DataFrame({"b": b, "y": y}).groupby("b")["y"].agg(["mean", "count", "std"])
    if len(df) < 3:
        return None
    mono = float(pd.Series(df["mean"].values).corr(pd.Series(np.arange(len(df))), method="spearman"))
    top, bot = df.iloc[-1], df.iloc[0]
    se = np.sqrt(top["std"] ** 2 / top["count"] + bot["std"] ** 2 / bot["count"] + 1e-18)
    return {"means": [round(float(v), 4) for v in df["mean"]], "mono": round(mono, 3),
            "tb_diff": round(float(top["mean"] - bot["mean"]), 4), "tb_t": round(float((top["mean"] - bot["mean"]) / se), 2)}


def analyze(days: list[str], out_md: str, sample: int = 400_000):
    rng = np.random.default_rng(7)
    rows_all = []; ev_all = []
    for d in days:
        f = pq.read_table(os.path.join(FOUT, f"{d}.parquet")).to_pandas()
        f = f[f["valid"]]
        if len(f) > sample:
            f = f.iloc[np.sort(rng.choice(len(f), sample, replace=False))]
        f["day"] = d; rows_all.append(f)
        e = pq.read_table(os.path.join(FOUT, f"events_{d}.parquet")).to_pandas()
        e = e[e["valid"]]; e["day"] = d; ev_all.append(e)
    F = pd.concat(rows_all, ignore_index=True); E = pd.concat(ev_all, ignore_index=True)
    fac_cols = [c for c in F.columns if c not in ("ts", "mid", "bb", "ba", "valid", "hour", "day") and not c.startswith("dmid_")]
    res = {"n_rows": int(len(F)), "n_events": int(len(E)), "days": days, "factors": {}}
    lines = ["# 因子检验报告(Factor Report)", "",
             f"数据:KuCoin XBTUSDTM,{len(days)} 天({', '.join(days)}),状态行样本 {len(F):,},成交事件 {len(E):,}",
             f"(bid fill 事件 {int(E['is_bid_fill'].sum()):,},ask fill 事件 {int(E['is_ask_fill'].sum()):,})", "",
             "标签:dmid_h = 未来 h 后 mid 变动(bp);mk_h(bid) = 以成交前 bb 买入后 h 的 mid 相对成交价(bp,正=有利);mk_h(ask) 对称。",
             "IC = Spearman;mono = 十分位均值单调性;tb_t = 顶/底十分位差 t 值;stab = 逐日 IC 同号比例。", ""]
    # 无条件 mid 预测
    lines += ["## A. 因子 → 未来 mid 变动(无条件)", "", "| factor | " + " | ".join(f"IC {h}ms" for h in HORIZONS_MS) + " | mono@250 | tb_t@250 | stab@250 |", "|---|" + "---|" * (len(HORIZONS_MS) + 3)]
    for c in fac_cols:
        r = {"ic": {}, "mono": None}
        x = F[c].values.astype(np.float64)
        for h in HORIZONS_MS:
            r["ic"][h] = _ic(x, F[f"dmid_{h}ms"].values.astype(np.float64))[1]
        dq = _decile(x, F["dmid_250ms"].values.astype(np.float64))
        r["decile_250"] = dq
        ics = [_ic(F[F.day == d][c].values.astype(np.float64), F[F.day == d]["dmid_250ms"].values.astype(np.float64))[1] for d in days]
        ics = [v for v in ics if np.isfinite(v)]
        r["stab_250"] = (max(sum(v > 0 for v in ics), sum(v < 0 for v in ics)) / len(ics)) if ics else np.nan
        r["ic_by_day_250"] = ics
        res["factors"][c] = r
        lines.append(f"| {c} | " + " | ".join(f"{r['ic'][h]:+.3f}" if np.isfinite(r['ic'][h]) else "nan" for h in HORIZONS_MS)
                     + f" | {dq['mono'] if dq else 'nan'} | {dq['tb_t'] if dq else 'nan'} | {r['stab_250']:.2f} |")
    # fill-conditioned
    for side, flag, title in (("bid", "is_bid_fill", "B. E(Markout | Bid Fill, State)"), ("ask", "is_ask_fill", "C. E(Markout | Ask Fill, State)")):
        Es = E[E[flag]]
        lines += ["", f"## {title}", "", f"事件数 {len(Es):,};无条件均值 markout(bp):"
                  + ", ".join(f"{h}ms {Es[f'mk_{h}ms'].mean():+.3f}" for h in HORIZONS_MS), "",
                  "| factor | " + " | ".join(f"IC {h}ms" for h in HORIZONS_MS) + " | decile means@500ms (low→high) | mono | tb_t | stab |", "|---|" + "---|" * (len(HORIZONS_MS) + 4)]
        res[f"fill_{side}"] = {"n": int(len(Es)), "uncond": {h: float(Es[f"mk_{h}ms"].mean()) for h in HORIZONS_MS}, "factors": {}}
        for c in fac_cols:
            x = Es[c].values.astype(np.float64)
            r = {"ic": {h: _ic(x, Es[f"mk_{h}ms"].values.astype(np.float64))[1] for h in HORIZONS_MS}}
            dq = _decile(x, Es["mk_500ms"].values.astype(np.float64)); r["decile_500"] = dq
            ics = [_ic(Es[Es.day == d][c].values.astype(np.float64), Es[Es.day == d]["mk_500ms"].values.astype(np.float64))[1] for d in days]
            ics = [v for v in ics if np.isfinite(v)]
            r["stab_500"] = (max(sum(v > 0 for v in ics), sum(v < 0 for v in ics)) / len(ics)) if ics else np.nan
            res[f"fill_{side}"]["factors"][c] = r
            lines.append(f"| {c} | " + " | ".join(f"{r['ic'][h]:+.3f}" if np.isfinite(r['ic'][h]) else "nan" for h in HORIZONS_MS)
                         + f" | {dq['means'] if dq else 'nan'} | {dq['mono'] if dq else 'nan'} | {dq['tb_t'] if dq else 'nan'} | {r['stab_500']:.2f} |")
    # 逐日/逐时无条件 markout(bid/ask fill)
    lines += ["", "## D. 成交事件无条件 markout 逐日(bp, 500ms / 5s)", "", "| day | bid n | bid mk500 | bid mk5s | ask n | ask mk500 | ask mk5s | sweep 占比 |", "|---|---|---|---|---|---|---|---|"]
    for d in days:
        eb = E[(E.day == d) & E.is_bid_fill]; ea = E[(E.day == d) & E.is_ask_fill]
        lines.append(f"| {d} | {len(eb):,} | {eb['mk_500ms'].mean():+.3f} | {eb['mk_5000ms'].mean():+.3f} | {len(ea):,} | {ea['mk_500ms'].mean():+.3f} | {ea['mk_5000ms'].mean():+.3f} | {E[E.day == d]['sweep'].mean():.2%} |")
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    open(out_md, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    json.dump(res, open(out_md.replace(".md", ".json"), "w"), indent=1, default=float)
    print("\n".join(lines[:12]))
    print(f"... written {out_md}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "analyze"])
    ap.add_argument("--days", default="20251001,20260101,20260401,20260601,20260701,20260801")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "research", "factor_report.md"))
    ns = ap.parse_args()
    days = ns.days.split(",")
    if ns.cmd == "build":
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(ns.workers) as ex:
            for line in ex.map(build_day, days):
                print(line, flush=True)
    else:
        analyze(days, ns.out)


if __name__ == "__main__":
    main()
