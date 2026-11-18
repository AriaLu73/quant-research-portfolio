#!/usr/bin/env python3
"""research7 阶段 0:逐笔委托两天(10-01、10-02)在 8–9 月参照分布里处于什么位置(预登记 4.3)。

用途      回答"测试期是否覆盖高波动时段、低流动性时段"。按小时算两个量,与 8–9 月 20 天的同一量比分位:
          rv   小时已实现波动(bp):该小时内中间价每 1 秒对数收益的平方和开根号
          usd  小时成交额(美元):逐笔成交的 价格 × 数量 之和
所属阶段  阶段 0;不属于研究模块,不对应报价公式中的某一项。
数据      10 月:data/research7/market/XBTUSDTM_<day>_<hh>.npz(本研究从逐笔委托重建的买一卖一与吃单)
          8–9 月:购买的逐笔成交 data/trades/2026/<mm>/<dd>/XBTUSDTM.csv.gz(成交价每秒最后一笔当作价格;没有用盘口)
          两边价格口径不同(中间价 对 成交价):成交价含买卖价反弹,会把 8–9 月的 rv 略微抬高;BTC 点差约 0.012 bp,影响可忽略。
用法      Python314/python.exe scripts/research7/coverage_check.py
"""
import glob, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NS = 10**9
MULT, TICK = 0.001, 0.1          # BTC / 张、美元 / tick(KuCoin 合约接口存档 2026-10-02)


def rv_bp(t_ns, px):
    """每 1 秒取最后一个价格,对数收益平方和开根号,× 1e4 → bp。只在一个小时内部计算。"""
    s = pd.Series(px, index=t_ns // NS).groupby(level=0).last()
    r = np.diff(np.log(s.values))
    return float(np.sqrt(np.sum(r * r)) * 1e4)


rows = []
for f in sorted(glob.glob(os.path.join(ROOT, "data", "trades", "2026", "*", "*", "XBTUSDTM.csv.gz"))):
    d = pd.read_csv(f, usecols=["timestamp", "price", "amount"])
    d["h"] = d.timestamp // (3600 * 10**6)                       # 时间戳单位微秒 → 小时序号
    for h, g in d.groupby("h"):
        rows.append(("ref", h, rv_bp(g.timestamp.values * 1000, g.price.values), float((g.price * g.amount).sum()) * MULT))   # amount 的单位是张(样本核对:单笔 6、25),× MULT → BTC
for f in sorted(glob.glob(os.path.join(ROOT, "data", "research7", "market", "XBTUSDTM_*.npz"))):
    z = np.load(f)
    b, sw = z["bbo"], z["sw"]
    if len(b) < 100:
        continue
    mid = (b[:, 1] + b[:, 2]) / 2 * TICK
    usd = float(np.sum(sw[:, 2] * MULT * sw[:, 3] * TICK)) if len(sw) else 0.0
    rows.append((os.path.basename(f)[9:20], int(b[0, 0] // (3600 * NS)), rv_bp(b[:, 0], mid), usd))
D = pd.DataFrame(rows, columns=["src", "h", "rv", "usd"])
ref = D[D.src == "ref"]
print(f"参照(8–9 月逐笔成交):{len(ref)} 个小时;rv 分位 10/50/90/99% = " + " / ".join(f"{ref.rv.quantile(q):.1f}" for q in (.1, .5, .9, .99))
      + " bp;成交额分位 10/50/90% = " + " / ".join(f"${ref.usd.quantile(q) / 1e6:.2f}M" for q in (.1, .5, .9)))
oct_ = D[D.src != "ref"].copy()
oct_["rv_pct"] = [(ref.rv < x).mean() for x in oct_.rv]
oct_["usd_pct"] = [(ref.usd < x).mean() for x in oct_.usd]
pd.set_option("display.width", 200)
print(oct_.to_string(index=False, formatters={"rv": "{:.1f}".format, "usd": "{:,.0f}".format, "rv_pct": "{:.0%}".format, "usd_pct": "{:.0%}".format}))
print(f"10 月小时数 {len(oct_)};rv 在参照 90% 分位以上的 {int((oct_.rv_pct >= .9).sum())} 个;成交额在参照 10% 分位以下的 {int((oct_.usd_pct <= .1).sum())} 个")
