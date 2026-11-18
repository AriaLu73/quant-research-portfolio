#!/usr/bin/env python3
"""Quote Economics(prompt §12/§15):挂单 → 成交概率 × 成交后净收益。

对训练日每隔 1s 采样一次"在当前最优买价 bb 挂 S BTC 的被动单"(与卖侧对称),
用 QueuePositionEstimator(ESTIMATED)前推:
  - 入队时前方量 Q = 该档公开量(队尾假设);
  - 同价位后续卖方主动成交量按量推进;同价位撤单减量按 cancel_bias=0.5 归因为前方(与回测引擎一致);
  - 推进量 ≥ Q + S 视为全额成交(成交时间 = 达到该阈值的成交行);
  - 该档被吃穿/撤空(bb 跌到 P 以下):我方成为该价位唯一挂单,下一笔卖方主动成交即成交;
  - bb 上移(有人在我们前面插价):按"跟盘口重挂"处理,视为撤单(censored);
  - 时限 T 内未成交 = 未成交。
输出:按状态分桶的 P(fill)、E(markout|fill)、QuoteEV = P(fill) × (markout + rebate) → docs/research/quote_econ.md
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KU = os.path.join(ROOT, "data", "research", "kucoin")
FOUT = os.path.join(ROOT, "data", "research", "factors")
US = 1000
REBATE_BP = OUR_FEE          # 项目配置 config/backtest/glft_kucoin_colo.yaml: maker OUR_FEE
CANCEL_BIAS = 0.5


def simulate_side(day: str, side: str, S: float, T_ms: int, sample_ms: int, F: pd.DataFrame, tr: pd.DataFrame):
    ts = F["ts"].values.astype(np.int64); n = len(ts)
    mid = F["mid"].values.astype(np.float64)
    px = (F["bb"] if side == "bid" else F["ba"]).values.astype(np.float64)
    q1 = (F["bq1"] if side == "bid" else F["aq1"]).values.astype(np.float64)
    valid = F["valid"].values
    # 同价位段
    chg = np.r_[True, px[1:] != px[:-1]]
    seg = np.cumsum(chg) - 1
    seg_end = np.empty(n, dtype=np.int64)          # 段内最后一行下标
    last = np.r_[np.nonzero(chg)[0][1:] - 1, n - 1]
    seg_end = last[seg]
    # 行级推进量:区间 (ts_{i-1}, ts_i] 内同侧主动成交量(bid 侧 = 卖方主动;价 ≤ P 即打到该档)
    tts = tr["ts"].values.astype(np.int64); tside = tr["side"].values; tqty = tr["qty"].values.astype(np.float64)
    tpx = tr["price"].values.astype(np.float64)
    aggr = (tside == -1) if side == "bid" else (tside == 1)
    cum_t = np.r_[0.0, np.cumsum(np.where(aggr, tqty, 0.0))]
    pts = np.r_[ts[0] - 1, ts[:-1]]
    j0 = np.searchsorted(tts, pts, side="right"); j1 = np.searchsorted(tts, ts, side="right")
    tv = cum_t[j1] - cum_t[j0]
    dq = np.r_[0.0, np.diff(q1)]
    same = ~chg
    cancel = np.where(same, np.maximum(0.0, -dq - tv), 0.0)
    adv = np.where(same, tv + CANCEL_BIAS * cancel, 0.0)
    cumA = np.cumsum(adv)
    # 采样挂单时刻
    grid = np.arange(ts[0] + 60_000_000, ts[-1] - (T_ms + 60_000) * US, sample_ms * US)
    p = np.searchsorted(ts, grid, side="right") - 1
    p = p[(p >= 0) & valid[p] & (q1[p] > 0)]
    P = px[p]; Q = q1[p]; t0 = ts[p]
    # 队列推进成交:cumA[i] - cumA[p] >= Q + S,且 i <= seg_end[p]
    target = cumA[p] + Q + S
    i_fill = np.searchsorted(cumA, target, side="left")
    i_fill = np.minimum(i_fill, n - 1)
    by_queue = (i_fill <= seg_end[p]) & (ts[i_fill] - t0 <= T_ms * US)
    # 段结束后:价位消失方向
    e = seg_end[p]
    nxt = np.minimum(e + 1, n - 1)
    went_away = (px[nxt] < P) if side == "bid" else (px[nxt] > P)     # 档位被吃穿/撤空 → 我方成唯一挂单
    # 唯一挂单后首笔同侧主动成交
    aggr_ts = tts[aggr]
    k = np.searchsorted(aggr_ts, ts[nxt], side="left")
    k = np.minimum(k, len(aggr_ts) - 1)
    t_alone_fill = aggr_ts[k]
    by_alone = (~by_queue) & went_away & (t_alone_fill - t0 <= T_ms * US) & (k < len(aggr_ts))
    filled = by_queue | by_alone
    t_fill = np.where(by_queue, ts[i_fill], np.where(by_alone, t_alone_fill, -1))
    sgn = 1.0 if side == "bid" else -1.0
    out = {"row": p, "ts": t0, "price": P, "Q": Q, "filled": filled, "by_queue": by_queue, "by_alone": by_alone,
           "t_to_fill_ms": np.where(filled, (t_fill - t0) / US, np.nan)}
    for h in (500, 5000, 30000):
        kk = np.searchsorted(ts, t_fill + h * US, side="left")
        kk = np.minimum(kk, n - 1)
        out[f"mk_{h}ms"] = np.where(filled, sgn * (mid[kk] - P) / P * 1e4, np.nan)
    # 未成交情形的机会成本参考:挂单后 T 时 mid 相对 P(未成交 = 价格走远 or 队列没推进)
    kk = np.minimum(np.searchsorted(ts, t0 + T_ms * US, side="left"), n - 1)
    out["dmid_T"] = sgn * (mid[kk] - P) / P * 1e4
    df = pd.DataFrame(out)
    df["side"] = side; df["day"] = day
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="20251001,20260101,20260401")
    ap.add_argument("--size", type=float, default=0.15)       # ≈ $10k
    ap.add_argument("--T", type=int, default=30000)
    ap.add_argument("--sample-ms", type=int, default=1000)
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "research", "quote_econ.md"))
    ns = ap.parse_args()
    parts = []
    for d in ns.days.split(","):
        F = pq.read_table(os.path.join(FOUT, f"{d}.parquet")).to_pandas()
        tr = pq.read_table(os.path.join(KU, f"trades_{d}.parquet")).to_pandas()
        fac = ["imb1", "imb5", "spread_ticks", "bq1", "aq1", "ofi_500ms", "ofi_1000ms", "tflow_1000ms", "tflow_5000ms",
               "timb_5000ms", "tint_1000ms", "cancel_imb_2000ms", "qdepl_imb_1000ms", "ret_1000ms", "ret_5000ms",
               "vol_10000ms", "depth_chg_1s", "vpin", "tcluster_100ms", "t_since_trade_ms", "hour"]
        fac = [c for c in fac if c in F.columns]
        for side in ("bid", "ask"):
            df = simulate_side(d, side, ns.size, ns.T, ns.sample_ms, F, tr)
            for c in fac:
                df[c] = F[c].values[df["row"].values]
            # 方向对齐:sgn 因子 = 对本侧有利为正(bid: imb>0 好;ask: -imb>0 好)
            s = 1.0 if side == "bid" else -1.0
            for c in ("imb1", "imb5", "ofi_500ms", "ofi_1000ms", "tflow_1000ms", "tflow_5000ms", "timb_5000ms",
                      "cancel_imb_2000ms", "qdepl_imb_1000ms", "ret_1000ms", "ret_5000ms"):
                if c in df.columns:
                    df[c + "_al"] = s * df[c]
            df["q_own"] = np.where(side == "bid", df["bq1"], df["aq1"])
            df["q_opp"] = np.where(side == "bid", df["aq1"], df["bq1"])
            parts.append(df)
        print(d, "done", flush=True)
    D = pd.concat(parts, ignore_index=True)
    D.to_parquet(os.path.join(FOUT, "quote_econ_samples.parquet"))
    L = ["# Quote Economics(挂盘口被动单的成交概率与成交后经济)", "",
         f"样本:{', '.join(ns.days.split(','))};每 {ns.sample_ms}ms 采样一次挂单,单量 {ns.size} BTC,时限 {ns.T/1000:.0f}s;"
         f"队列位置估计 = ESTIMATED(队尾入队,撤单归因 {CANCEL_BIAS});返费 {REBATE_BP}bp(项目 我方费率档 配置)。", "",
         f"总样本 {len(D):,};P(fill) = {D['filled'].mean():.3f}(队列推进 {D['by_queue'].mean():.3f},档位消失后独挂 {D['by_alone'].mean():.3f});"
         f"成交时间中位 {D.loc[D.filled, 't_to_fill_ms'].median():.0f}ms", "",
         "无条件 E(markout|fill) bp:" + ", ".join(f"{h}ms {D.loc[D.filled, f'mk_{h}ms'].mean():+.3f}" for h in (500, 5000, 30000)),
         f";未成交样本 T 时 mid 相对挂价 {D.loc[~D.filled, 'dmid_T'].mean():+.3f}bp(正 = 价格远离,错过的是有利成交)", ""]
    def table(col, q=10, label=None):
        x = D[col].values
        try:
            b = pd.qcut(x, q, labels=False, duplicates="drop")
        except Exception:
            return []
        g = D.assign(b=b).groupby("b")
        rows = ["", f"### 按 {label or col} 分位", "", "| bin | range | n | P(fill) | P(queue) | E[mk 500ms|fill] | E[mk 5s|fill] | E[mk 30s|fill] | net/fill 5s (+rebate) | QuoteEV 5s (bp×P) | 未成交 dmid_T |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for bi, gg in g:
            f = gg[gg.filled]
            pf = gg["filled"].mean(); m5 = f["mk_5000ms"].mean()
            rows.append(f"| {bi} | {gg[col].min():+.3g}..{gg[col].max():+.3g} | {len(gg):,} | {pf:.3f} | {gg['by_queue'].mean():.3f} | {f['mk_500ms'].mean():+.3f} | {m5:+.3f} | {f['mk_30000ms'].mean():+.3f} | {m5 + REBATE_BP:+.3f} | {pf * (m5 + REBATE_BP):+.4f} | {gg.loc[~gg.filled, 'dmid_T'].mean():+.3f} |")
        return rows
    for c, lab in (("imb1_al", "L1 失衡(本侧有利为正)"), ("imb5_al", "5 档失衡(对齐)"), ("q_own", "本侧顶档量 Q(BTC)"), ("q_opp", "对侧顶档量"),
                   ("ofi_1000ms_al", "OFI 1s(对齐)"), ("tflow_5000ms_al", "主动流 5s(对齐)"), ("timb_5000ms_al", "成交失衡 5s(对齐)"),
                   ("cancel_imb_2000ms_al", "撤单失衡 2s(对齐)"), ("qdepl_imb_1000ms_al", "队列耗尽失衡 1s(对齐)"),
                   ("ret_5000ms_al", "5s 收益(对齐)"), ("vol_10000ms", "10s 波动"), ("tint_1000ms", "1s 成交笔数"), ("vpin", "VPIN"),
                   ("spread_ticks", "价差 tick"), ("hour", "小时(UTC)")):
        if c in D.columns:
            L += table(c, q=(24 if c == "hour" else 10), label=lab)
    # 逐日
    L += ["", "## 逐日", "", "| day | side | n | P(fill) | E[mk 5s|fill] | net/fill | QuoteEV |", "|---|---|---|---|---|---|---|"]
    for (d, s), gg in D.groupby(["day", "side"]):
        f = gg[gg.filled]; m5 = f["mk_5000ms"].mean(); pf = gg["filled"].mean()
        L.append(f"| {d} | {s} | {len(gg):,} | {pf:.3f} | {m5:+.3f} | {m5 + REBATE_BP:+.3f} | {pf * (m5 + REBATE_BP):+.4f} |")
    open(ns.out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:8]))


if __name__ == "__main__":
    main()
