#!/usr/bin/env python3
"""research7 阶段 4:把联合估计选出的"每笔净值为正的状态"存成门限,供回放使用。

用途      联合估计(as_study.py)在训练段选出的格子全部落在:距离 0(加入最优价)、σ_t 最低三分位、朝向我方一侧的不平衡不低于第 40 百分位。
          这里把两个门限(只用训练段)写成文件。
所属阶段  阶段 4(研究二、三的第 7 步"接入方式")。
对应公式  c^AS(X_t):在门限内的状态,估计的每笔净值为正 → 该侧报价贴到最优价;其余状态不改动基准报价。
输出      data/research7/as/gate.json:sig_max(bp/√秒)、imb_min(朝向我方一侧的不平衡下限)
用法      .venv/Scripts/python.exe scripts/research7/as_gate.py
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import as_study as A
import calib as C

TR = A.load(C.TRAIN_DAYS)
gate = dict(sig_max=float(np.quantile(TR["sig"], 1 / 3)), imb_min=float(np.quantile(TR["imb_s"], 0.4)))
json.dump(gate, open(os.path.join(A.OUT, "gate.json"), "w"), indent=1)
print(gate)
