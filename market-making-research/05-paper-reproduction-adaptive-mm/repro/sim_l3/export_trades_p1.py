"""导出 Table 8 l3sim 列里 P1_M_g3(原论文目录,1.8 ms)的全部成交明细(用户 2026-11-08:"XBTUSDTM 250 ms,XBTUSDCM 1000 ms,P1 原论文,这两个策略的 trades 给我看一下")。
来源  data/step14/<sym>[/dt<dt>]/<day>_P1_M_g3_L1.8.npz 的 fills(P1 没有市价单);中价序列 <day>_bbo.npz(L3 分辨率)。
口径  与 Table 8 l3sim 列一致:PnL 不含返佣 = 挂单成交 ± 价款 + 日末残余按当日最后中价计价;返佣 = 成交张数 × 返佣率 × 日末中价(USDT OUR_FEE / USDC OUR_FEE)。
输出  reports/step12/P1_M_g3_<dt>ms_trades_<sym>.csv(按时间排序,一行一笔)。
用法  python export_trades_p1.py <sym> <dt_ms> [--days 20261016,20261017,20261018 | all]   all = data/step14 里该 Δt 下全部有 P1 文件的日子
"""
import csv
import datetime as dt
import os
import sys

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as fh:
    CONTRACTS = yaml.safe_load(fh)
NS = 1_000_000_000
REBATE_BP = {"USDT": 0.7, "USDC": 1.2}


