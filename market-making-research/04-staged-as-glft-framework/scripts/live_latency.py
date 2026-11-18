#!/usr/bin/env python3
"""research7 下单 / 撤单延迟的经验分布(按交易所负载分档),来自 2026-10-02 实盘订单。

用途      阶段 0 验收 T0-2 发现"正常 1.5 ms / 拥堵 49.7 ms"的两点延迟模型与实盘偏差过大(撤单实际 2.5–16 ms,
          模型给 49.7 ms),按提示词"偏差过大时必须先修正回测器"改用实测分布。本文件从实盘日志与公开逐笔委托流
          量出每张单的 发单→进簿、发撤单→撤掉 的时间,连同发出那一刻的负载一起存下来。
所属阶段  阶段 0。不属于任何研究模块,不对应报价公式中的某一项(研究八"延迟度量"会复用这张表)。
量的定义  d_open   = 公开流里我方订单 open 的交易所时间 − 引擎发单时间(毫秒)
          d_cancel = 公开流里我方订单 done(canceled) 的交易所时间 − 引擎发撤单时间(毫秒)
          load     = 发出那一刻之前 100 毫秒内两个 BTC 合约的公开逐笔消息条数(l3_prep.Load)
          两个时钟:引擎时间是我方机器时钟,交易所时间精度 1 毫秒;两者之差实测 −0.04 ms(±0.8 ms),不校正。
          因此小于 0 的个别读数截到 0.1 ms。
用法      .venv/Scripts/python.exe scripts/research7/live_latency.py build
"""
import gzip
import os
import sys
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l3sim as L
import l3_prep as P
import live_recon as R

OUT = os.path.join(P.OUT, "latency_empirical.npz")
# 负载分档的边界(条 / 100 毫秒)。在看到分档结果之前定下:等距 250 一档,744 附近不单独设界;ASSUMPTION。
# 最后一档 ≥ 1500 合并(样本少)。
EDGES = (0, 250, 500, 750, 1000, 1500)
FLOOR_MS = 0.1     # 毫秒;时钟误差造成的非正读数截到这个值(ASSUMPTION,见文件头)


def build():
    ld = P.Load()
    rows_o, rows_c = [], []
    for sym in ("XBTUSDCM", "XBTUSDTM"):
        od = R.read_journal(sym)
        by_ex = {o["ex_id"].encode(): o for o in od.values() if o["ex_id"]}
        for hh in R.HOURS:
            f = os.path.join(L.L3_DIR[sym], R.DAY, f"{hh}_{sym}_l3.jsonl.gz")
            try:
                with gzip.open(f, "rb") as fh:
                    for line in fh:
                        is_open = b'"subject":"open"' in line
                        if not is_open and b'"reason":"canceled"' not in line:
                            continue
                        j = line.find(b'"orderId":"')
                        o = by_ex.get(line[j + 11:line.index(b'"', j + 11)])
                        if o is None:
                            continue
                        k = line.rfind(b'"ts":')
                        ts = int(line[k + 5:k + 24])                      # 交易所时间(纳秒)
                        if is_open:
                            rows_o.append((ld.count(o["t_send"]), (ts - o["t_send"]) / L.MS, o["t_send"]))      # 纳秒 → 毫秒;第三列留发出时刻
                        elif o["t_cancel"]:
                            rows_c.append((ld.count(o["t_cancel"]), (ts - o["t_cancel"]) / L.MS, o["t_cancel"]))
            except (EOFError, OSError, zlib.error):
                pass
    a, c = np.asarray(rows_o, float), np.asarray(rows_c, float)
    a[:, 1], c[:, 1] = np.maximum(a[:, 1], FLOOR_MS), np.maximum(c[:, 1], FLOOR_MS)
    np.savez(OUT, open=a[:, :2], cancel=c[:, :2], edges=np.asarray(EDGES))
    # 第二张表:负载改用"XBTUSDTM 的 L2 + 成交事件在过去 100 毫秒的条数"(8–9 月没有逐笔消息数,只有这个口径可用)。
    # 分档边界取这批样本负载的 20 / 40 / 60 / 80 / 95% 分位(等样本量分档;ASSUMPTION,只决定抽样池怎么切)。
    import l2sim as S2
    ev = np.load(os.path.join(P.OUT, "l2", f"XBTUSDTM_{R.DAY}.npz"))
    l2 = S2.L2Load(ev["ts"])
    lo = np.array([l2.count(int(t)) for t in a[:, 2]], float)
    lc = np.array([l2.count(int(t)) for t in c[:, 2]], float)
    e2 = np.r_[0.0, np.percentile(np.r_[lo, lc], (20, 40, 60, 80, 95))]
    np.savez(OUT.replace(".npz", "_l2load.npz"), open=np.c_[lo, a[:, 1]], cancel=np.c_[lc, c[:, 1]], edges=e2)
    print("按 L2 消息量分档:边界", np.round(e2, 0).tolist())
    for name, x in (("发单→进簿", np.c_[lo, a[:, 1]]), ("发撤单→撤掉", np.c_[lc, c[:, 1]])):
        for i, b0 in enumerate(e2):
            b1 = e2[i + 1] if i + 1 < len(e2) else np.inf
            m = (x[:, 0] >= b0) & (x[:, 0] < b1)
            if m.sum():
                print(f"   {name} L2 负载 [{b0:.0f}, {b1:.0f})  n {int(m.sum()):5d}   " + "  ".join(f"p{q} {np.percentile(x[m, 1], q):6.1f}" for q in (50, 90, 99)))
    q = (50, 75, 90, 95, 99)
    for name, x in (("发单→进簿", a), ("发撤单→撤掉", c)):
        print(f"{name}  n = {len(x):,}   全体分位(毫秒)" + "  ".join(f"p{p} {np.percentile(x[:, 1], p):.1f}" for p in q))
        for i, lo in enumerate(EDGES):
            hi = EDGES[i + 1] if i + 1 < len(EDGES) else np.inf
            m = (x[:, 0] >= lo) & (x[:, 0] < hi)
            if m.sum():
                print(f"   负载 [{lo}, {hi})  n {int(m.sum()):5d}   " + "  ".join(f"p{p} {np.percentile(x[m, 1], p):6.1f}" for p in q))
    print("LATENCY_BUILD_DONE", flush=True)


if __name__ == "__main__":
    build()
