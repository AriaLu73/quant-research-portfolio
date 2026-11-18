#!/usr/bin/env python3
"""回测引擎(research7 L3 回放器)对 2026-10-14 BTC-USDT 实盘订单的逐张对账(用户 10-18:"现在去测回测引擎跟实盘差别多大，
用10-14当天实盘跑的策略去回测环境里测，看跟我们真实的实盘成交记录差别在哪";选定 research7 L3 回放器、只测 BTC、逐张对账 + 策略自己跑 两种都做)。
本文件是"逐张对账"那一半;做法与阶段 0 的 live_recon.py 完全相同(直接调用它的 Replay / stats),只换输入:
  实盘  data/research7/live_orders_20261014.jsonl.gz(服务器总线导出):BTC-USDT 的全部下单、撤单指令、交易所回报、成交(三个策略实例都算)
  行情  同期自采逐笔委托 data/research5/usdc_pairs_l3usdt/20261014/<时>_XBTUSDTM_l3.jsonl.gz(我方实盘订单从公开流里拿掉)
两种重放(同 live_recon.py):
  actual   我方订单的进簿 / 撤单时刻 = 交易所公开流里这张单的 open / done → 只检验排队与撮合规则
  emp×20   进簿 = 引擎发单时刻 + 实测延迟分布(按负载分档抽样,20 个随机数种子);撤单同理 → 再检验延迟模型
比较:每张单实盘成没成交、成交多少张,回放成没成交、成交多少张;列出全部不一致的订单(进簿时前面排了多少、离最优价几跳、撤单时刻)。
只比挂单成交(实盘的吃单成交单独列数)。不算 markout。
用法  .venv/Scripts/python.exe scripts/research7/live_recon_20261014.py run | report
输出  data/research7/live_recon/20261014_XBTUSDTM.json、_bbo.npy、20261014_report.txt"""
import gzip
import json
import math
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l3sim as L          # noqa: E402
import l3_prep as P        # noqa: E402
import live_recon as R     # noqa: E402

SYM, DAY = "XBTUSDTM", "20261014"
EXPORT = os.path.join(L.ROOT, "data", "research7", "live_orders_20261014.jsonl.gz")
OUT = R.OUT; TAG = f"{DAY}_{SYM}"


def hours():
    """10-14 有逐笔委托文件、且实盘在跑(08:01–21:01 UTC)的小时。"""
    return [h for h in P.hours_of(DAY, SYM) if "08" <= h <= "21"]


def read_export():
    """同 live_recon.read_journal 的输出格式:{引擎订单号: side、tick、size(张)、t_send、ex_id、t_cancel、fills、rejected、strategy}。"""
    mult = L.MULT[SYM]; od = {}
    with gzip.open(EXPORT, "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line); m = r["obj"]; typ = r["msg_type"]
            if typ == "KVGroup":                          # 撤单指令(protobuf 文本)
                if '"BTC-USDT"' not in m:
                    continue
                oid = re.search(r'key: "order_id"\n  value: "([^"]+)"', m).group(1); t = int(re.search(r"ts_ns: (\d+)", m).group(1))
                if oid in od:
                    od[oid]["t_cancel"] = od[oid]["t_cancel"] or t
                continue
            if m.get("symbol") != "BTC-USDT":
                continue
            oid = m.get("order_id", "")
            if typ == "Order":
                od[oid] = dict(side=0 if m["side"] == "buy" else 1, tick=L.to_tick(m["price"]) if m.get("price") else None, size=int(round(float(m["quantity"]) / mult)),
                               t_send=int(m["ts_ns"]), ex_id=None, t_cancel=None, fills=[], rejected=False, strategy=m.get("strategy_id"),
                               tif=m.get("time_in_force"))
            elif oid in od:
                o = od[oid]
                if typ == "OrderReport":
                    if m.get("exchange_order_id"):
                        o["ex_id"] = m["exchange_order_id"]
                    if m["status"] == "rejected":
                        o["rejected"] = True
                elif typ == "Fill":
                    o["fills"].append((int(m["ts_ns"]), int(round(float(m["quantity"]) / mult)), L.to_tick(m["price"]), bool(m["is_maker"])))
    return od


def run():
    hs = hours(); od_all = read_export()
    other = [o for o in od_all.values() if o["tif"] != "post_only"]          # 非只挂不吃的单(平仓 / 手动单),只计数,不进对账
    od = {k: o for k, o in od_all.items() if o["tif"] == "post_only"}
    own = {o["ex_id"]: (o["side"], o["tick"]) for o in od.values() if o["ex_id"]}
    a1 = R.Replay(od, "actual")
    table = np.load(os.path.join(P.OUT, "latency_empirical.npz"))
    emp = [R.Replay(od, "model", L.EmpiricalLatency(P.Load(), table, lead_ms=0.0, seed=s)) for s in range(R.N_SEEDS)]
    rec = P.Recorder()
    sim = L.L3Sim(SYM, L.Latency(load=P.Load()), [a1] + emp, recorder=rec, own_ids=own, trade_ticks=P.load_trade_ticks(DAY, hs, SYM))
    print(f"orders {len(od):,}, hours {hs}", flush=True)
    sim.run(DAY, hs)
    res = dict(sym=SYM, day=DAY, hours=hs, breaks=sim.breaks, n_orders=len(od), n_other=len(other),
               other_fills=[(o["tif"], o["side"], o["tick"], o["size"], o["fills"]) for o in other if o["fills"]], paired_n=sim.paired_n, paired_qty=sim.paired_qty, orders={})
    for k, o in od.items():
        row = dict(side=o["side"], tick=o["tick"], size=o["size"], t_send=o["t_send"], t_cancel=o["t_cancel"], rejected=o["rejected"], strategy=o["strategy"], real=o["fills"])
        for name, ag in [("actual", a1)] + [(f"emp{i}", e) for i, e in enumerate(emp)]:
            so = ag.sim_of.get(k)
            row[name] = None if (so is None or k in ag.skipped) else dict(state=so.state, fills=so.fills, ahead0=so.ahead0, level0=so.level0, rest_at=so.rest_at, cancel_at=so.cancel_at)
        res["orders"][k] = row
    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(os.path.join(OUT, f"{TAG}.json"), "w"))
    np.save(os.path.join(OUT, f"{TAG}_bbo.npy"), np.asarray(rec.bbo, np.int64).reshape(-1, 5))
    print(f"RECON_1014_RUN_DONE orders {len(od):,} breaks {sim.breaks}", flush=True)


