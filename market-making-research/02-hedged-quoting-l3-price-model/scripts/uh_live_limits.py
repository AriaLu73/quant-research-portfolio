#!/usr/bin/env python3
"""research3:实盘风控配置要容纳候选版本,需要多大的数(只读,量 C6S15 已跑完的全天回测)。
逐小时从订单日志重放:USDC 腿 / USDT 腿的持仓名义、"持仓 + 同向在挂单"的最坏敞口(风控 PT-04 / PT-05 的口径)、单笔最大名义、
任意 10 秒下单数(两条合约合计,风控 PT-07 按 交易所.品类 计)、每天下单数。回测每小时从空仓开始,跨小时持仓不在内。
用法:Python314/python.exe -X utf8 scripts/research3/uh_live_limits.py [前缀=C6S15]"""
import glob, json, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
prefix = sys.argv[1] if len(sys.argv) > 1 else "C6S15"
rows = []; per_day = {}
for p in sorted(glob.glob(os.path.join(ROOT, "data", "research5", "runs", prefix + "_2026*.json"))):
    for r in json.load(open(p, encoding="utf-8")):
        if "net" not in r:
            continue
        ev = [json.loads(l) for l in open(os.path.join(r["out_dir"], "broker_sim_wal.jsonl"), encoding="utf-8")]
        O = {}; pos = {"U": 0.0, "H": 0.0}; rest = {("U", 1): 0.0, ("U", -1): 0.0, ("H", 1): 0.0, ("H", -1): 0.0}
        px_last = {"U": None, "H": None}; ts_orders = []; mx = dict(posU=0.0, posH=0.0, expU=0.0, expH=0.0, order=0.0, net=0.0)
        for e in ev:
            t = e["t"]
            if t == "order":
                leg = "U" if e["symbol"].endswith("USDC") else "H"; s = 1 if e["side"] == "buy" else -1; q = float(e["qty"])
                px = float(e["price"]) if e.get("price") else px_last[leg]
                O[e["id"]] = [leg, s, q]; rest[(leg, s)] += q; ts_orders.append(e["ts_ns"])
                if px:
                    px_last[leg] = px; mx["order"] = max(mx["order"], q * px)
            elif t == "cancel" and e["id"] in O:
                leg, s, q = O.pop(e["id"]); rest[(leg, s)] -= q
            elif t == "fill" and e["id"] in O:
                leg, s, q = O[e["id"]]; f = float(e["qty"]); pos[leg] += s * f; rest[(leg, s)] -= f; O[e["id"]][2] = q - f; px_last[leg] = float(e["px"])
                if O[e["id"]][2] <= 1e-12:
                    O.pop(e["id"])
            for leg, kp, ke in (("U", "posU", "expU"), ("H", "posH", "expH")):
                px = px_last[leg]
                if px:
                    mx[kp] = max(mx[kp], abs(pos[leg]) * px)
                    mx[ke] = max(mx[ke], abs(pos[leg] + max(rest[(leg, 1)], 0.0)) * px, abs(pos[leg] - max(rest[(leg, -1)], 0.0)) * px)
            if px_last["U"]:
                mx["net"] = max(mx["net"], abs(pos["U"] + pos["H"]) * px_last["U"])
        ts = np.array(sorted(ts_orders)); n10 = int((np.searchsorted(ts, ts + 10_000_000_000, "left") - np.arange(len(ts))).max()) if len(ts) else 0
        day = r["feed"].split("/")[1].split("_")[0]; per_day[day] = per_day.get(day, 0) + len(ts)
        rows.append(dict(feed=r["feed"][-11:], n10=n10, orders=len(ts), **mx))
q = lambda k, p: float(np.percentile([x[k] for x in rows], p))
print(f"{prefix}:{len(rows)} 小时、{len(per_day)} 天")
for k, name in (("posU", "USDC 腿持仓名义"), ("posH", "USDT 腿持仓名义"), ("expU", "USDC 腿 持仓+同向挂单"), ("expH", "USDT 腿 持仓+同向挂单"), ("net", "两腿净敞口(未对冲)"), ("order", "单笔订单名义")):
    print(f"  {name:<16} 中位 {q(k, 50):>9,.0f}  90% {q(k, 90):>9,.0f}  99% {q(k, 99):>9,.0f}  最大 {q(k, 100):>9,.0f}")
print(f"  任意 10 秒下单数(两合约合计):中位 {q('n10', 50):.0f}  99% {q('n10', 99):.0f}  最大 {q('n10', 100):.0f};每小时下单 最大 {max(x['orders'] for x in rows):,};每天下单 最大 {max(per_day.values()):,}、均值 {int(np.mean(list(per_day.values()))):,}")
w = max(rows, key=lambda x: x["expU"]); print("  USDC 最坏敞口出现在", w["feed"], {k: round(v) for k, v in w.items() if k not in ("feed",)})
