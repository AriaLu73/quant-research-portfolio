#!/usr/bin/env python3
"""把 data/oos/ku_buyc/<日>_<时> 的 24 个小时切片拼成整天一个目录 data/oos/ku_buycday/<日>_00(gzip 文件按小时顺序直接首尾相接),
供回测引擎一个进程连续跑整天(用户 10-15:持仓和策略状态跨小时延续,和实盘一样)。每个小时文件开头的整本快照原样保留。
用法:Python314/python.exe scripts/research7/build_day_feed.py 20260918 [更多日期] --symbols BTC-USDT,ETH-USDT,SOL-USDT"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
syms = sys.argv[sys.argv.index("--symbols") + 1].split(",") if "--symbols" in sys.argv else ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
days = [a for a in args if a.isdigit()]
for day in days:
    for sym in syms:
        out = os.path.join(ROOT, "data", "oos", "ku_buycday", day + "_00", "kucoin", "swap", sym, "feed_raw")
        os.makedirs(out, exist_ok=True)
        for kind in ("depth_deltas", "ticks"):
            dst = os.path.join(out, "%s-%s.jsonl.gz" % (kind, day))
            srcs = [os.path.join(ROOT, "data", "oos", "ku_buyc", "%s_%02d" % (day, hh), "kucoin", "swap", sym, "feed_raw", "%s-%s.jsonl.gz" % (kind, day)) for hh in range(24)]
            miss = [s for s in srcs if not os.path.exists(s)]
            if miss:
                raise SystemExit("缺 %d 个小时文件,例 %s" % (len(miss), miss[0]))
            with open(dst + ".part", "wb") as fo:
                for s in srcs:
                    with open(s, "rb") as fi:
                        fo.write(fi.read())
            os.replace(dst + ".part", dst)
        print(day, sym, "ok", flush=True)
