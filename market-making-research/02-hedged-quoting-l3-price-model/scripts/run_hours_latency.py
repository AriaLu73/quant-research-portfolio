#!/usr/bin/env python3
"""research3:按实测下单延迟做回测敏感性(2026-10-02)。scripts/research5/run_hours.py 的延迟是写死的 1.8 ms(当时的假设);
10-02 在 colo 机上用统一账户通道实测:下单往返中位 4.6 ms、90% 分位 23 ms、最大 68 ms(20 张),撤单中位 4.5 ms。
本脚本不改 run_hours.py,只在调用前把它的延迟常量换成命令行给的值,其余完全相同。
用法:python scripts/research3/run_hours_latency.py <延迟毫秒> --tag T --strategy ... --params ... --manifest ...(其余参数同 run_hours.py)"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research5"))
import run_hours as RH

RH.COLO_LATENCY_NS = int(float(sys.argv[1]) * 1_000_000)
sys.argv = [sys.argv[0]] + sys.argv[2:]
print("latency_ns", RH.COLO_LATENCY_NS, flush=True)
RH.main()
