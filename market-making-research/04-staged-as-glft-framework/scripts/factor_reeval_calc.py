#!/usr/bin/env python3
"""已有因子重评(用户 10-15:"你先重评再看需不需要新的因子")—— 第一步:把 RD-Agent 交来的全部因子在重评用的日子上算出来。

日子   第三轮交给 RD 的十天(实盘组回测成交所在的日子)+ 10-14(实盘)。每天 12–18 时 UTC(盘口网格只有这六小时)。
因子   RDAgent_Factor 下除毒性一轮以外的全部因子代码(毒性一轮已有 data/factors/tox1,直接用):
         Toxic/Toxic二轮(16 对)、未入选因子代码(毒性 4 对 + btc_lead_100ms、obi_l2to5)、Toxic/Toxic二轮_重写_新标签(adv_thinback)、
         根目录的中心因子(10 个)、宽度因子(wid_depletion_jump)、库存一轮新挖 8 轮(8 对)。
做法   拼一张与 hf_book.h5 同格式的表(字段是各批因子用到的并集:前五档价格和数量、成交量 / 笔数 / 最高最低成交价、价位更新条数、
       币安成交),原样导入每个因子文件、调用 calculate_<名字>(),只替换读写 h5 的两处。代码一个字不改。
输出   data/factors/reeval/<日>.npz,每个因子一个 (行数, 3) 数组,列 = BTC / ETH / SOL。
用法   Python314/python.exe scripts/research7/factor_reeval_calc.py <YYYYMMDD>
       Python314/python.exe scripts/research7/factor_reeval_calc.py all [并行数]
"""
import glob
import importlib.util
import os
import subprocess
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "research", "as2008"))
import toxicity_tox as TT                                           # noqa: E402  拼表(前五档 + 成交 + 币安)沿用它
import toxicity_rd8 as R8                                           # noqa: E402

RD = os.path.join(ROOT, "RDAgent_Factor")
DIRS = [os.path.join(RD, "Toxic", "Toxic二轮"), os.path.join(RD, "未入选因子代码"), os.path.join(RD, "Toxic", "Toxic二轮_重写_新标签"),
        RD, os.path.join(RD, "宽度因子"),
        os.path.join(RD, "Inventory", "库存因子一轮_run19_解压", "run19_库存补充_持仓情景_opus copy", "新挖8轮", "factors")]
OUT = os.path.join(ROOT, "data", "factors", "reeval")
DAYS = ("20260827", "20260828", "20260829", "20260830", "20260831", "20260901", "20260917", "20260918", "20260923", "20260924", "20261014")
STEP_NS = 10_000_000


def factor_files():
    out = []
    for d in DIRS:
        out += sorted(glob.glob(os.path.join(d, "*.py")))
    return out


