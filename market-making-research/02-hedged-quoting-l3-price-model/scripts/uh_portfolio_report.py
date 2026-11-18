#!/usr/bin/env python3
"""research3:多品种组合的回测汇总。每个品种一个子账户(KuCoin 经典账户下子账户限频各自独立),所以:
  各品种独立回测 → 逐小时净值相加;限频审计**按品种(=按子账户)分别做**,同时给出"若共用一个账户"的合并峰值作对照。
用法:python uh_portfolio_report.py NAME1[,NAME2,...] [day1,day2,...]
  NAME 可以是一个 run_hours 结果集(如 R3SA_ETH_train32),也可以是全天链的前缀(如 ALLFV10k → 自动找 ALLFV10k_<day>.json)。
  给了日期就只看这些天;不给则取所有品种都跑完(24 小时齐)的日子。
审计线:任意 30 秒窗口权重(下单 2、撤单 1)≤ 1000(最低档 2000 的一半)。"""
import glob, json, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS = os.path.join(ROOT, "data", "research5", "runs")
names = sys.argv[1].split(",")
only_days = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None


def load(name):
    """{feed: row};前缀则合并所有 <name>_<8 位日期>.json。"""
    out = {}
    p = os.path.join(RUNS, name + ".json")
    paths = [p] if os.path.exists(p) else sorted(q for q in glob.glob(os.path.join(RUNS, name + "_*.json")) if os.path.basename(q)[len(name) + 1:-5].isdigit())
    for q in paths:
        for r in json.load(open(q, encoding="utf-8")):
            if "net" in r:
                out[r["feed"]] = r
    return out


def weights(out_dir):
    p = os.path.join(out_dir, "broker_sim_wal.jsonl"); ts, w = [], []
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            o = json.loads(l)
            if o["t"] == "order":
                ts.append(o["ts_ns"]); w.append(2)
            elif o["t"] == "cancel":
                ts.append(o["ts_ns"]); w.append(1)
    return ts, w


def peak30(ts, w):
    if not ts:
        return 0
    i = np.argsort(ts); ts = np.array(ts)[i]; cw = np.r_[0, np.cumsum(np.array(w)[i])]
    j = np.searchsorted(ts, ts + 30_000_000_000, "left")
    return int((cw[j] - cw[:-1]).max())


R = {n: load(n) for n in names}
day_of = lambda f: f.split("/")[1].split("_")[0]
days = sorted(set.intersection(*[{d for d in {day_of(f) for f in v} if sum(day_of(f) == d for f in v) == 24} for v in R.values()])) if only_days is None else sorted(only_days)
if not days:                                    # 抽样小时的结果集(不是全天):取共同小时
    feeds = sorted(set.intersection(*[set(v) for v in R.values()]))
else:
    feeds = sorted(f for f in set.intersection(*[set(v) for v in R.values()]) if day_of(f) in days)
nh = len(feeds)
if not nh:
    print("还没有跑完的小时:", names); sys.exit(0)
print(f"品种 {len(names)} 个,共同小时 {nh} 个" + (f"({len(days)} 个全天:{days[0]}…{days[-1]})" if days else "(抽样小时)"))
pk = {n: [] for n in names}; pk_all = []; tot = []
for f in feeds:
    ts_all, w_all = [], []
    for n in names:
        a, b = weights(R[n][f]["out_dir"]); pk[n].append(peak30(a, b)); ts_all += a; w_all += b
    pk_all.append(peak30(ts_all, w_all)); tot.append(sum(R[n][f]["net_corr"] for n in names))
tot = np.array(tot)
for n in names:
    x = [R[n][f] for f in feeds]; net = sum(r["net_corr"] for r in x); vol = sum(r["vol"] for r in x)
    print(f"  {n:<22} 净 ${net:8.2f}  两腿成交 ${vol:>11,.0f}  {net / vol * 1e4 if vol else 0:5.2f} bp/$  有成交 {sum(r['usdc_fills'] > 0 for r in x):>3}  亏损小时 {sum(r['net_corr'] < -1e-9 for r in x):>3}  最差 ${min(r['net_corr'] for r in x):7.2f}"
          f"  风控拦截 {sum(r.get('blocked') or 0 for r in x)}  限频峰值 {max(pk[n])}(超线小时 {sum(p > 1000 for p in pk[n])})")
vol = sum(R[n][f]["vol"] for n in names for f in feeds)
print(f"组合:净 ${tot.sum():.2f};两腿成交 ${vol:,.0f}({tot.sum() / vol * 1e4:.2f} bp/$);逐小时 正 {int((tot > 1e-9).sum())} / 负 {int((tot < -1e-9).sum())},最差 ${tot.min():.2f} 最好 ${tot.max():.2f}")
print(f"限频:每品种一个子账户 → 各自峰值见上(线 1000);若全部共用一个账户,合并峰值最高 {max(pk_all)},超线 {sum(p > 1000 for p in pk_all)}/{nh} 小时")
if days:
    print("逐日:  日期      " + "  ".join(f"{n[-10:]:>10}" for n in names) + "      组合净     两腿成交   最差小时")
    for d in days:
        fs = [f for f in feeds if day_of(f) == d]
        per = [sum(R[n][f]["net_corr"] for f in fs) for n in names]
        hv = [sum(R[n][f]["net_corr"] for n in names) for f in fs]
        print(f"       {d}  " + "  ".join(f"{p:>10.2f}" for p in per) + f"  {sum(per):>10.2f}  {sum(R[n][f]['vol'] for n in names for f in fs):>11,.0f}  {min(hv):>8.2f}")
    nd = len(days); dn = np.array([sum(R[n][f]["net_corr"] for n in names for f in feeds if day_of(f) == d) for d in days])
    print(f"全天口径({nd} 天):日均净 ${tot.sum() / nd:.2f}(最差日 ${dn.min():.2f},亏损日 {int((dn < 0).sum())});日均两腿成交 ${vol / nd:,.0f} → ${vol / nd * 30 / 1e6:.1f}M/月,净 ${tot.sum() / nd * 30:,.0f}/月")
else:
    print(f"折算(按这 {nh} 个抽样小时外推,会高估全天):成交 ${vol / nh * 720 / 1e6:.1f}M/月,净 ${tot.sum() / nh * 720:,.0f}/月")
