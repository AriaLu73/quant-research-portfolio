"""导出某个 l3sim 代理的全部成交明细(用户 2026-11-07:"策略的所有成交明显整理成 P2_full_3.8ms_trades 文件给我")。
来源  data/step15/<sym>/<day>_<agent>.npz 的 fills(挂单成交)与 mos(市价单;含段末清算)。
输出  reports/step15/<agent_label>_trades_<sym>.csv(按时间排序,一行一笔),字段说明见同目录 *_字段说明.md。
用法  python export_trades.py <sym> <V_LO> <gamma> [--agent P2_full_L3.8] [--label P2_full_3.8ms]
"""
import csv
import datetime as dt
import glob
import json
import os
import sys

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
with open(os.path.join(REPRO, "config", "contracts.yaml"), encoding="utf-8") as fh:
    CONTRACTS = yaml.safe_load(fh)
NS = 1_000_000_000
SEG_NS = 300 * NS


def iso(ts):
    return dt.datetime.fromtimestamp(ts / NS, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def main(sym, V_LO, gamma, agent, label):
    c = CONTRACTS[sym]; tick, mult, quote = float(c["tick"]), float(c["mult"]), c["quote"]
    unit = tick * mult
    files = sorted(glob.glob(os.path.join(REPRO, "data", "step15", sym, f"*_{agent}.npz")))
    days = [os.path.basename(p)[:8] for p in files]
    meta = json.loads(bytes(np.load(glob.glob(os.path.join(REPRO, "data", "step13", sym, "dt1000", f"{days[0]}_g{gamma:g}_e{V_LO}_reb*.npz"))[0])["meta"]).decode())
    fee_t, reb_t = meta["fee_take_ticks"], meta["rebate_ticks"]          # tick/张
    rows = []
    for d, p in zip(days, files):
        day0 = int(dt.datetime.strptime(d, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
        z = np.load(p)
        for r in z["fills"]:
            ts, side, tk, qty, a0, a_fill, wait, sweep, lvl0, born = [int(x) for x in r]
            px = tk * tick
            rows.append(dict(ts=ts, day=d, seg=(ts - day0) // SEG_NS, event="maker_fill", side="sell" if side == 1 else "buy", price=px, qty=qty,
                             notional=qty * px * mult, cash=(px if side == 1 else -px) * qty * mult, rebate=reb_t * qty * unit, taker_fee=0.0,
                             d_inv=-qty if side == 1 else qty, ahead0=a0, ahead_at_fill=a_fill, queue_wait_ms=wait / 1e6, sweep_qty=sweep,
                             level0_ticks=lvl0, decision_ts=born, mid=None, spread_ticks=None))
        for r in z["mos"]:
            ts, e, px_t, seg, mid2, spr = r
            ts = int(ts); seg_now = (ts - day0) // SEG_NS
            px = px_t * tick
            rows.append(dict(ts=ts, day=d, seg=int(seg), event="segment_end_liquidation" if int(seg) != seg_now else "market_order", side="buy" if e > 0 else "sell",
                             price=px, qty=abs(int(e)), notional=abs(e) * px * mult, cash=-e * px * mult, rebate=0.0, taker_fee=fee_t * abs(e) * unit,
                             d_inv=int(e), ahead0=None, ahead_at_fill=None, queue_wait_ms=None, sweep_qty=None, level0_ticks=None, decision_ts=None,
                             mid=mid2 * tick, spread_ticks=int(spr)))
        # 日末残余库存按当日最后一个有效中价计价(与 Table 11 的段 PnL 口径一致:未清算的残余按中价记),记为一行虚拟平仓
        inv_day = sum(r["d_inv"] for r in rows if r["day"] == d)
        if inv_day != 0:
            sys.path.insert(0, HERE); import step15_report as R
            ts_m, mid_m = R.mids(sym, d)
            t_end = max(r["ts"] for r in rows if r["day"] == d)
            mid_end = float(R.mid_at(ts_m, mid_m, t_end)) * tick
            rows.append(dict(ts=t_end + 1, day=d, seg=(t_end - day0) // SEG_NS, event="day_end_mark_to_market", side="sell" if inv_day > 0 else "buy", price=mid_end,
                             qty=abs(inv_day), notional=abs(inv_day) * mid_end * mult, cash=inv_day * mid_end * mult, rebate=0.0, taker_fee=0.0, d_inv=-inv_day,
                             ahead0=None, ahead_at_fill=None, queue_wait_ms=None, sweep_qty=None, level0_ticks=None, decision_ts=None, mid=mid_end, spread_ticks=None))
    rows.sort(key=lambda r: (r["ts"], 0 if r["event"] != "maker_fill" else 1))
    inv = 0; cum_ex = 0.0; cum_in = 0.0
    out = os.path.join(REPRO, "reports", "step15", f"{label}_trades_{sym}.csv")
    cols = ["ts_utc", "ts_ns", "day", "seg_300s", "event", "side", f"price_{quote}", "qty_contracts", f"notional_{quote}", f"cash_flow_{quote}", f"rebate_{quote}", f"taker_fee_{quote}",
            "inventory_after_contracts", f"cum_pnl_excl_rebate_{quote}", f"cum_pnl_incl_rebate_{quote}", "ahead0_contracts", "ahead_at_fill_contracts", "queue_wait_ms", "sweep_qty_contracts",
            "level0_ticks", "decision_ts_utc", f"mid_at_exec_{quote}", "spread_ticks_at_exec"]
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh); w.writerow(cols)
        for r in rows:
            inv += r["d_inv"]; cum_ex += r["cash"] - r["taker_fee"]; cum_in += r["cash"] - r["taker_fee"] + r["rebate"]
            w.writerow([iso(r["ts"]), r["ts"], r["day"], r["seg"], r["event"], r["side"], f"{r['price']:.4f}", r["qty"], f"{r['notional']:.4f}", f"{r['cash']:.6f}", f"{r['rebate']:.6f}", f"{r['taker_fee']:.6f}",
                        inv, f"{cum_ex:.4f}", f"{cum_in:.4f}", r["ahead0"], r["ahead_at_fill"], "" if r["queue_wait_ms"] is None else f"{r['queue_wait_ms']:.1f}", r["sweep_qty"], r["level0_ticks"],
                        "" if r["decision_ts"] is None else iso(r["decision_ts"]), "" if r["mid"] is None else f"{r['mid']:.4f}", "" if r["spread_ticks"] is None else r["spread_ticks"]])
    n_f = sum(r["event"] == "maker_fill" for r in rows); n_m = sum(r["event"] == "market_order" for r in rows); n_l = sum(r["event"] == "segment_end_liquidation" for r in rows); n_k = sum(r["event"] == "day_end_mark_to_market" for r in rows)
    print(f"{sym} {agent}: 行数 {len(rows)}(挂单成交 {n_f}、市价单 {n_m}、段末清算 {n_l}、日末按中价计价 {n_k});现金腿(不含返佣,已扣 taker 费) {cum_ex:+.2f} {quote},返佣 {cum_in - cum_ex:+.2f},含返佣 {cum_in:+.2f};日末残余库存合计 {inv} 张 → {out}")


if __name__ == "__main__":
    sym, V_LO, gamma = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
    arg = lambda f, d: sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d
    main(sym, V_LO, gamma, arg("--agent", "P2_full_L3.8"), arg("--label", "P2_full_3.8ms"))
