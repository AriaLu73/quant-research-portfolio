"""适配层:只读引用 research_mm/src/adapters/engine.py 与引擎 scripts/research7/l3sim.py,按 config/contracts.yaml 注入合约常量。

裁决附录(2026-11-06)事实更正:ETHUSDCM 的 L3 目录映射"在适配层构造引擎前加入,不改引擎文件"。
注入的三个量都是引擎模块全局、调用时解析(l3sim.py:31-32 L3_DIR、:37 TICK、:38 MULT;to_tick :52-54 每次调用读 TICK),
所以补丁对引擎生效;代价是 TICK 只有一个值 → 一个进程只能服务一个合约(patch_engine 对第二个合约直接报错)。
"""
import os
import sys

import yaml

ROOT = r""
REPRO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "research_mm", "src", "adapters"), os.path.join(ROOT, "research_mm", "src", "analytics")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import engine as E      # noqa: E402  research_mm 的引擎适配(只读)

L, P = E.L, E.P
with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as _fh:
    CONTRACTS = yaml.safe_load(_fh)
_patched = None


def patch_engine(sym, l3_dir=None, trd_dir=None):
    """把 sym 的 L3 目录 / tick / 每张币数注入引擎模块。返回合约配置。l3_dir/trd_dir 可覆盖(9 月自录 L3 的 data/kucoin_l3*,附录第 5 条)。"""
    global _patched
    c = CONTRACTS[sym]
    if not c.get("l3_dir") and not l3_dir:
        raise SystemExit(f"{sym} 无 L3 数据(contracts.yaml status={c.get('status')}),不能构造引擎")
    if _patched not in (None, sym):
        raise RuntimeError(f"本进程已服务 {_patched};TICK 是引擎模块全局,换合约请另起进程")
    L.L3_DIR[sym] = l3_dir or c["l3_dir"]
    L.MULT[sym] = float(c["mult"])
    L.TICK = float(c["tick"])
    L.TRD_DIR = trd_dir or l3_dir or c["trd_dir"]
    _patched = sym
    return c


def days_of(sym):
    d = CONTRACTS[sym]["l3_dir"]
    out = []
    for x in sorted(os.listdir(d)):
        p = os.path.join(d, x)
        if x.isdigit() and len(x) == 8 and os.path.isdir(p) and any(f.endswith(f"_{sym}_l3.jsonl.gz") for f in os.listdir(p)):
            out.append(x)
    return out
