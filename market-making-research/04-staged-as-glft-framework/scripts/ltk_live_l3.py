#!/usr/bin/env python3
"""research7 宽价差合约:实盘策略类 MM_LTK_PROBE_v1(定版)在 2026-10-01 逐笔委托数据上回放——真实排队位置。

用途      用户 2026-10-11:"用 L3 模拟的话我们那个策略一天多少钱"。此前逐笔委托回放(ltk_l3.py)跑的是研究脚本里的规则副本、
          每单 $2,000、不设任何上限;8–9 月的回放(ltk_live_replay.py)跑的是实盘策略类,但排队是按 L2 推断的。
          本文件把两者合起来:实盘策略类 + 逐笔委托的真实排队(l3sim.L3Sim)。
所属阶段  阶段 8 探针的补充检验。
对应公式  策略文件头的规则;本文件不含报价逻辑(适配层复用 ltk_live_replay.LiveAgent)。
方案      t20 = 定版(每单 = 上限 = $200,第一版离场,TTL 20 秒,原下单频率上限);u2k = 同上但 $2,000;
          c2k = $2,000 且放开下单频率上限(每秒 5 / 每 10 秒 30 / 每天 20 万)。同一延迟种子,各自独立排队。
撮合口径  l3sim.L3Sim:按订单号逐笔重建队列;成交价与挂单价不一致的打印(成对打印)不分给我方;我方订单不进公开盘口、
          别人不对我方报价作反应(H2)。延迟:10-02 实盘实测分布 + 行情到达抖动;币安成交到达延迟 24 ms。
          与 L2 回放的一处差别:这里没有插入"币安价变化"的唤醒事件,策略只在 KuCoin 有消息时决策(逐笔委托消息很密,影响小)。
数据      data/research4/l3_raw/20261001(自采,约 13 小时,自 13:35 UTC);币安 data/research7/ltk_live/bn_<合约>_20261001.npz。
输出      data/research7/ltk_live_l3/<合约>_<方案>.npz / .json(格式同 ltk_live_replay.py)。
用法      .venv/Scripts/python.exe scripts/research7/ltk_live_l3.py run <合约>
          .venv/Scripts/python.exe scripts/research7/ltk_live_l3.py all [并行数]
          .venv/Scripts/python.exe scripts/research7/ltk_live_l3.py report
"""
import contextlib
import glob
import io
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import l3_prep as P
import l3sim as L
import ltk_live_replay as R
import ltk_screen as SC

DAY = "20261001"
RAW = os.path.join(R.ROOT, "data", "research4", "l3_raw")
FRESH_MS = float(os.environ.get("LTK_FRESH_MS", "0") or 0)     # > 0:进簿不到这么多毫秒就被打到的挂单的成交不分给我方(见 l3sim.fresh_ns)
OUT = os.path.join(R.ROOT, "data", "research7", "ltk_live_l3" + ("_fresh%d" % FRESH_MS if FRESH_MS > 0 else ""))
NAMES = ("t20", "u2k", "c2k")
LABEL = {"t20": "$200(定版)", "u2k": "$2,000", "c2k": "$2,000 放开频率上限"}
POOL = ("BZUSDTM", "PAXGUSDTM", "XAUTUSDTM", "CRCLUSDTM", "IONQUSDTM", "AMDUSDTM", "SPCXUSDTM", "SPYUSDTM")   # 定版合约池
SEED = 81                          # 同 ltk_l3.py


def symbols():
    return sorted({os.path.basename(f).split("_")[1] for f in glob.glob(os.path.join(RAW, DAY, "??_*_l3.jsonl.gz"))})


def run(sym):
    fb = os.path.join(R.OUT, "bn_%s_%s.npz" % (sym[:-1], DAY))
    if not os.path.exists(fb):
        print("ltk_live_l3 %s: 没有币安数据  L3LIVE_MISSING" % sym, flush=True)
        return
    tick, mult = SC.spec(sym)
    L.TICK, L.MULT[sym], L.L3_DIR[sym], L.TRD_DIR = tick, mult, RAW, RAW          # 按品种设置(同 ltk_l3.py)
    hours = sorted(os.path.basename(f)[:2] for f in glob.glob(os.path.join(RAW, DAY, "??_%s_l3.jsonl.gz" % sym)))
    zb = np.load(fb)
    lt = np.load(os.path.join(R.ROOT, "data", "research7", "latency_empirical.npz"))
    agents = [R.LiveAgent(n, L.EmpiricalLatency(P.Load(), lt, lead_ms=0.3, seed=SEED, md_jitter=True), sym, zb["ts"], zb["px"].tolist(), R.VARIANTS[n])
              for n in NAMES]
    sim = L.L3Sim(sym, L.Latency(fixed_ms=1.8), agents, trade_ticks=P.load_trade_ticks(DAY, hours, sym))
    if FRESH_MS > 0:
        sim.fresh_ns = int(FRESH_MS * L.MS)
    with contextlib.redirect_stdout(io.StringIO()):
        sim.run(DAY, hours, prewarm_s=0)
    os.makedirs(OUT, exist_ok=True)
    for a in agents:
        base = os.path.join(OUT, "%s_%s" % (sym, a.name))
        np.savez_compressed(base + ".npz", fills=np.asarray(a.fills, float).reshape(-1, 7), mids=np.asarray(a.mids, float).reshape(-1, 2),
                            pnl=np.asarray(a.pnl, float).reshape(-1, 2), tick=a.tick, mult=a.mult)
        st = a.strat._summary()
        st.update(n_place=a.n_place, n_cancel=a.n_cancel, breaks=sim.breaks, paired=int(sim.paired_n), hours=len(hours), fresh_n=int(sim.fresh_n), fresh_qty=int(sim.fresh_qty))
        json.dump(st, open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False, default=str)
    print("ltk_live_l3 %s: %d 个小时文件;" % (sym, len(hours)) + "  ".join("%s 成交 %d" % (a.name, len(a.fills)) for a in agents) + "  L3LIVE_DONE", flush=True)


