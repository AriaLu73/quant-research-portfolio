#!/usr/bin/env python3
"""research7 阶段 3 的数据准备:每天 100 毫秒网格上的盘口状态、订单流与币安参考价。只整理数据,不含任何预测模型。

用途      研究一(公允价格)要比较的参考价与短期信号,都从这张表计算。
所属阶段  阶段 3,研究一的"数据与特征"一步。
对应公式  为 F_t = S^ref_t + w_t·α̂_t(h) 准备输入。
输出      data/research7/feat/feat_<day>.npz(每个数组一行对应一个 100 毫秒网格点,记录该时刻"之前"的状态,只用过去的数据):
            t0        第一个网格点的时间(纳秒)
            bb, ba    买一、卖一(tick)
            qb, qa    买一、卖一的张数
            db5, da5, db20, da20   买一起向下 5 / 20 个 tick 内、卖一起向上 5 / 20 个 tick 内的总张数(多档深度)
            ofi       这个 100 毫秒内的订单流不平衡(张;Cont–Kukanov–Stoikov 的逐事件定义求和,见 _ofi)
            tb, ts_   这个 100 毫秒内吃单买入、吃单卖出的张数(不按盘口成交的打印已剔除)
            age       盘口已多久没有变化(秒)
          data/research7/feat/bn_<day>.npz(模式 bn):币安 BTCUSDT 永续逐笔成交在同一网格上的
            px        该 100 毫秒末之前最后一笔成交价(美元;按币安成交时间,未加任何延迟——使用时由调用方加上实测的行情延迟)
            buy, sell 该 100 毫秒内吃单买入、卖出的数量(BTC)
数据来源  KuCoin:data/research7/l2/XBTUSDTM_<day>.npz(l2_prep.py)。币安:data/research5/binance_hist/BTCUSDT-aggTrades-<日期>.zip
          (币安官方历史数据;用户 2026-10-06 允许 KuCoin 策略只读使用币安行情)。
自反性    研究一第 6 条要求剔除我方挂单与成交。这些是历史公开数据,期间我方没有在 XBTUSDTM 上持续挂单(10-02 的实盘对冲单共 23 张),不需要剔除;
          实盘时须从盘口数量里扣除自己的挂单(项目记录 memory uh-code-review:book_has_own)。
用法      .venv/Scripts/python.exe scripts/research7/feat_grid.py ku <YYYYMMDD>
          Python314/python.exe scripts/research7/feat_grid.py bn <YYYYMMDD>
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "research7", "feat")
STEP_NS = 100_000_000          # 网格间隔 100 毫秒(与 vol_grid.py 相同)
DEPTHS = (5, 20)               # 多档深度的范围(tick):ASSUMPTION。价差恒为 1 tick(0.1 美元),5 / 20 tick = 0.5 / 2 美元,
                               # 对应阶段 1 δ 网格最近的几档;更深的深度留待信号有效后再加


def ku(day, sym="XBTUSDTM"):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import l2sim as S
    import l3sim as L

    class Snap:
        """挂在仿真器上的"策略":不下单,只在每个 100 毫秒边界记录盘口状态,并累计区间内的订单流。"""

        def __init__(self):
            self.orders, self.rows = [], []
            self.g = None                       # 当前所在的网格序号
            self.prev = None                    # 上一次的 (bb, ba, qb, qa),用于 OFI
            self.ofi = self.tb = self.ts = 0.0
            self.last_change = 0

        def _ofi(self, cur):
            """订单流不平衡的逐事件贡献(Cont, Kukanov & Stoikov 2014 的定义;文献台账核对后登记编号):
            e = 1{Pb ≥ Pb'}·qb − 1{Pb ≤ Pb'}·qb' − 1{Pa ≤ Pa'}·qa + 1{Pa ≥ Pa'}·qa'(带撇为上一状态)。"""
            bb, ba, qb, qa = cur
            b0, a0, q0b, q0a = self.prev
            return (qb if bb >= b0 else 0) - (q0b if bb <= b0 else 0) - (qa if ba <= a0 else 0) + (q0a if ba >= a0 else 0)

        def on_event(self, sim, ts):
            bb, ba = sim.best(0), sim.best(1)
            if bb is None or ba is None or bb >= ba:
                return
            g = ts // STEP_NS
            if self.g is not None and g != self.g:
                # 进入新的网格区间:把上一区间结束时(本事件之前)的状态写一行,空缺的区间用同一状态补齐
                b0, a0, q0b, q0a = self.prev
                sz = sim.touch.size
                dep = [sum(sz[0].get(b0 - i, 0) for i in range(d)) for d in DEPTHS] + [sum(sz[1].get(a0 + i, 0) for i in range(d)) for d in DEPTHS]
                for k in range(self.g + 1, g + 1):
                    first = k == self.g + 1
                    self.rows.append((k, b0, a0, q0b, q0a, dep[0], dep[2], dep[1], dep[3],
                                      self.ofi if first else 0.0, self.tb if first else 0.0, self.ts if first else 0.0,
                                      (k * STEP_NS - self.last_change) / 1e9))
                self.ofi = self.tb = self.ts = 0.0
            self.g = g
            cur = (bb, ba, sim.touch.size[0][bb], sim.touch.size[1][ba])
            if self.prev is not None and cur != self.prev:
                self.ofi += self._ofi(cur)
                self.last_change = ts
            self.prev = cur

        def on_sweep(self, ts, side, sweep):
            q = sum(s for _, s, _ in sweep)
            if side == 1:
                self.tb += q                    # 打到卖盘 = 吃单买入
            else:
                self.ts += q

        def on_bbo(self, *a):
            pass

        def on_fill(self, *a):
            pass

        def on_break(self, sim, ts):
            self.prev = None
            self.g = None

    ev = np.load(os.path.join(ROOT, "data", "research7", "l2", f"{sym}_{day}.npz"))
    sn = Snap()
    sim = S.L2Sim(sym, L.Latency(), [sn], recorder=sn)
    # 第一行状态要等 prev 建好:on_event 里 prev 为 None 时只建立状态
    orig = sn.on_event

    def guarded(sim_, ts):
        if sn.prev is None:
            bb, ba = sim_.best(0), sim_.best(1)
            if bb is not None and ba is not None and bb < ba:
                sn.prev = (bb, ba, sim_.touch.size[0][bb], sim_.touch.size[1][ba])
                sn.g = ts // STEP_NS
                sn.last_change = ts
            return
        orig(sim_, ts)
    sn.on_event = guarded
    sim.run(ev)
    A = np.asarray(sn.rows, np.float64)
    os.makedirs(OUT, exist_ok=True)
    g = A[:, 0].astype(np.int64)
    np.savez_compressed(os.path.join(OUT, f"feat_{day}.npz"), g=g, bb=A[:, 1].astype(np.int32), ba=A[:, 2].astype(np.int32),
                        qb=A[:, 3].astype(np.float32), qa=A[:, 4].astype(np.float32), db5=A[:, 5].astype(np.float32), da5=A[:, 6].astype(np.float32),
                        db20=A[:, 7].astype(np.float32), da20=A[:, 8].astype(np.float32), ofi=A[:, 9].astype(np.float32),
                        tb=A[:, 10].astype(np.float32), ts_=A[:, 11].astype(np.float32), age=A[:, 12].astype(np.float32))
    print(f"feat {day}: {len(A):,} 行  网格序号是否连续 {bool(np.all(np.diff(g) >= 1))}  重置 {sim.breaks}  FEAT_DONE", flush=True)


def bn(day, sym="BTCUSDT"):
    """sym:币安 U 本位合约代码。BTCUSDT 的输出文件名保持 bn_<day>.npz(阶段 3–6 的脚本按这个名字读);其它品种写 bn_<sym>_<day>.npz。"""
    import zipfile
    import pandas as pd
    f = os.path.join(ROOT, "data", "research5", "binance_hist", f"{sym}-aggTrades-{day[:4]}-{day[4:6]}-{day[6:]}.zip")
    if not os.path.exists(f):
        print(f"bn {day}: 没有文件 {os.path.basename(f)}  BN_MISSING", flush=True)
        return
    with zipfile.ZipFile(f) as z:
        d = pd.read_csv(z.open(z.namelist()[0]))
    d.columns = [c.strip().lower() for c in d.columns]
    t = d["transact_time"].values.astype(np.int64)
    t = t * (1_000_000 if t[0] < 10**14 else 1000)          # 单位换算:毫秒(或微秒)→ 纳秒
    g = t // STEP_NS
    g0, g1 = int(g[0]), int(g[-1])
    n = g1 - g0 + 1
    px = np.full(n, np.nan)
    last = pd.Series(d["price"].values, index=g).groupby(level=0).last()
    px[last.index.values - g0] = last.values
    px = pd.Series(px).ffill().values                        # 没有成交的区间沿用之前的成交价(只用过去)
    qty = d["quantity"].values.astype(float)
    taker_buy = ~d["is_buyer_maker"].astype(bool).values     # is_buyer_maker = True 表示买方是挂单方 → 吃单方卖出
    buy = np.bincount(g[taker_buy] - g0, weights=qty[taker_buy], minlength=n)
    sell = np.bincount(g[~taker_buy] - g0, weights=qty[~taker_buy], minlength=n)
    os.makedirs(OUT, exist_ok=True)
    out_name = f"bn_{day}.npz" if sym == "BTCUSDT" else f"bn_{sym}_{day}.npz"
    np.savez_compressed(os.path.join(OUT, out_name), g0=g0, px=px.astype(np.float32), buy=buy.astype(np.float32), sell=sell.astype(np.float32))
    print(f"bn {sym} {day}: 成交 {len(d):,} 笔  网格 {n:,} 点  BN_DONE", flush=True)


if __name__ == "__main__":
    {"ku": ku, "bn": bn}[sys.argv[1]](*sys.argv[2:])
