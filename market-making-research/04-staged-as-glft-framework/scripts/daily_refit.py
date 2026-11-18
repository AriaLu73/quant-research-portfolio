#!/usr/bin/env python3
"""AS 实盘参数每天重估(用户 10-15:"σ、k、γ、A 和四个方向因子系数全部每天重新估计";"load_edges 每天标定一次",门槛选 (b))。

一天一次,对"前一天"(UTC)做:
  1. 自采原始消息 → 事件数组      scripts/research7/l2_prep.py own <day> <合约>          (XBT / ETH / SOL)
  2. 事件数组 → 买一卖一与吃单     scripts/research7/l2_market.py <day> <合约>
  3. 事件数组 → 10 毫秒盘口网格     RDAgent_Factor/评估脚本/build_grid.py grid <合约> <day>
  4. 币安期货成交日档(data.binance.vision,第二天才发布)→ 毒性因子 research/as2008/toxicity_tox.py calc <day>
  5. 估计:回测每天用的同一个函数 as_offline.estimate_day(合约, [day])(窗口 1 天,和回测一样)
       → σ、k、γ、A;ETH 另有 BTC 失衡、涨跌差;两个合约都有 tox_bnpush、自己的失衡
     币安日档还没发布时第 4 步做不了:tox_bnpush 估不出,自己的失衡是在它之后估的,也不估——这两项保持部署文件里的旧值,
     其余照常更新(输出里写明)。币安发布后再跑一次本脚本即补齐。
  6. 负载门槛 load_edges(选 (b)):用实盘策略第 23 步记下的负载直方图(12–18 时 UTC)标定。
     直方图从 /api/strategies 的 _runtime_json.stats.load_hist_12_18 取,存成 JSON 文件后用 --load-hist 传进来
     ({"MmAsBtc": [...301 个计数...], "MmAsEth": [...]} 或直接给 _runtime_json 原文)。
     定法与回测相同:让策略数到的条数各档占的时间 = 实测撤单延迟表各档(按当天 BTC 的 L2 事件数分)占的时间。没给就不改门槛。
  7. 写结果:data/research7/daily_params/<交易日>.json(交易日 = 估计日 + 1),每个实例一段可直接贴进 web 参数面板的 YAML;
     加 --write-deploy 时把这些值写进 strategies/deploy/MM_AS_{BTC,ETH}_v2.py 的 DEFAULT_PARAMS(就地改,旧文件先备份到
     strategies/deploy/_archive_<日期>/)。本脚本不碰实盘。

用法:.venv/Scripts/python.exe scripts/research7/daily_refit.py [估计日 YYYYMMDD,默认昨天 UTC] [--load-hist 文件] [--write-deploy]
"""
import datetime as dt, importlib.util, io, json, os, re, shutil, subprocess, sys, urllib.request
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VPY, PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe"), r"Python314/python.exe"
NOWIN = 0x08000000
SYMS = ("XBTUSDTM", "ETHUSDTM", "SOLUSDTM")
BN = {"XBTUSDTM": "BTCUSDT", "ETHUSDTM": "ETHUSDT", "SOLUSDTM": "SOLUSDT"}
DEPLOY = {"XBTUSDTM": ("MmAsBtc", "strategies/deploy/MM_AS_BTC_v2.py"), "ETHUSDTM": ("MmAsEth", "strategies/deploy/MM_AS_ETH_v2.py")}
KEYS = {"XBTUSDTM": ("sigma", "k", "gamma", "A", "beta_bnpush", "beta_obi"),
        "ETHUSDTM": ("sigma", "k", "gamma", "A", "beta_btc_obi", "beta_xgap", "beta_bnpush", "beta_obi")}
OUTD = os.path.join(ROOT, "data", "research7", "daily_params")
env = dict(os.environ, PYTHONIOENCODING="utf-8")


def run(cmd, log):
    with open(log, "a", encoding="utf-8") as f:
        r = subprocess.run(cmd, cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT, creationflags=NOWIN)
    if r.returncode:
        raise SystemExit("失败(%s):%s,见 %s" % (r.returncode, " ".join(cmd), log))


def exists(*p):
    return os.path.exists(os.path.join(ROOT, *p))


def binance(day):
    """币安日档;已有就跳过,没发布返回 False。"""
    d = "%s-%s-%s" % (day[:4], day[4:6], day[6:])
    for s in BN.values():
        f = os.path.join(ROOT, "data", "research5", "binance_hist", "%s-aggTrades-%s.zip" % (s, d))
        if os.path.exists(f):
            continue
        try:
            data = urllib.request.urlopen("https://data.binance.vision/data/futures/um/daily/aggTrades/%s/%s-aggTrades-%s.zip" % (s, s, d), timeout=300).read()
        except Exception:  # noqa: BLE001
            return False
        open(f + ".part", "wb").write(data)
        os.replace(f + ".part", f)
    return True


def edges_from_hist(hist, day):
    """负载直方图(下标 = 每 100 毫秒条数)→ 五个门槛;BTC 的 L2 事件数取当天 12–18 时。"""
    t0 = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    ts = np.load(os.path.join(ROOT, "data", "research7", "l2", "XBTUSDTM_%s.npz" % day))["ts"]
    g = np.arange(t0 + 12 * 3600 * 10**9 + 10**9, t0 + 18 * 3600 * 10**9, 10**8)
    l2 = np.searchsorted(ts, g, side="right") - np.searchsorted(ts, g - 10**8, side="right")
    edges = np.load(os.path.join(ROOT, "data", "research7", "latency_empirical_l2load.npz"))["edges"]
    h = np.asarray(hist, float)
    cdf = np.cumsum(h) / h.sum()
    out = []
    for e in edges[1:]:
        share = min(float((l2 < e).mean()), 1.0)
        out.append(float(np.searchsorted(cdf, share)))          # 与 np.quantile 同口径的离散分位数
    return out


