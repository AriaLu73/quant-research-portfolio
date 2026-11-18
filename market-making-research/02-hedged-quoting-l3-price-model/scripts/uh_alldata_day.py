#!/usr/bin/env python3
"""research3:全数据回测的单日小结 + 累计(读 data/research5/runs/ALLs2d_<day>.json 与行为审计)。用法:python uh_alldata_day.py <day> [all]"""
import glob, json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS = os.path.join(ROOT, "data", "research5", "runs")
TRAIN_H = {"01", "07", "13", "19"}; TRAIN_D = {"20260901", "20260902", "20260903", "20260910", "20260911", "20260914", "20260917", "20260918"}; WALK_D = {"20260923", "20260924"}


def kind(day):
    return "训练日(其中 4 小时是训练小时)" if day in TRAIN_D else ("走步日" if day in WALK_D else "从未用过的日子")


def load(day):
    p = os.path.join(RUNS, f"ALLs2d_{day}.json")
    return [r for r in json.load(open(p, encoding="utf-8"))] if os.path.exists(p) else []


def summ(rows):
    ok = [r for r in rows if "net" in r]
    net = sum(r["net_corr"] for r in ok); vol = sum(r["vol"] for r in ok); usdc = sum(r["usdc_usd"] for r in ok)
    return dict(hours=len(ok), err=len(rows) - len(ok), net=net, vol=vol, usdc=usdc, bp=net / vol * 1e4 if vol else 0.0, orders=sum(r["orders"] or 0 for r in ok),
                fills=sum(r["usdc_fills"] for r in ok), pos=sum(r["net_corr"] > 1e-9 for r in ok), neg=sum(r["net_corr"] < -1e-9 for r in ok),
                nofill=sum(r["usdc_fills"] == 0 for r in ok), worst=min((r["net_corr"] for r in ok), default=0.0), best=max((r["net_corr"] for r in ok), default=0.0),
                blocked=sum(r.get("blocked") or 0 for r in ok), max_orders=max((r["orders"] or 0 for r in ok), default=0),
                hedge_mkt=sum((r.get("stats") or {}).get("hedge_market", 0) for r in ok), inv_end=sum(abs(r.get("inv_end") or 0) for r in ok))


def audit(day):
    p = os.path.join(ROOT, "logs", f"r3_ALLs2d_{day}_behaviour.txt")
    if not os.path.exists(p):
        return None, None, []
    txt = open(p, encoding="utf-8", errors="replace").read().splitlines()
    w, fails = [], []
    for l in txt:
        f = l.split()
        if len(f) > 12 and f[0].startswith("ku_buy/") and f[7].isdigit():
            w.append(int(f[7]))
            if "FAIL" in l:
                fails.append((f[0][-2:], int(f[7]), [x for x in f if "FAIL" in x]))
    verdict = next((l for l in reversed(txt) if l.startswith("BEHAVIOUR")), "?")
    return verdict, (max(w) if w else None), fails


def main():
    day = sys.argv[1]
    rows = load(day); s = summ(rows); v, w, fails = audit(day)
    print(f"== {day}({kind(day)}):{s['hours']} 小时" + (f",{s['err']} 个出错" if s["err"] else ""))
    print(f"净 ${s['net']:.2f};两腿成交 ${s['vol']:,.0f}(USDC 腿 ${s['usdc']:,.0f});每美元 {s['bp']:.2f} bp;小时 正 {s['pos']} / 负 {s['neg']} / 无成交 {s['nofill']};最好 ${s['best']:.2f} 最差 ${s['worst']:.2f}")
    print(f"报单 {s['orders']:,} 张,USDC 成交 {s['fills']} 笔,单小时最多 {s['max_orders']:,} 张;风控拦截 {s['blocked']};吃单对冲 {s['hedge_mkt']} 次")
    print(f"行为审计:{v};30 秒峰值权重最高 {w};未过的小时 {fails}")
    ok = sorted((r for r in rows if "net" in r), key=lambda r: r["net_corr"])
    print("最差 3 小时:", [(r["feed"][-2:], round(r["net_corr"], 2), round(r["usdc_usd"])) for r in ok[:3]], "最好 3 小时:", [(r["feed"][-2:], round(r["net_corr"], 2), round(r["usdc_usd"])) for r in ok[-3:]])
    if day in TRAIN_D:
        tr = [r for r in ok if r["feed"][-2:] in TRAIN_H]; un = [r for r in ok if r["feed"][-2:] not in TRAIN_H]
        print(f"其中训练小时(4 个)净 ${sum(r['net_corr'] for r in tr):.2f};未见过的 20 个小时净 ${sum(r['net_corr'] for r in un):.2f}、成交 ${sum(r['vol'] for r in un):,.0f}")
    done = sorted(re.findall(r"ALLs2d_(\d{8})\.json", " ".join(os.listdir(RUNS))))
    tot = {"all": [], "unseen": []}
    for d in done:
        for r in load(d):
            if "net" not in r:
                continue
            tot["all"].append(r)
            if not (d in TRAIN_D and r["feed"][-2:] in TRAIN_H):
                tot["unseen"].append(r)
    full = [d for d in done if len([r for r in load(d) if "net" in r]) == 24]
    for k, name in (("all", "累计(全部已跑小时)"), ("unseen", "累计(剔除 32 个训练小时)")):
        t = summ(tot[k])
        print(f"{name}:{t['hours']} 小时,净 ${t['net']:.2f},两腿成交 ${t['vol']:,.0f},{t['bp']:.2f} bp/$;正 {t['pos']} / 负 {t['neg']} / 无成交 {t['nofill']};折 ${t['net'] / max(1, t['hours']) * 24:.0f}/天、成交 ${t['vol'] / max(1, t['hours']) * 720 / 1e6:.1f}M/月")
    print("已跑完整的日子:", len(full), "/ 20;逐日净值:", {d: round(summ(load(d))["net"], 2) for d in full})


if __name__ == "__main__":
    main()
