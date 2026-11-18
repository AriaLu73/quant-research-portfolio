#!/usr/bin/env python3
"""research7 宽价差合约:第二版(离场单保留公允价规则 + 库存平移 + TTL 20 秒)对第一版的配对比较。

用途      按预登记 00_范围_阈值_预登记.md 第 19 节:在选择样本上选 k,在判读样本上只读一次,逐条给出判定 (a)–(d)。
所属阶段  阶段 8 探针的补充检验(第二版)。
列的含义  盈亏 = 当天结束时 现金 + 持仓 × 中间价 − 手续费;离场单净值 = 带离场标记的成交的 60 秒 markout + 价差 + 返佣(美元);
          日终持仓 = 当天最后的持仓名义金额(美元,绝对值);t = 逐日(按天合计)盈亏之差的均值 / 标准误。
用法      .venv/Scripts/python.exe scripts/research7/ltk_live_v2_report.py
"""
import json
import os

import numpy as np

import ltk_live_replay as R

REBATE_BP = OUR_FEE
NAMES = ("vol", "t20", "s025", "s05", "s10")
SEL_DAYS = tuple(d for d in R.COMM_DAYS if d <= "20260903")          # 选 k 的 9 天(预登记)
LABEL = {"vol": "第一版", "t20": "第一版 + TTL 20 秒", "s025": "第二版 k = 0.25", "s05": "第二版 k = 0.5", "s10": "第二版 k = 1.0"}