def write_deploy(path, vals, note, day):
    s = io.open(os.path.join(ROOT, path), encoding="utf-8").read()
    a = s.index("DEFAULT_PARAMS = {"); b = s.index("}\n", a) + 2
    blk = s[a:b]
    for k, v in vals.items():
        pat = re.compile(r"('%s': )('[^']*'|[^,\n}]+)" % re.escape(k))
        if len(pat.findall(blk)) != 1:
            raise SystemExit("%s 里找不到唯一的 %s" % (path, k))
        blk = pat.sub(lambda m: m.group(1) + repr(v), blk)
    ns = {}
    exec(blk, ns)
    if any(ns["DEFAULT_PARAMS"][k] != v for k, v in vals.items()):
        raise SystemExit("写入核对失败:%s" % path)
    arch = os.path.join(ROOT, "strategies", "deploy", "_archive_%s" % dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d"))
    os.makedirs(arch, exist_ok=True)
    shutil.copy2(os.path.join(ROOT, path), os.path.join(arch, os.path.basename(path).replace(".py", "_before_refit_%s.py" % day)))
    line = "#      每日重估:%s(估计日 %s)\n" % (note, day)
    s = s[:a] + line + blk + s[b:]
    io.open(os.path.join(ROOT, path), "w", encoding="utf-8", newline="\n").write(s)


# 用户 10-15:"你永远不允许碰实盘"。本脚本只在本机算数、改本机文件;实盘由用户在 web 端参数面板自己贴输出的 YAML。


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    day = args[0] if args else (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y%m%d")
    trade_day = (dt.datetime.strptime(day, "%Y%m%d") + dt.timedelta(days=1)).strftime("%Y%m%d")
    log = os.path.join(ROOT, "logs", "daily_refit_%s.log" % day)
    if not os.path.isdir(os.path.join(ROOT, "data", "research5", "usdc_pairs", day)):
        raise SystemExit("没有 %s 的自采数据(data/research5/usdc_pairs/%s):采集没在跑?" % (day, day))
    for s in SYMS:                                                       # 1–3
        if not exists("data", "research7", "l2", "%s_%s.npz" % (s, day)):
            run([VPY, "scripts/research7/l2_prep.py", "own", day, s], log)
        if not exists("data", "research7", "market_l2", "%s_%s.npz" % (s, day)):
            run([VPY, "scripts/research7/l2_market.py", day, s], log)
        if not exists("data", "factors", "grid", "%s_%s.npz" % (s, day)):
            run([PY, "RDAgent_Factor/评估脚本/build_grid.py", "grid", s, day], log)
    have_bn = binance(day)                                               # 4
    if have_bn and not exists("data", "factors", "tox1", "%s.npz" % day):
        run([PY, "research/as2008/toxicity_tox.py", "calc", day], log)
    have_tox = exists("data", "factors", "tox1", "%s.npz" % day)
    if have_tox and "tox_bnpush_ask" not in np.load(os.path.join(ROOT, "data", "factors", "tox1", "%s.npz" % day)).files:
        raise SystemExit("data/factors/tox1/%s.npz 里没有 tox_bnpush(因子文件路径不对?),删掉它重算" % day)
    spec = importlib.util.spec_from_file_location("off", os.path.join(ROOT, "research", "as2008", "github_ragoragino", "as_offline.py"))
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    hist = None
    if "--load-hist" in sys.argv:
        hist = json.load(open(sys.argv[sys.argv.index("--load-hist") + 1], encoding="utf-8"))
    res = {"fit_day": day, "trade_day": trade_day, "binance_published": have_bn, "instances": {}}
    for sym, (name, path) in DEPLOY.items():
        r = M.estimate_day(sym, [day])                                   # 5
        keys = [k for k in KEYS[sym] if have_tox or k not in ("beta_bnpush", "beta_obi")]
        vals = {k: float(r[k]) for k in keys}
        kept = [k for k in KEYS[sym] if k not in keys]
        if hist and name in hist:                                        # 6(旧办法:实盘负载直方图;10-15 起只作核对)
            h = hist[name]
            if isinstance(h, str):
                h = json.loads(h)["stats"]["load_hist_12_18"]
            vals["load_edges"] = ",".join("%g" % x for x in edges_from_hist(h, day))
        else:                                                            # 6(10-15 起默认:用户"门槛按回测同一办法标")
            # 实盘适配器按交易所毫秒成组发布(depth_group: exchange_ms)后,策略数到的条数 = 有价位变化的交易所毫秒数 + 成交笔数,
            # 与回测数据每毫秒一行同口径;门槛按 as_offline.estimate_load_edges 同样的分位对齐办法,用估计日的自录数据标
            sys.path.insert(0, os.path.join(ROOT, "scripts", "research7"))
            import live_load_edges as LLE
            e, _ = LLE.edges_msgroup(day, sym)
            vals["load_edges"] = ",".join("%g" % x for x in e)
        note = "更新 " + "、".join(vals) + ("" if not kept else ";保持旧值 " + "、".join(kept) + "(币安日档未发布)")
        res["instances"][name] = dict(values=vals, kept=kept, note=note, yaml="".join("%s: %r\n" % (k, v) for k, v in vals.items()))
        print("== %s(估计日 %s,用于 %s)\n%s\n%s" % (name, day, trade_day, note, res["instances"][name]["yaml"]), flush=True)
        if "--write-deploy" in sys.argv:                                 # 7
            write_deploy(path, vals, note, day)
            print("已写入 %s" % path, flush=True)
    os.makedirs(OUTD, exist_ok=True)
    json.dump(res, open(os.path.join(OUTD, "%s.json" % trade_day), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
