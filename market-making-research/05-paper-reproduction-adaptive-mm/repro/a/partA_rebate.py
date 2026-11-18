"""Part A 论文忠实回测 + maker 返佣(用户 我方费率-11-07:"提交 Part A 论文忠实,含返佣 我方费率 天的结果")。
Part A 本身无费率(无 taker 费、无返佣);本表只在逐日 PnL_T 上加 返佣 = 成交额 × r(USDT 线 我方费率,USDC 线 我方费率),不改任何回放。
Part A 全部是挂单成交,没有市价单;日末残余按日末深快照沿深度清算(Step 9),不计 taker 费。
输出  reports/partA/rebate_<sym>.md
用法  python partA_rebate.py <sym> [dt_ms]
"""
import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as fh:
    CONTRACTS = yaml.safe_load(fh)
REBATE_BP = {"USDT": 0.7, "USDC": 1.2}
ORDER_A = ["M_g1", "M_g2", "M_g3", "G_g3"] + [f"Level{i}" for i in range(1, 7)]


def load(sym, dt_ms, tag, prefix):
    od = os.path.join(REPRO, "data", "step10", sym, tag, f"dt{dt_ms}")
    rows, days = {}, []
    for p in sorted(glob.glob(os.path.join(od, f"{prefix}_*.json"))):
        d = json.load(open(p, encoding="utf-8"))
        d = d.get("results", d) if prefix == "expB" else d        # expB 外层 {results, meta}
        days.append(os.path.basename(p)[len(prefix) + 1:len(prefix) + 9])
        for n, r in d.items():
            rows.setdefault(n, []).append(r)
    return rows, days


def block(title, rows, days, order, quote, r_bp):
    md = [f"## {title}", "", f"测试日 {len(days)} 天:{days[0]}…{days[-1]}。货币 {quote}。返佣率 {r_bp} bp = 成交额 × {r_bp}e-4。",
          "", "| 方案 | 策略收益 PnL_T 均值 /日 | PnL_T 标准差 /日 | 返佣 均值 /日 | 策略收益 + 返佣 均值 /日 | 标准差 /日 | 9 天合计 策略收益 | 9 天合计 返佣 | 9 天合计 含返佣 | 含返佣为正的天数 | 成交笔数 /日 | 成交额 /日 | 成交额 /h | 策略收益 bp(按成交额) | 含返佣 bp |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in order:
        if n not in rows:
            continue
        rs = rows[n]
        P = np.array([r["PnL_T_usdt"] for r in rs]); V = np.array([r["notional_usdt"] for r in rs]); R = V * r_bp * 1e-4; T = P + R
        f = np.mean([r["n_fills"] for r in rs])
        bp = P.sum() / V.sum() * 1e4 if V.sum() > 0 else float("nan"); bpt = T.sum() / V.sum() * 1e4 if V.sum() > 0 else float("nan")
        md.append(f"| {n} | {P.mean():+,.2f} | {P.std(ddof=1):,.2f} | {R.mean():+,.2f} | {T.mean():+,.2f} | {T.std(ddof=1):,.2f} | {P.sum():+,.1f} | {R.sum():+,.1f} | {T.sum():+,.1f} | "
                  f"{int((T > 0).sum())}/{len(T)} | {f:,.0f} | ${V.mean():,.0f} | ${V.mean() / 24:,.0f} | {bp:+.2f} | {bpt:+.2f} |")
    md.append("")
    md.append("逐日(策略收益 / 返佣 / 含返佣," + quote + "):")
    md.append("")
    md.append("| 日 | " + " | ".join(n for n in order if n in rows) + " |")
    md.append("|---|" + "---|" * len([n for n in order if n in rows]))
    for i, d in enumerate(days):
        cells = []
        for n in order:
            if n in rows:
                r = rows[n][i]; reb = r["notional_usdt"] * r_bp * 1e-4
                cells.append(f"{r['PnL_T_usdt']:+,.0f} / {reb:+,.0f} / {r['PnL_T_usdt'] + reb:+,.0f}")
        md.append(f"| {d} | " + " | ".join(cells) + " |")
    md.append("")
    return md


def main(sym, dt_ms):
    c = CONTRACTS[sym]; quote = c["quote"]; r_bp = REBATE_BP[quote]
    md = [f"# Part A 论文忠实回测 + maker 返佣 —— {sym}, Δt = {dt_ms} ms, 9 天", "",
          "口径:回放与 reports/step10 的 expA / expB 完全相同(队首假设、无延迟、无 taker 费、全部挂单、日末残余沿日末深快照清算);"
          f"只在每天的 PnL_T 上加 返佣 = 当日挂单成交额 × {r_bp} bp。策略收益 = 原 PnL_T(不含返佣)。单位:{quote};成交额为名义金额({quote})。",
          "", "参数含义:PnL_T = 日末现金 + 残余库存按日末深快照沿深度清算的价值;返佣 = 成交额 × 返佣率;bp 列 = 9 天合计 ÷ 9 天成交额合计 × 1e4;"
          "成交笔数 = 有成交的决策区间数(一个区间内多笔吃单打到我方只算 1 笔)。", ""]
    rows, days = load(sym, dt_ms, "base", "expA")
    md += block("实验 A(Table 2/3 的方案:自适应 P1 目录 M_g1/M_g2/M_g3、非鞅 G_g3、固定档位 Level 1–6)", rows, days, ORDER_A, quote, r_bp)
    rows, days = load(sym, dt_ms, "base", "expB")
    if rows:
        md += block("实验 B(Table 4/5 的方案:非自适应到达模型)", rows, days, list(rows.keys()), quote, r_bp)
    rows, days = load(sym, dt_ms, "base_det", "expA")
    if rows:
        md += block("实验 C(Table 6/7 的方案:确定性需求变体)", rows, days, ORDER_A, quote, r_bp)
    rep = os.path.join(REPRO, "reports", "partA"); os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"rebate_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1000)