def make_book(day):
    df = TT.make_book(day)                                          # 前五档、buy/sell_qty、buy_max_px、sell_min_px、币安五列
    n = len(df) // 3
    t0 = int(np.load(os.path.join(R8.GRID, "XBTUSDTM_%s.npz" % day))["t0"])
    extra = {c: np.zeros((n, 3)) for c in ("buy_cnt", "sell_cnt", "n_upd_bid", "n_upd_ask")}
    for j, (name, sym, mult) in enumerate(R8.INSTS):                # 补 rd8 那张表才有的四列,算法照 toxicity_rd8.make_book
        ev = np.load(os.path.join(R8.L2, "%s_%s.npz" % (sym, day)))
        ts, kind, side = ev["ts"], ev["kind"], ev["side"]
        i = -((t0 - ts) // STEP_NS)
        inr = (i >= 0) & (i < n)
        tr = inr & (kind == 0)
        buy, sell = tr & (side == 1), tr & (side == 0)
        extra["buy_cnt"][:, j] = np.bincount(i[buy], minlength=n)
        extra["sell_cnt"][:, j] = np.bincount(i[sell], minlength=n)
        up = inr & (kind == 1)
        extra["n_upd_bid"][:, j] = np.bincount(i[up & (side == 0)], minlength=n)
        extra["n_upd_ask"][:, j] = np.bincount(i[up & (side == 1)], minlength=n)
    for c, v in extra.items():
        df[c] = v.ravel()
    return df


def run_factor(path, book):
    name = os.path.basename(path)[:-3]
    spec = importlib.util.spec_from_file_location("rd_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = getattr(mod, "calculate_" + name)()
    if isinstance(res, pd.DataFrame):
        res = res.iloc[:, 0]
    return res.reindex(book.index).to_numpy(dtype="float64").reshape(-1, 3)


def calc(day):
    book = make_book(day)
    pd.read_hdf = lambda *a, **k: book.copy(deep=False)
    pd.DataFrame.to_hdf = lambda self, *a, **k: None
    pd.Series.to_hdf = lambda self, *a, **k: None
    _stack = pd.DataFrame.stack

    def stack(self, *a, **k):                                       # 本机 pandas 3 的 stack 不接受 dropna(同 toxicity_rd8)
        k.pop("dropna", None)
        return _stack(self, *a, **k)
    pd.DataFrame.stack = stack
    os.makedirs(OUT, exist_ok=True)
    out = {}
    for p in factor_files():
        name = os.path.basename(p)[:-3]
        t = time.time()
        try:
            out[name] = run_factor(p, book).astype(np.float32)
            print("%s %-40s 用时 %5.0f 秒  有值比例 %.2f" % (day, name, time.time() - t, np.isfinite(out[name]).mean()), flush=True)
        except Exception as ex:                                      # noqa: BLE001  一个因子出错不影响其它因子;错误照实记下
            print("%s %-40s 出错:%r" % (day, name, ex), flush=True)
    np.savez_compressed(os.path.join(OUT, "%s.npz" % day), **out)
    print("%s REEVAL_CALC_DONE %d 个因子" % (day, len(out)), flush=True)


def calc_all(par):
    todo = [d for d in DAYS if not os.path.exists(os.path.join(OUT, "%s.npz" % d))]
    procs = []
    while todo or procs:
        while todo and len(procs) < par:
            d = todo.pop(0)
            procs.append(subprocess.Popen([sys.executable, os.path.abspath(__file__), d], cwd=ROOT,
                                          env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=0x08000000))   # 不开窗口
        time.sleep(5)
        procs = [p for p in procs if p.poll() is None]
    print("REEVAL_CALC_ALL_DONE", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "all":
        calc_all(int(sys.argv[2]) if len(sys.argv) > 2 else 2)
    elif sys.argv[1] not in ("inv6", "inv6day"):
        calc(sys.argv[1])


# ---------------------------------------------------------------------------------------------------
# 补算(10-16):库存一轮里 6 个因子在本机 pandas 3 上报"assignment destination is read-only"——pandas 3 一律写时复制,
# Series.values 给的是只读数组,而这几个因子的代码会就地改这些数组。因子代码不改;只在调用它们时让 .values 返回一份可写的拷贝
# (它们只改自己的局部数组,不往表里写回,所以结果不受影响)。输出 data/factors/reeval/<日>_inv6.npz。
# 用法:Python314/python.exe scripts/research7/factor_reeval_calc.py inv6
INV6 = ("posa_favrun_short", "posa_thinahead_short", "posa_unretraced_short", "posb_bandimb_short", "posb_peergap_long", "posb_peergap_short")


def calc_inv6(day):
    book = make_book(day)
    pd.read_hdf = lambda *a, **k: book.copy(deep=False)
    pd.DataFrame.to_hdf = lambda self, *a, **k: None
    pd.Series.to_hdf = lambda self, *a, **k: None
    pd.Series.values = property(lambda self: np.array(self.to_numpy(), copy=True))
    out = {}
    for n in INV6:
        t = time.time()
        try:
            out[n] = run_factor(os.path.join(DIRS[-1], n + ".py"), book).astype(np.float32)
            print("%s %-30s 用时 %4.0f 秒  有值比例 %.2f" % (day, n, time.time() - t, np.isfinite(out[n]).mean()), flush=True)
        except Exception as ex:                                      # noqa: BLE001
            print("%s %-30s 出错:%r" % (day, n, ex), flush=True)
    np.savez_compressed(os.path.join(OUT, "%s_inv6.npz" % day), **out)


if __name__ == "__main__" and sys.argv[1] == "inv6":
    for d in DAYS:
        if not os.path.exists(os.path.join(OUT, "%s_inv6.npz" % d)):
            subprocess.run([sys.executable, os.path.abspath(__file__), "inv6day", d], cwd=ROOT, creationflags=0x08000000)
    print("INV6_ALL_DONE", flush=True)
if __name__ == "__main__" and sys.argv[1] == "inv6day":
    calc_inv6(sys.argv[2])
