#!/usr/bin/env python3
"""research7 研究一:把离线筛选选中的公允价格调整量存成一张表,供回放使用。

用途      α̂(10 秒)= E[未来 10 秒中间价变动 | 买一卖一不平衡所在的十分位](bp),只用训练段估计(微观价格的条件均值形式)。
          同时在验证段上量校准斜率 b(实际变动对 α̂ 的回归斜率):b 就是信号收缩权重 w 的数据估计(提示词:w_t 不预设为 1)。
所属阶段  阶段 3,研究一第 7 步(接入方式)。
对应公式  F_t = S_t · (1 + w · α̂_t / 1e4),替换保留价中的 S_t。
输出      data/research7/feat/micro_table.json:edges(9 个分桶边界)、alpha_bp(10 个桶的调整量)、w(校准斜率,截断到 [0, 1])
用法      Python314/python.exe scripts/research7/fair_table.py
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fair_study as F

H = F.H_MAIN
TR, VA = F.stack(F.TRAIN), F.stack(F.VALID)
x, y = TR["imb1"], TR[f"y_{H}"]
m = np.isfinite(x) & np.isfinite(y)
edges = np.quantile(x[m], np.linspace(0, 1, F.N_BUCKET + 1)[1:-1])
b = np.digitize(x[m], edges)
alpha = np.array([y[m][b == i].mean() for i in range(F.N_BUCKET)])
# 验证段校准:实际变动 = b · α̂ + 误差(过原点最小二乘);按小时分块给出标准误
xv, yv, hv = VA["imb1"], VA[f"y_{H}"], VA["hour"]
k = np.isfinite(xv) & np.isfinite(yv)
pred = alpha[np.digitize(xv[k], edges)]
slope = float(pred @ yv[k] / (pred @ pred))
per = [float(pred[hv[k] == h] @ yv[k][hv[k] == h] / (pred[hv[k] == h] @ pred[hv[k] == h])) for h in np.unique(hv[k])]
se = float(np.std(per, ddof=1) / np.sqrt(len(per)))
w = float(min(max(slope, 0.0), 1.0))
json.dump(dict(edges=edges.tolist(), alpha_bp=alpha.tolist(), w=w, slope=slope, slope_se=se, horizon_s=H),
          open(os.path.join(F.FEAT, "micro_table.json"), "w"), indent=1)
print("分桶边界(不平衡):", np.round(edges, 3).tolist())
print("调整量 bp:", np.round(alpha, 3).tolist())
print(f"验证段校准斜率 {slope:.3f}(按小时的标准误 {se:.3f})→ w = {w:.3f}")