def one(sym, day, name):
    base = os.path.join(R.OUT, "%s_%s_%s" % (sym, day, name))
    if not os.path.exists(base + ".json"):
        return None
    z, st = np.load(base + ".npz"), json.load(open(base + ".json", encoding="utf-8"))
    f, m, p = z["fills"], z["mids"], z["pnl"]
    o = dict(pnl=float(p[-1, 1]) if len(p) else 0.0, n=len(f), usd=0.0, exit_usd=0.0, exit_net=0.0, norm_net=0.0, dd=0.0, w30=0.0, eod=0.0,
             loss_stop=st["loss_stop"], msgs=st["n_place"] + st["n_cancel"])
    if len(p):
        v, sec = p[:, 1], p[:, 0]
        o["dd"] = float((np.maximum.accumulate(v) - v).max())
        j = np.searchsorted(sec, sec - 1800, side="left")
        o["w30"] = float((v - v[j]).min())
    if len(f) and len(m):
        sec = f[:, 0] // 10**9
        ih = np.clip(np.searchsorted(m[:, 0], sec + 60, side="left"), 0, len(m) - 1)
        w = f[:, 2] * f[:, 3]
        net = (f[:, 1] * (m[ih, 1] - f[:, 2]) / f[:, 2] * 1e4 + REBATE_BP) * w / 1e4
        ex = f[:, 5] > 0.5
        o.update(usd=float(w.sum()), exit_usd=float(w[ex].sum()), exit_net=float(net[ex].sum()), norm_net=float(net[~ex].sum()),
                 eod=abs(float(f[-1, 4])) * float(m[-1, 1]))
    return o


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def main():
    lines = []

    def P(s=""):
        lines.append(s)
        print(s, flush=True)

    res = {n: {} for n in NAMES}
    for sym, day in R.JOBS:
        for n in NAMES:
            o = one(sym, day, n)
            if o is not None:
                res[n][(sym, day)] = o
    keys = [k for k in R.JOBS if all(k in res[n] for n in NAMES)]
    sel = [k for k in keys if k[0] in R.COMMS and k[1] in SEL_DAYS]
    ev = [k for k in keys if k not in sel]
    P("第二版对第一版 —— 8 个合约(剔除白银、原油、天然气);五个方案都跑完的合约日 %d / %d;选择样本 %d 个合约日,判读样本 %d 个" % (len(keys), len(R.JOBS), len(sel), len(ev)))

    def block(title, ks):
        P()
        P("== " + title)
        P("%-20s %7s %10s %9s %9s %9s %9s %8s %8s %8s %7s %8s" % ("方案", "成交", "成交额$", "盈亏$", "正常单$", "离场单$", "离场额$", "最大回撤", "最差30m", "最差一天", "亏损线", "日终持仓"))
        days = sorted({d for _, d in ks})
        out = {}
        for n in NAMES:
            r = [res[n][k] for k in ks]
            byday = [sum(res[n][k]["pnl"] for k in ks if k[1] == d) for d in days]
            out[n] = byday
            P("%-20s %7d %10.0f %+9.2f %+9.2f %+9.2f %9.0f %8.2f %+8.2f %+8.2f %7d %8.0f" % (
                LABEL[n], sum(o["n"] for o in r), sum(o["usd"] for o in r), sum(o["pnl"] for o in r), sum(o["norm_net"] for o in r), sum(o["exit_net"] for o in r),
                sum(o["exit_usd"] for o in r), max(o["dd"] for o in r), min(o["w30"] for o in r), min(byday), sum(o["loss_stop"] for o in r),
                float(np.mean([o["eod"] for o in r]))))
        return days, out

    _, so = block("选择样本:BZ + PAXG + XAUT,08-26 … 09-03", sel)
    pick = max(("s025", "s05", "s10"), key=lambda n: sum(so[n]))
    P("选定:%s(选择样本合计盈亏最高)" % LABEL[pick])
    days, eo = block("判读样本:其余 11 天的 BZ + PAXG + XAUT,以及股票合约的全部合约日(只读一次)", ev)
    P()
    P("== 判定(判读样本,%s 对 第一版)" % LABEL[pick])
    diff = np.asarray(eo[pick]) - np.asarray(eo["vol"])
    P("(a) 逐日盈亏之差:均值 $%+.2f / 天,合计 $%+.2f,t %+.2f(%d 天;其中 %d 天第二版更好) → %s" % (diff.mean(), diff.sum(), tstat(diff), len(diff), int((diff > 0).sum()), "满足" if tstat(diff) >= 2 else "不满足"))
    e1 = sum(res["vol"][k]["exit_net"] for k in ev)
    e2 = sum(res[pick][k]["exit_net"] for k in ev)
    P("(b) 离场单净值:第一版 $%+.2f → 第二版 $%+.2f → %s" % (e1, e2, "满足" if (e2 >= 0 or abs(e2) < 0.5 * abs(e1)) else "不满足"))
    d1, d2 = max(res["vol"][k]["dd"] for k in ev), max(res[pick][k]["dd"] for k in ev)
    w1, w2 = min(eo["vol"]), min(eo[pick])
    P("(c) 最大日内回撤 $%.2f → $%.2f;最差一天 $%+.2f → $%+.2f → %s" % (d1, d2, w1, w2, "满足" if (d2 <= 1.5 * d1 and w2 >= 1.5 * w1) else "不满足"))
    P("(d) 日终未平仓位(名义,平均每合约日):第一版 $%.0f → 第二版 $%.0f;超过 $100 的合约日 %d → %d(共 %d)" % (
        float(np.mean([res["vol"][k]["eod"] for k in ev])), float(np.mean([res[pick][k]["eod"] for k in ev])),
        sum(res["vol"][k]["eod"] > 100 for k in ev), sum(res[pick][k]["eod"] > 100 for k in ev), len(ev)))
    dt = np.asarray(eo["t20"]) - np.asarray(eo["vol"])
    P("另:只把 TTL 从 60 秒改成 20 秒(第一版其余不变):逐日之差合计 $%+.2f,t %+.2f" % (dt.sum(), tstat(dt)))
    P()
    P("== 各合约(全部样本):第一版 → %s 的盈亏 / 离场单净值 / 成交额" % LABEL[pick])
    for sym in R.SYMS:
        ks = [k for k in keys if k[0] == sym]
        if not ks:
            continue
        a = [res["vol"][k] for k in ks]
        b = [res[pick][k] for k in ks]
        da = np.asarray([x["pnl"] for x in b]) - np.asarray([x["pnl"] for x in a])
        P("   %-6s %2d 天  盈亏 $%+8.2f → $%+8.2f(差的 t %+5.2f;为正 %2d → %2d 天) 离场单 $%+7.2f → $%+7.2f  成交额 $%s → $%s" % (
            sym[:-5], len(ks), sum(x["pnl"] for x in a), sum(x["pnl"] for x in b), tstat(da), sum(x["pnl"] > 0 for x in a), sum(x["pnl"] > 0 for x in b),
            sum(x["exit_net"] for x in a), sum(x["exit_net"] for x in b), format(round(sum(x["usd"] for x in a)), ","), format(round(sum(x["usd"] for x in b)), ",")))
    alld = sorted({d for _, d in keys})
    for n in ("vol", pick):
        bd = [sum(res[n][k]["pnl"] for k in keys if k[1] == d) for d in alld]
        P("全部样本 %s:合计 $%+.2f,每天 $%+.2f,%d 天里 %d 天为正,逐日 t %+.2f,最差一天 $%+.2f" % (LABEL[n], sum(bd), float(np.mean(bd)), len(bd), sum(x > 0 for x in bd), tstat(bd), min(bd)))
    open(os.path.join(R.OUT, "live_v2_report.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