def report():
    res = json.load(open(os.path.join(OUT, f"{TAG}.json")))
    L_ = [f"回测引擎(research7 L3 回放器)对 10-14 BTC-USDT 实盘订单逐张对账,时段 {res['hours'][0]}–{res['hours'][-1]} 时 UTC(有逐笔委托的小时);只挂不吃订单 {res['n_orders']:,} 张;回放中断流 {res['breaks']} 次", ""]
    taker = sum(1 for r in res["orders"].values() for f in r["real"] if not f[3])
    L_.append(f"只挂不吃订单里的吃单成交 {taker} 笔;非只挂不吃的订单 {res['n_other']} 张,其中有成交的 {len(res['other_fills'])} 张(平仓 / 手动单,不参与比较)")
    for mode in ["actual"] + [f"emp{i}" for i in range(R.N_SEEDS)]:
        rows = [(k, r) for k, r in res["orders"].items() if r.get(mode) is not None and not r["rejected"]]
        real_f = {k for k, r in rows if any(f[3] for f in r["real"])}; sim_f = {k for k, r in rows if r[mode]["fills"]}
        rq = sum(f[1] for k, r in rows for f in r["real"] if f[3]); sq = sum(f for k, r in rows for _, f in r[mode]["fills"])
        if mode == "actual" or mode == "emp0":
            L_.append(f"\n[{'actual:进簿 / 撤单取交易所真实时刻' if mode == 'actual' else 'emp0:引擎发单时刻 + 实测延迟(种子 0)'}] 可评估订单 {len(rows):,}")
            L_.append(f"  成交订单  实盘 {len(real_f)}  回放 {len(sim_f)}  两边都成交 {len(real_f & sim_f)}  只实盘成交 {len(real_f - sim_f)}  只回放成交 {len(sim_f - real_f)}")
            L_.append(f"  成交张数  实盘 {rq}  回放 {sq}")
            both = real_f & sim_f
            if both:
                dq = [sum(f[1] for f in res['orders'][k]['real'] if f[3]) - sum(f for _, f in res['orders'][k][mode]['fills']) for k in both]
                dt = [(min(t for t, _ in res['orders'][k][mode]['fills']) - min(f[0] for f in res['orders'][k]['real'] if f[3])) / 1e6 for k in both]
                L_.append(f"  两边都成交的订单:张数差(实盘 − 回放)= 0 的 {sum(d == 0 for d in dq)} / {len(dq)};首笔成交时刻差(回放 − 实盘)中位 {np.median(dt):+.1f} ms,范围 {min(dt):+.1f} … {max(dt):+.1f} ms")
            for k in sorted(real_f ^ sim_f, key=lambda k: res["orders"][k]["t_send"]):
                r = res["orders"][k]; s = r[mode]
                L_.append(f"    不一致 {k} {r['strategy']} {'买' if r['side'] == 0 else '卖'} {r['tick'] * L.TICK:.1f} x{r['size']} 发单 {r['t_send']} 撤单指令 {r['t_cancel']} | 实盘 {[(f[0], f[1]) for f in r['real'] if f[3]]} | 回放 {s['state']} {s['fills']} 进簿 {s['rest_at']} 撤单生效 {s['cancel_at']} 进簿时前方 {s['ahead0']} 张 档位 {s['level0']}")
    ns, nr, nb, qs = [], [], [], []
    for i in range(R.N_SEEDS):
        mode = f"emp{i}"; rows = [(k, r) for k, r in res["orders"].items() if r.get(mode) is not None and not r["rejected"]]
        real_f = {k for k, r in rows if any(f[3] for f in r["real"])}; sim_f = {k for k, r in rows if r[mode]["fills"]}
        ns.append(len(sim_f)); nr.append(len(real_f)); nb.append(len(real_f & sim_f)); qs.append(sum(f for k, r in rows for _, f in r[mode]["fills"]))
    L_.append(f"\n[emp × {R.N_SEEDS} 个种子] 成交订单 实盘 {np.mean(nr):.1f}  回放 均值 {np.mean(ns):.2f}(各种子 {min(ns)}–{max(ns)})  两边都成交 均值 {np.mean(nb):.2f}  回放成交张数 均值 {np.mean(qs):.0f}")
    txt = "\n".join(L_); open(os.path.join(OUT, f"{DAY}_report.txt"), "w", encoding="utf-8").write(txt); print(txt)


if __name__ == "__main__":
    run() if sys.argv[1] == "run" else report()
