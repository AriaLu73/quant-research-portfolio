#!/usr/bin/env python3
"""research3:MM-UH-FV2 v1 全数据回测的单日小结 + 累计。用法:python uh_fvall_day.py <day>
两档(ALLFV5k = 单笔 $5,000;ALLFV10k = 单笔 $10,000)。日子分三类:从未用过(12 天)、训练日(8 天,其中 4 个训练小时)、走步日(2 天)。"""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS = os.path.join(ROOT, "data", "research5", "runs")
TRAIN_H = {"01", "07", "13", "19"}
TRAIN_D = {"20260901", "20260902", "20260903", "20260910", "20260911", "20260914", "20260917", "20260918"}; WALK_D = {"20260923", "20260924"}
kind = lambda d: "训练日" if d in TRAIN_D else ("走步日" if d in WALK_D else "从未用过")


def load(prefix, day):
    p = os.path.join(RUNS, f"{prefix}_{day}.json")
    return [r for r in json.load(open(p, encoding="utf-8")) if "net" in r] if os.path.exists(p) else []


def summ(rows):
    n = len(rows); net = sum(r["net_corr"] for r in rows); vol = sum(r["vol"] for r in rows)
    return dict(hours=n, net=net, vol=vol, bp=net / vol * 1e4 if vol else 0.0, fillh=sum(r["usdc_fills"] > 0 for r in rows), neg=sum(r["net_corr"] < -1e-9 for r in rows),
                worst=min((r["net_corr"] for r in rows), default=0.0), best=max((r["net_corr"] for r in rows), default=0.0), orders=sum(r["orders"] or 0 for r in rows),
                blocked=sum(r.get("blocked") or 0 for r in rows), hmkt=sum((r.get("stats") or {}).get("hedge_market", 0) for r in rows))


def audit(prefix, day):
    p = os.path.join(ROOT, "logs", f"r3_{prefix}_{day}_behaviour.txt")
    if not os.path.exists(p):
        return "?", None, 0
    txt = open(p, encoding="utf-8", errors="replace").read().splitlines(); w = []; nf = 0
    for l in txt:
        f = l.split()
        if len(f) > 12 and f[0].startswith("ku_buy/") and f[7].isdigit():
            w.append(int(f[7])); nf += "FAIL" in l
    v = next((l for l in reversed(txt) if l.startswith("BEHAVIOUR")), "?")
    return ("通过" if "PASS" in v else "未通过"), (max(w) if w else None), nf


day = sys.argv[1]
print(f"== {day}({kind(day)})")
for prefix, lab in (("ALLFV5k", "单笔 $5k "), ("ALLFV10k", "单笔 $10k")):
    R = load(prefix, day)
    if len(R) < 24:
        print(f"{lab}:只跑完 {len(R)}/24 小时"); continue
    s = summ(R); v, w, nf = audit(prefix, day)
    print(f"{lab}:净 ${s['net']:.2f};两腿成交 ${s['vol']:,.0f}({s['bp']:.2f} bp/$);有成交 {s['fillh']}/24 小时,亏损 {s['neg']} 小时,最差 ${s['worst']:.2f} 最好 ${s['best']:.2f};"
          f"报单 {s['orders']:,};限频审计 {v}(峰值权重 {w},未过 {nf} 小时);风控拦截 {s['blocked']};吃单对冲 {s['hmkt']} 次")
for prefix, lab in (("ALLFV5k", "单笔 $5k "), ("ALLFV10k", "单笔 $10k")):
    done = sorted(d for d in re.findall(rf"{prefix}_(\d{{8}})\.json", " ".join(os.listdir(RUNS))) if len(load(prefix, d)) == 24)
    if not done:
        continue
    allr = [r for d in done for r in load(prefix, d)]
    unseen = [r for d in done for r in load(prefix, d) if not (d in TRAIN_D and r["feed"][-2:] in TRAIN_H)]
    fresh = [r for d in done if d not in TRAIN_D and d not in WALK_D for r in load(prefix, d)]
    a, u, f = summ(allr), summ(unseen), summ(fresh)
    nd = len(done); nfresh = len([d for d in done if d not in TRAIN_D and d not in WALK_D])
    daily = {d: round(summ(load(prefix, d))["net"], 1) for d in done}
    print(f"-- {lab} 累计 {nd}/20 天:净 ${a['net']:.2f}(${a['net'] / nd:.1f}/天、约 ${a['net'] / nd * 30:,.0f}/月);两腿成交 ${a['vol'] / nd:,.0f}/天、${a['vol'] / nd * 30 / 1e6:.1f}M/月;{a['bp']:.2f} bp/$;亏损天数 {sum(v < 0 for v in daily.values())}")
    if nfresh:
        print(f"   其中从未用过的 {nfresh} 天:净 ${f['net']:.2f}(${f['net'] / nfresh:.1f}/天);两腿 ${f['vol'] / nfresh:,.0f}/天;{f['bp']:.2f} bp/$")
    print(f"   逐日净值:{daily}")
