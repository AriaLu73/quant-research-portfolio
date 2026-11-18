#!/usr/bin/env python3
"""research3 LTK-0:按预登记规则(docs/research3/ltk_selection_2026-10-03.md 第 3、4 节)从 ltk_scan 结果选大 tick 合约。
规则(选品日 09-10、09-18、09-24 三天都要满足):share1 ≥ 0.70,η̂ ≤ 0.30,数据可用(stale_share ≤ 0.10、beyond_share ≤ 0.20);
真实吃单额三天中位 ≥ $1M/天。通过者按 π(三天中位)排序,前 10 个进第二步。09-21 只作附加列。
另报:合约间 η̂ 与 net5 的 Spearman 秩相关(预期为负)。
用法:Python314/python.exe scripts/research3/ltk_select.py"""
import os
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEL_DAYS = ("20260910", "20260918", "20260924")


def main():
    d = pd.read_csv(os.path.join(ROOT, "data", "research3", "ltk", "ltk_scan.csv"), dtype={"day": str})
    d = d[d.get("error").isna()] if "error" in d else d
    d["usable"] = (d.stale_share <= 0.10) & (d.beyond_share <= 0.20)
    d["large"] = (d.share1 >= 0.70) & (d.eta <= 0.30)
    s = d[d.day.isin(SEL_DAYS)]
    g = s.groupby("sym").agg(days=("day", "nunique"), cls=("cls", "first"), reb=("reb", "first"), tick_bp=("tick_bp", "median"),
                             share1=("share1", "median"), share1_min=("share1", "min"), tw_share1=("tw_share1", "median"),
                             eta=("eta", "median"), eta_max=("eta", "max"), pi_bp=("pi_bp", "median"),
                             real_usd=("real_usd", "median"), pair_share=("pair_share", "median"), q_over_v=("q_over_v", "median"),
                             gamma_mu=("gamma_mu", "median"), net5=("net5", "median"), usable_all=("usable", "all"), large_all=("large", "all"))
    g["passed"] = (g.days == 3) & g.usable_all & g.large_all & (g.real_usd >= 1e6)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 200)
    cols = ["cls", "reb", "tick_bp", "share1", "share1_min", "tw_share1", "eta", "eta_max", "pi_bp", "real_usd", "pair_share", "q_over_v", "gamma_mu", "net5"]
    print("contracts scanned on all three selection days: %d (usable all three days: %d)" % ((g.days == 3).sum(), ((g.days == 3) & g.usable_all).sum()))
    full = g[(g.days == 3) & g.usable_all]
    print("  of these: share1 >= 0.70 all three days %d | eta <= 0.30 all three days %d | both %d | real taker >= $1M/day %d" % (
        (full.share1_min >= 0.70).sum(), (full.eta_max <= 0.30).sum(), full.large_all.sum(), (full.real_usd >= 1e6).sum()))
    P = g[g.passed].sort_values("pi_bp", ascending=False)
    print("\nPASSED (%d), ranked by pi = tick_bp*(1/2 - eta) + rebate:" % len(P))
    print(P[cols].round(3).to_string() if len(P) else "  none")
    near = full[~full.index.isin(P.index) & full.large_all].sort_values("pi_bp", ascending=False)
    print("\nlarge tick on all three days but real taker < $1M/day (%d), top 15 by pi:" % len(near))
    print(near[cols].head(15).round(3).to_string() if len(near) else "  none")
    big = full[full.real_usd >= 1e6].sort_values("eta")
    print("\nreal taker >= $1M/day (%d): the 20 with the smallest eta (whether or not large tick):" % len(big))
    print(big[cols].head(20).round(3).to_string())
    x = full.dropna(subset=["eta", "net5"])
    rho = x.eta.rank().corr(x.net5.rank())
    xb = x[x.real_usd >= 1e6]
    print("\nindependent check (Dayri-Rosenbaum: smaller eta -> better maker outcome): Spearman(eta, net5) = %.3f over %d contracts; "
          "%.3f over the %d with >= $1M/day" % (rho, len(x), xb.eta.rank().corr(xb.net5.rank()), len(xb)))
    out = os.path.join(ROOT, "data", "research3", "ltk", "ltk_selection.csv")
    g.sort_values("pi_bp", ascending=False).to_csv(out)
    if len(P):
        top = P.head(10)
        extra = d[(d.day == "20260921") & d.sym.isin(top.index)].set_index("sym")[["share1", "eta", "pi_bp", "real_usd", "net5"]]
        print("\n09-21 (extra day, not used for selection) for the top 10:")
        print(extra.round(3).to_string() if len(extra) else "  not in the 09-21 files")
    print("\nwritten", out)


if __name__ == "__main__":
    main()
