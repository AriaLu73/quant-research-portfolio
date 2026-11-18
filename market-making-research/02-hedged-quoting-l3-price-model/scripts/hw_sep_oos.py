#!/usr/bin/env python3
"""H-W 样本外检验(预注册见 docs/research3/strategy_midcap_touch.md 第 16 节;规则与口径冻结,不得因结果改动):
  数据:购买的 9 月全合约盘口 data/book_l2/2026/09/<日>/ + data/trades;检验日 09-10、09-17、09-24。
  步骤:① 抽盘口帧(extract_buy_tob,已抽的跳过)② pair_intercept_sim(PI_FR=0.005, PI_H_MS=3, PI_CAP_USD=1000, L=1,2)③ 按预注册标准出结论。
  主检验集 = CRYPTO 类 USDT 本位合约,剔除 XBT/ETH/SOL/XRP;副检验集 = STOCK 类。
用法:python scripts/research3/hw_sep_oos.py [--days 20260910,20260917,20260924] [--workers 4] [--report-only]"""
import argparse, glob, json, os, subprocess, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPECS = json.load(open(os.path.join(ROOT, "data", "research2", "kc_contract_specs.json")))
MAJORS = {"XBTUSDTM", "ETHUSDTM", "SOLUSDTM", "XRPUSDTM"}
TAG = "_sepoos"
os.environ["PYTHONUTF8"] = "1"          # 子进程日志一律 UTF-8(detach 下默认 GBK,曾导致按中文标记等待的链永远等不到)


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buy_paths as BP


def contracts(day):
    return BP.symbols(day)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--days", default="20260910,20260917,20260924"); ap.add_argument("--workers", type=int, default=4); ap.add_argument("--report-only", action="store_true")
    ns = ap.parse_args(); days = ns.days.split(",")
    uni = sorted({s for d in days for s in contracts(d) if s in SPECS and s.endswith("USDTM") and s not in MAJORS and SPECS[s].get("class") in ("CRYPTO", "STOCK")})
    print(f"检验日 {days};合约 {len(uni)} 个(CRYPTO {sum(SPECS[s]['class'] == 'CRYPTO' for s in uni)},STOCK {sum(SPECS[s]['class'] == 'STOCK' for s in uni)})", flush=True)
    if not uni:
        print("没有可检验的合约:所选日期的 data/book_l2 目录里只有主流币/大宗。"); return
    if not ns.report_only:
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "research3", "extract_buy_tob.py"), "--syms", ",".join(uni), "--days", ",".join(days), "--workers", str(ns.workers)], cwd=ROOT, check=False)
        env = dict(os.environ, PI_FR="0.005", PI_H_MS="3", PI_CAP_USD="1000")
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "research3", "pair_intercept_sim.py"), "--syms", ",".join(uni), "--days", ",".join(days), "--L", "1,2", "--phi", "0",
                        "--workers", str(ns.workers), "--tag", TAG], env=env, cwd=ROOT, stdout=subprocess.DEVNULL, check=False)
    D = pd.read_csv(os.path.join(ROOT, "data", "research3", f"pair_intercept{TAG}.csv"))
    if "error" in D:
        print("出错的 (合约,日):", int(D.error.notna().sum())); D = D[D.error.isna()]
    D = D[(D.fills > 0) & D.day.astype(int).astype(str).isin(days)].copy(); D["cls"] = D.sym.map(lambda s: SPECS[s]["class"])
    pd.set_option("display.width", 220)
    for cls, name in (("CRYPTO", "主检验集(山寨永续)"), ("STOCK", "副检验集(股票合约)")):
        for L in (1.0, 2.0):
            X = D[(D.cls == cls) & (D.L == L)]
            if not len(X):
                continue
            g = X.groupby("day").agg(contracts=("sym", "size"), pos=("rt_net", lambda x: int((x > 0).sum())), net=("rt_net", "sum"), leg=("rt_leg", "sum"), vol=("rt_vol", "sum"),
                                     orders_s=("orders_per_s", "sum"), pair=("pair_share", "mean")); g["bp"] = g.net / g.vol * 1e4
            s = X.groupby("sym").rt_net.sum()
            print(f"\n== {name},L = {L:g} ms:净 ${X.rt_net.sum():,.0f}(价差腿 ${X.rt_leg.sum():,.0f})/ 成交额 ${X.rt_vol.sum():,.0f} = {X.rt_net.sum() / X.rt_vol.sum() * 1e4:+.2f} bp;正合约 {int((s > 0).sum())}/{len(s)}")
            print(g.round(2).to_string())
            if cls == "CRYPTO" and L == 2.0:
                c1 = bool((g.net > 0).all()) and len(g) == len(days); c2 = (s > 0).mean() >= 0.55; c3 = X.rt_net.sum() / X.rt_vol.sum() * 1e4 >= 1.0; c4 = X.rt_leg.sum() > 0
                print(f"\n预注册标准(主检验集、L = 2 ms):① 每个检验日净利 > 0:{c1} ② 正合约占比 ≥ 55%:{c2}({(s > 0).mean():.0%}) ③ 净 ≥ +1.0 bp:{c3} ④ 不含返佣的价差腿 > 0:{c4}")
                print("结论:", "通过" if (c1 and c2 and c3 and c4) else "不通过")
                print("最赚 10 个:"); print(s.sort_values(ascending=False).head(10).round(0).to_string()); print("最亏 5 个:"); print(s.sort_values().head(5).round(0).to_string())


if __name__ == "__main__":
    main()
    print("HW_OOS_DONE", flush=True)
