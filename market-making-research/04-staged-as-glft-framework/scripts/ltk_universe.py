#!/usr/bin/env python3
"""research7 宽价差合约:在 KuCoin 全部合约里筛"还有哪些品种可以用同一套做法"(只读成交文件,不建盘口,不回放)。

用途      用户 2026-10-09:"别的品种呢,没办法赚更多钱了吗"。定版策略靠两样东西:价差至少两跳(才能挂到别人前面)、
          币安有同名永续(公允价)。本脚本用 9 月四个全合约日的逐笔成交,给每个合约算这两样的代理指标与成交额,列出候选。
所属阶段  阶段 8 探针的补充(选品);不对应报价公式中的某一项。
指标      usd      日均成交额(美元)= Σ 价格 × 张数 × 合约乘数 / 天数
          spr_tk   价差代理(跳):相邻两笔吃单方向相反的成交,价格之差的绝对值的中位数 / 一跳
                   (买方吃单成交在卖一、卖方吃单成交在买一,方向一换价格差约等于价差;这是代理,不是盘口价差)
          spr_bp   同上,以 bp 计
          tick_bp  一跳的 bp
          n        日均成交笔数
筛选      币安有同名 U 本位永续(data/research7/bn_raw/um_symbols.txt);spr_tk ≥ 2;日均成交额 ≥ MIN_USD。
数据来源  data/trades/2026/09/<dd>/<合约>.csv.gz(购买的 Tardis 成交;timestamp 微秒,amount 张);
          规格 data/research5/kucoin_contracts_20261002.json(一跳、乘数)。
用法      Python314/python.exe scripts/research7/ltk_universe.py
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAYS = ("10", "18", "21", "24")
MIN_USD = 300_000.0                # ASSUMPTION:日均成交额下限。已回放的 8 个合约里最小的是 XAUT / SPY 一档(每天约 $60–150 万)
OUT = os.path.join(ROOT, "data", "research7", "ltk_live")


def main():
    spec = {c["symbol"]: (float(c["tickSize"]), float(c["multiplier"])) for c in
            json.load(open(os.path.join(ROOT, "data", "research5", "kucoin_contracts_20261002.json"), encoding="utf8"))}
    um = set(open(os.path.join(ROOT, "data", "research7", "bn_raw", "um_symbols.txt")).read().split())
    rows = []
    syms = sorted(s for s in spec if s.endswith("USDTM"))
    for sym in syms:
        tick, mult = spec[sym]
        if mult <= 0:
            continue
        usd, n, dp, px = 0.0, 0, [], []
        nd = 0
        for d in DAYS:
            f = os.path.join(ROOT, "data", "trades", "2026", "09", d, sym + ".csv.gz")
            if not os.path.exists(f):
                continue
            try:
                t = pd.read_csv(f, usecols=["side", "price", "amount"])
            except Exception:  # noqa: BLE001 - 个别文件损坏:跳过这一天
                continue
            if len(t) < 50:
                continue
            nd += 1
            p = t.price.values.astype(float)
            usd += float((p * t.amount.values * mult).sum())
            n += len(t)
            b = (t.side.values == "buy")
            flip = b[1:] != b[:-1]
            dp.append(np.abs(np.diff(p))[flip])
            px.append(np.median(p))
        if not nd:
            continue
        dp = np.concatenate(dp)
        if not len(dp):
            continue
        m = float(np.median(px))
        s_tk = float(np.median(dp)) / tick
        rows.append((sym, usd / nd, n / nd, s_tk, s_tk * tick / m * 1e4, tick / m * 1e4, sym[:-1] in um, nd))
    df = pd.DataFrame(rows, columns=["sym", "usd", "n", "spr_tk", "spr_bp", "tick_bp", "binance", "days"])
    os.makedirs(OUT, exist_ok=True)
    df.to_csv(os.path.join(OUT, "universe_screen.csv"), index=False)
    print("有成交数据的 USDT 合约 %d 个;币安有同名永续 %d 个" % (len(df), int(df.binance.sum())))
    for lab, q in (("价差代理 ≥ 2 跳", df.spr_tk >= 2), ("且币安有同名", (df.spr_tk >= 2) & df.binance),
                   ("且日均成交额 ≥ $%.0f 万" % (MIN_USD / 1e4), (df.spr_tk >= 2) & df.binance & (df.usd >= MIN_USD))):
        print("  %s:%d 个,日均成交额合计 $%s" % (lab, int(q.sum()), format(round(df.usd[q].sum()), ",")))
    c = df[(df.spr_tk >= 2) & df.binance & (df.usd >= MIN_USD)].sort_values("usd", ascending=False)
    print("%-16s %12s %8s %7s %7s %8s" % ("合约", "日均成交额$", "笔/天", "价差跳", "价差bp", "一跳bp"))
    for r in c.itertuples():
        print("%-16s %12.0f %8.0f %7.1f %7.2f %8.3f" % (r.sym, r.usd, r.n, r.spr_tk, r.spr_bp, r.tick_bp))


if __name__ == "__main__":
    main()
