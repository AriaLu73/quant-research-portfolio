#!/usr/bin/env python3
"""MIDCAP-3(阶段 8 延迟、阶段 10 归因):候选合约 × mode × 延迟 的 7 日回放汇总。
延迟规则见 touch_mm_replay.replay():成交后同侧 lat 内不再成交;盘口价刚变 lat 内不成交。归因 = 教材第 27 章恒等式。"""
import os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
f = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "research3", "touch_mm_replay_cap3_lat.csv")
R = pd.read_csv(f)
if "error" in R:
    R = R[R.error.isna()]
R["day"] = R.day.astype(str)
pd.set_option("display.width", 250)
g = R.groupby(["sym", "mode", "lat_ms"]).agg(net=("net", "sum"), pos_days=("net", lambda x: int((x > 0).sum())), days=("net", "size"), worst=("net", "min"),
                                               vol_day=("vol", "mean"), spread=("attr_spread", "sum"), adverse5=("attr_adverse5", "sum"),
                                               holding=("attr_holding", "sum"), rebate=("rebate", "sum"), check=("attr_check", lambda x: float(np.abs(x).max()))).reset_index()
g["net_bp"] = g.net / (g.vol_day * g.days) * 1e4
for mode in ("touch", "penny"):
    x = g[g["mode"] == mode]
    print(f"\n=== mode {mode}: 7 日合计净利 $(行 = 合约,列 = 延迟 ms)===")
    print(x.pivot(index="sym", columns="lat_ms", values="net").round(0).to_string())
    print(f"--- 正收益天数 / 7 ---")
    print(x.pivot(index="sym", columns="lat_ms", values="pos_days").to_string())
    print(f"--- 日均成交额 $ ---")
    print(x.pivot(index="sym", columns="lat_ms", values="vol_day").round(0).to_string())
print("\n=== 归因(lat 3 ms,7 日合计 $):价差捕获 / 逆向选择 5s / 持有 / 返佣 / 净 / 恒等式残差 ===")
a = g[g.lat_ms == 3.0][["sym", "mode", "spread", "adverse5", "holding", "rebate", "net", "net_bp", "check"]]
print(a.to_string(index=False, float_format=lambda v: f"{v:,.1f}"))