def run_all(par):
    import subprocess
    import time
    todo = [s for s in symbols() if not os.path.exists(os.path.join(OUT, "%s_%s.json" % (s, NAMES[-1])))]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("LTK_CAND", None)
    running = []
    while todo or running:
        running = [p for p in running if p.poll() is None]
        while todo and len(running) < par:
            running.append(subprocess.Popen([sys.executable, os.path.abspath(__file__), "run", todo.pop(0)], cwd=R.ROOT, env=env))
        time.sleep(2)
    print("L3LIVE_ALL_DONE", flush=True)


def report():
    lines = []

    def Pn(s=""):
        lines.append(s)
        print(s, flush=True)

    res = {}
    for sym in symbols():
        for n in NAMES:
            base = os.path.join(OUT, "%s_%s" % (sym, n))
            if not os.path.exists(base + ".json"):
                continue
            z, st = np.load(base + ".npz"), json.load(open(base + ".json", encoding="utf-8"))
            f, m, p = z["fills"], z["mids"], z["pnl"]
            if not len(p):
                continue
            v, sec = p[:, 1], p[:, 0]
            span_h = (sec[-1] - sec[0]) / 3600.0
            o = dict(span=span_h, pnl=float(v[-1]), usd=float((f[:, 2] * f[:, 3]).sum()) if len(f) else 0.0, n=len(f),
                     dd=float((np.maximum.accumulate(v) - v).max()), front=st["fills_front"], fills=st["fills"], ls=st["loss_stop"],
                     msgs=st["n_place"] + st["n_cancel"], eod=abs(float(f[-1, 4])) * float(m[-1, 1]) if len(f) else 0.0)
            j = np.searchsorted(sec, sec - 1800, side="left")
            o["w30"] = float((v - v[j]).min())
            if len(f):
                ih = np.clip(np.searchsorted(m[:, 0], f[:, 0] // 10**9 + 60, side="left"), 0, len(m) - 1)
                w = f[:, 2] * f[:, 3]
                o["net_bp"] = float(((f[:, 1] * (m[ih, 1] - f[:, 2]) / f[:, 2] * 1e4 + 0.8) * w).sum() / w.sum())
                hr = ((sec - sec[0]) // 3600).astype(int)
                o["hourly"] = [float(v[hr == k][-1] - v[hr == k][0]) for k in range(hr.max() + 1) if (hr == k).any()]
            res[(sym, n)] = o
    Pn("MM_LTK_PROBE_v1(定版,实盘策略类)在 2026-10-01 逐笔委托数据上的回放 —— 真实排队;盈亏与成交额已折算到 24 小时")
    if FRESH_MS > 0:
        Pn("口径:打到进簿不足 %d 毫秒的挂单的成交(先挂后吃的配对成交)不分给我方" % FRESH_MS)
    for n in NAMES:
        Pn()
        Pn("== 方案 %s" % LABEL[n])
        Pn("%-9s %5s %7s %11s %9s %7s %7s %8s %8s %6s %6s %9s %8s" % ("合约", "小时", "成交", "成交额$/天", "盈亏$/天", "每笔bp", "逐时t", "最大回撤", "最差30m", "最前", "亏损线", "消息/天", "末持仓$"))
        for grp, syms in (("定版合约池", POOL), ("其余合约", [s for s in symbols() if s not in POOL])):
            tot = [0.0, 0.0, 0.0]
            for sym in syms:
                o = res.get((sym, n))
                if o is None:
                    continue
                k = 24.0 / max(o["span"], 1e-9)
                h = np.asarray(o.get("hourly", [0.0]))
                t = float(h.mean() / (h.std(ddof=1) / np.sqrt(len(h)))) if len(h) > 2 and h.std(ddof=1) > 0 else float("nan")
                Pn("%-9s %5.1f %7d %11.0f %+9.2f %+7.2f %+7.2f %8.2f %+8.2f %5.0f%% %6d %9.0f %8.0f" % (
                    sym[:-5], o["span"], o["n"], o["usd"] * k, o["pnl"] * k, o.get("net_bp", float("nan")), t, o["dd"], o["w30"],
                    100 * o["front"] / max(o["fills"], 1), o["ls"], o["msgs"] * k, o["eod"]))
                tot[0] += o["pnl"] * k
                tot[1] += o["usd"] * k
                tot[2] += o["pnl"] > 0
            Pn("  %s合计:盈亏 $%+.2f / 天,成交额 $%s / 天,盈亏为正的合约 %d 个" % (grp, tot[0], format(round(tot[1]), ","), int(tot[2])))
    open(os.path.join(OUT, "live_l3_report.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2])
    elif sys.argv[1] == "report":
        report()
    else:
        run_all(int(sys.argv[2]) if len(sys.argv) > 2 else 6)
