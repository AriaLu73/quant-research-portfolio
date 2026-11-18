#!/usr/bin/env python3
"""research7 宽价差合约:ltk_live_replay.py 的结果汇总(8–9 月,实盘策略类 MM_LTK_PROBE_v1,L2 推断排队)。

用途      每个合约 × 每天 × 两个方案:成交、盈亏、每笔净值、尾部亏损、排在最前的比例、消息量、各安全措施的触发次数;
          再按合约、按天汇总。
所属阶段  阶段 8 探针的补充检验。
列的含义  盈亏 = 当天结束时 现金 + 持仓 × 中间价 − 手续费(返佣为负的手续费);
          每笔净值 = 60 秒 markout + 返佣 我方费率(成交额加权);最大回撤 / 最差 N 分钟 = 逐秒盈亏路径上的值;
          最前 = 成交时我方严格优于别人最优价的笔数占比;成对 = 被判为不按盘口成交、未分给我方的成交量占全部成交量;
          t = 逐日盈亏的均值 / 标准误(天数少,只作参考)。
用法      .venv/Scripts/python.exe scripts/research7/ltk_live_report.py
"""
import json
import os

import numpy as np

import ltk_live_replay as R

REBATE_BP = OUR_FEE
H_S = 60


def one(sym, day, name):
    base = os.path.join(R.OUT, "%s_%s_%s" % (sym, day, name))
    if not os.path.exists(base + ".json"):
        return None
    z, st = np.load(base + ".npz"), json.load(open(base + ".json", encoding="utf-8"))
    f, m, p = z["fills"], z["mids"], z["pnl"]
    out = dict(st=st, n=len(f), usd=float((f[:, 2] * f[:, 3]).sum()) if len(f) else 0.0, pnl=float(p[-1, 1]) if len(p) else 0.0,
               dd=0.0, w1=0.0, w5=0.0, w30=0.0, net_bp=float("nan"), net_usd=0.0, exit_share=0.0, mkt=0.0)
    if len(p):
        v, sec = p[:, 1], p[:, 0]
        out["dd"] = float((np.maximum.accumulate(v) - v).max())
        for mins in (1, 5, 30):
            j = np.searchsorted(sec, sec - mins * 60, side="left")
            out["w%d" % mins] = float((v - v[j]).min())
    if len(f):
        k = np.clip(np.searchsorted(m[:, 0], f[:, 0] // 10**9 + H_S, side="left"), 0, len(m) - 1)
        mo = f[:, 1] * (m[k, 1] - f[:, 2]) / f[:, 2] * 1e4 + REBATE_BP
        w = f[:, 2] * f[:, 3]
        out["net_bp"] = float((mo * w).sum() / w.sum())
        out["net_usd"] = float((mo * w).sum() / 1e4)
        out["exit_share"] = float(f[:, 5].mean())
    if len(m):
        out["mkt"] = float(st["trade_qty"]) * float(z["mult"]) * float(np.median(m[:, 1]))     # 当天全市场成交额(美元,按中位价折算)
    return out


def tstat(x):
    x = np.asarray(x, float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def main():
    lines = []

    def P(s=""):
        lines.append(s)
        print(s, flush=True)

    P("MM_LTK_PROBE_v1(实盘策略类)在 8–9 月数据上的回放 —— 每单 $%.0f、每合约持仓上限 $%.0f;L2 推断排队;币安延迟 %.0f ms" % (R.ORDER_USD, R.ORDER_USD, R.REF_DELAY_MS))
    P("股票合约 %d 个 × %d 天(盘口只有这几天);金属 / 大宗 %d 个 × %d 天" % (len(R.STOCKS), len(R.STOCK_DAYS), len(R.COMMS), len(R.COMM_DAYS)))
    detail = []
    for name in R.VARIANTS:
        res = {}
        for sym, day in R.JOBS:
            o = one(sym, day, name)
            if o is not None:
                res[(sym, day)] = o
        P()
        P("== 方案 %s(%s);已完成 %d / %d 个合约日" % (name, "门槛 −0.25 跳 + 0.10 σ60,文件默认值" if name == "vol" else "门槛 −0.25 跳,theta_sigma = 0", len(res), len(R.JOBS)))
        P("%-8s %4s %7s %10s %9s %8s %7s %7s %7s %8s %7s %6s %6s %6s %6s %6s %8s" % (
            "合约", "天数", "成交", "成交额$", "盈亏$", "每笔bp", "正天数", "t", "最差日", "最大回撤", "最差30m", "最前", "离场单", "亏损线", "成对", "占市场", "消息/天"))
        tot_day = {}
        for sym in R.SYMS:
            rs = [(d, o) for (s, d), o in res.items() if s == sym]
            if not rs:
                continue
            pn = [o["pnl"] for _, o in rs]
            usd = sum(o["usd"] for _, o in rs)
            fills = sum(o["st"]["fills"] for _, o in rs)
            P("%-8s %4d %7d %10.0f %+9.2f %+8.2f %4d/%-2d %+7.2f %+7.2f %8.2f %+7.2f %5.0f%% %5.0f%% %6d %5.0f%% %5.1f%% %8.0f" % (
                sym[:-5], len(rs), sum(o["n"] for _, o in rs), usd, sum(pn), sum(o["net_usd"] for _, o in rs) / max(usd, 1) * 1e4,
                sum(x > 0 for x in pn), len(pn), tstat(pn), min(pn), max(o["dd"] for _, o in rs), min(o["w30"] for _, o in rs),
                100 * sum(o["st"]["fills_front"] for _, o in rs) / max(fills, 1), 100 * float(np.mean([o["exit_share"] for _, o in rs])),
                sum(o["st"]["loss_stop"] for _, o in rs),
                100 * sum(o["st"]["paired_qty"] for _, o in rs) / max(sum(o["st"]["trade_qty"] for _, o in rs), 1),
                100 * usd / max(sum(o["mkt"] for _, o in rs), 1), float(np.mean([o["st"]["n_place"] + o["st"]["n_cancel"] for _, o in rs]))))
            for d, o in rs:
                tot_day.setdefault(d, [0.0, 0.0, 0.0, 0.0])
                g = tot_day[d]
                g[0] += o["pnl"]
                g[1] += o["usd"]
                if sym in R.COMMS:
                    g[2] += o["pnl"]
                    g[3] += o["usd"]
                detail.append("%s %-10s %s 成交 %5d 成交额 %9.0f 盈亏 %+8.2f 每笔 %+7.2f bp 回撤 %6.2f 最差30m %+6.2f 最前 %3.0f%% 亏损线 %d 新单 %d 撤单 %d 成对 %3.0f%% 无公允价 %s 抽空 %s" % (
                    name, sym[:-5], d, o["n"], o["usd"], o["pnl"], o["net_bp"], o["dd"], o["w30"], 100 * o["st"]["fills_front"] / max(o["st"]["fills"], 1),
                    o["st"]["loss_stop"], o["st"]["n_place"], o["st"]["n_cancel"], 100 * o["st"]["paired_qty"] / max(o["st"]["trade_qty"], 1),
                    o["st"].get("no_fair_share"), o["st"].get("wide_share")))
        for grp, syms in (("股票合约", R.STOCKS), ("金属 / 大宗", R.COMMS), ("全部", R.SYMS)):
            sel = [o for (s, d), o in res.items() if s in syms]
            if not sel:
                continue
            usd = sum(o["usd"] for o in sel)
            days = sorted({d for (s, d) in res if s in syms})
            byday = [sum(o["pnl"] for (s, d), o in res.items() if s in syms and d == dd) for dd in days]
            P("%s合计:%d 个合约日,成交额 $%s,盈亏 $%+.2f(每天 $%+.2f,%d 天里 %d 天为正,逐日 t %+.2f,最差一天 $%+.2f);每笔口径 %+.2f bp" % (
                grp, len(sel), format(round(usd), ","), sum(o["pnl"] for o in sel), float(np.mean(byday)), len(days), sum(x > 0 for x in byday), tstat(byday), min(byday),
                sum(o["net_usd"] for o in sel) / max(usd, 1) * 1e4))
        P("金属 / 大宗逐日盈亏($):" + "  ".join("%s %+.1f" % (d[4:], tot_day[d][2]) for d in sorted(tot_day) if d in R.COMM_DAYS))
    P()
    open(os.path.join(R.OUT, "live_replay_report.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n\n== 逐合约日明细\n" + "\n".join(detail) + "\n")


if __name__ == "__main__":
    main()