def iso(ts):
    return dt.datetime.fromtimestamp(ts / NS, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def main(sym, dt_ms, days):
    c = CONTRACTS[sym]; tick, mult, quote = float(c["tick"]), float(c["mult"]), c["quote"]
    od = os.path.join(REPRO, "data", "step14", sym) if dt_ms == 1000 else os.path.join(REPRO, "data", "step14", sym, f"dt{dt_ms}")
    rows = []
    for d in days:
        bp = os.path.join(od, f"{d}_bbo.npz")
        if os.path.exists(bp):
            z = np.load(bp); bts, bmid = z["ts"], z["mid2"] / 2.0          # L3 分辨率中价(只有 Step 12 样本日有)
        else:
            sys.path.insert(0, HERE); import step15_report as R
            bts, bmid = R.mids(sym, d)                                       # 其余日子用 ladder_store 50 ms 网格中价(Table 10/11 口径)
            bts = bts.astype(np.int64)
        mid_end = float(bmid[-1])
        reb_t = REBATE_BP[quote] * 1e-4 * mid_end                     # tick/张,与 step12_l3sim.collect 一致
        fl = np.load(os.path.join(od, f"{d}_P1_M_g3_L1.8.npz"))["fills"]
        day0 = int(dt.datetime.strptime(d, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
        i_born = np.searchsorted(bts, fl[:, 9], side="right") - 1
        i_fill = np.searchsorted(bts, fl[:, 0], side="left") - 1     # 成交前最后一个 BBO
        for k, r in enumerate(fl):
            ts, side, tk, qty, a0, a_fill, wait, sweep, lvl0, born = [int(x) for x in r]
            px = tk * tick
            m_born = float(bmid[max(i_born[k], 0)]) * tick
            m_fill = float(bmid[max(i_fill[k], 0)]) * tick
            dist = (tk - bmid[max(i_born[k], 0)]) if side == 1 else (bmid[max(i_born[k], 0)] - tk)
            # 成交后 5 s 中价(markout 用)
            j = np.searchsorted(bts, ts + 5 * NS, side="right") - 1
            m5 = float(bmid[j]) * tick if j >= 0 and bts[j] - ts <= 5_200_000_000 else None
            rows.append(dict(ts=ts, day=d, event="maker_fill", side="sell" if side == 1 else "buy", price=px, qty=qty, notional=qty * px * mult,
                             cash=(px if side == 1 else -px) * qty * mult, rebate=reb_t * qty * tick * mult, d_inv=-qty if side == 1 else qty,
                             ahead0=a0, ahead_at_fill=a_fill, wait=wait / 1e6, sweep=sweep, lvl0=lvl0, born=born, m_born=m_born, dist=dist, m_fill=m_fill,
                             mo5=None if m5 is None else ((m5 - px) if side == 0 else (px - m5)) / tick))
        inv_day = sum(r["d_inv"] for r in rows if r["day"] == d)
        if inv_day != 0:
            t_end = int(bts[-1])
            rows.append(dict(ts=t_end + 1, day=d, event="day_end_mark_to_market", side="sell" if inv_day > 0 else "buy", price=mid_end * tick, qty=abs(inv_day),
                             notional=abs(inv_day) * mid_end * tick * mult, cash=inv_day * mid_end * tick * mult, rebate=0.0, d_inv=-inv_day,
                             ahead0=None, ahead_at_fill=None, wait=None, sweep=None, lvl0=None, born=None, m_born=None, dist=None, m_fill=mid_end * tick, mo5=None))
    rows.sort(key=lambda r: r["ts"])
    inv = 0; cum_ex = 0.0; cum_in = 0.0
    rep = os.path.join(REPRO, "reports", "step12"); os.makedirs(rep, exist_ok=True)
    out = os.path.join(rep, f"P1_M_g3_{dt_ms}ms_trades_{sym}.csv")
    cols = ["ts_utc", "ts_ns", "day", "event", "side", f"price_{quote}", "qty_contracts", f"notional_{quote}", f"cash_flow_{quote}", f"rebate_{quote}",
            "inventory_after_contracts", f"cum_pnl_excl_rebate_{quote}", f"cum_pnl_incl_rebate_{quote}",
            "decision_ts_utc", f"mid_at_decision_{quote}", "quote_distance_ticks", f"mid_before_fill_{quote}", "markout_5s_ticks",
            "ahead0_contracts", "ahead_at_fill_contracts", "queue_wait_ms", "sweep_qty_contracts", "level0_ticks"]
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh); w.writerow(cols)
        for r in rows:
            inv += r["d_inv"]; cum_ex += r["cash"]; cum_in += r["cash"] + r["rebate"]
            f = lambda v, fmt: "" if v is None else format(v, fmt)
            w.writerow([iso(r["ts"]), r["ts"], r["day"], r["event"], r["side"], f"{r['price']:.4f}", r["qty"], f"{r['notional']:.4f}", f"{r['cash']:.6f}", f"{r['rebate']:.6f}",
                        inv, f"{cum_ex:.4f}", f"{cum_in:.4f}", "" if r["born"] is None else iso(r["born"]), f(r["m_born"], ".4f"), f(r["dist"], ".1f"), f(r["m_fill"], ".4f"),
                        f(r["mo5"], ".1f"), "" if r["ahead0"] is None else r["ahead0"], "" if r["ahead_at_fill"] is None else r["ahead_at_fill"], f(r["wait"], ".1f"),
                        "" if r["sweep"] is None else r["sweep"], "" if r["lvl0"] is None else r["lvl0"]])
    n_f = sum(r["event"] == "maker_fill" for r in rows); n_k = len(rows) - n_f
    qty = sum(r["qty"] for r in rows if r["event"] == "maker_fill"); notional = sum(r["notional"] for r in rows if r["event"] == "maker_fill")
    print(f"{sym} P1_M_g3 {dt_ms} ms {','.join(days)}: 挂单成交 {n_f} 笔 / {qty:,} 张 / ${notional:,.0f},日末计价行 {n_k};"
          f"不含返佣 {cum_ex:+.2f} {quote},返佣 {cum_in - cum_ex:+.2f},含返佣 {cum_in:+.2f} → {out}")


if __name__ == "__main__":
    sym, dt_ms = sys.argv[1], int(sys.argv[2])
    arg = lambda f, d: sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d
    days = arg("--days", "20261016,20261017,20261018")
    if days == "all":
        import glob
        od = os.path.join(REPRO, "data", "step14", sym) if dt_ms == 1000 else os.path.join(REPRO, "data", "step14", sym, f"dt{dt_ms}")
        days = ",".join(sorted(os.path.basename(p)[:8] for p in glob.glob(os.path.join(od, "*_P1_M_g3_L1.8.npz"))))
    main(sym, dt_ms, days.split(","))
