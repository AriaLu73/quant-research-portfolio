#!/usr/bin/env python3
"""Data Readiness Report + DATASET REGISTRY(prompt §4/§5)。
读取 data/research/kucoin/audit_<day>.json,输出:
  docs/research/data_readiness.md
  data/research/dataset_registry.json
"""
import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KU = os.path.join(ROOT, "data", "research", "kucoin")


def main():
    days = sorted(f[6:14] for f in os.listdir(KU) if f.startswith("audit_"))
    reg = []
    lines = ["# Data Readiness Report(KuCoin 永续 XBTUSDTM,Tardis 原始 L2 增量 + 逐笔成交)", "",
             f"生成:{dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC;审计脚本 scripts/research/extract_kucoin_tardis.py", "",
             "检查项:缺失事件(时间缺口)、重复(成交 id 重复/帧内重复档)、乱序(交易所时间回跳)、时间戳异常、序号缺口(Tardis 无序号,以快照块数代理)、"
             "非法价/量、交叉簿、锁定簿、陈旧数据(>1s/>5s 无更新)。", "",
             "## 逐日汇总", "",
             "| day | L2 rows | frames | snapshot blocks | ts 回跳帧 (max ms) | 缺口>1s | 缺口>5s (max s) | 非法价/量 | crossed | locked | 帧内重复档 | trades | trade dup id | trade 乱序 | 簿延迟 p50/p99 ms |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in days:
        a = json.load(open(os.path.join(KU, f"audit_{d}.json")))
        t = a["trades"]
        lines.append(f"| {d} | {a['rows']:,} | {a['frames']:,} | {a['snapshot_blocks']} | {a['ts_backward_frames']} ({a['max_backward_us']/1000:.1f}) | {a['gap_gt_1s']} | {a['gap_gt_5s']} ({a['max_gap_us']/1e6:.1f}) | {a['bad_price']}/{a['neg_amount']} | {a['crossed_frames']} | {a['locked_frames']} | {a['dup_rows_in_frame']:,} | {t['rows']:,} | {t['dup_ids']} | {t['ts_backward']} | {a['book_lat_p50_us']/1000:.1f}/{a['book_lat_p99_us']/1000:.1f} |")
        day_dt = dt.datetime.strptime(d, "%Y%m%d")
        for h in range(24):
            quality = "ok"
            issues = []
            if a["hour_max_gap_us"][h] > 5_000_000:
                issues.append(f"gap {a['hour_max_gap_us'][h]/1e6:.1f}s")
            if a["hour_crossed_us"][h] > 0:
                issues.append("crossed")
            if a["hour_frames"][h] < 10000:
                issues.append("sparse")
            if issues:
                quality = "flag:" + ",".join(issues)
            reg.append({"dataset_id": f"ku_{d}_{h:02d}", "exchange": "kucoin", "symbol": "BTC-USDT (XBTUSDTM)",
                        "start_time": (day_dt + dt.timedelta(hours=h)).isoformat(), "end_time": (day_dt + dt.timedelta(hours=h + 1)).isoformat(),
                        "depth": "full L2 (incremental)", "event_count": a["hour_frames"][h], "l1_changes": a["hour_l1_changes"][h],
                        "trade_count": t["hour_trades"][h], "timestamp_resolution": "exchange ms (snapshot us)",
                        "max_gap_ms": a["hour_max_gap_us"][h] / 1000, "data_quality": quality,
                        "file_path": f"data/tardis_kucoin/book-{d}.csv.gz; data/tardis_kucoin/trades-{d}.csv.gz",
                        "schema_version": "tardis_incremental_book_L2_v1"})
    lines += ["", "## 逐小时事件数 / 成交数(数据集登记摘要)", "", "| dataset_id | frames | L1 changes | trades | max gap ms | quality |", "|---|---|---|---|---|---|"]
    for r in reg:
        lines.append(f"| {r['dataset_id']} | {r['event_count']:,} | {r['l1_changes']:,} | {r['trade_count']:,} | {r['max_gap_ms']:.0f} | {r['data_quality']} |")
    flagged = [r for r in reg if r["data_quality"] != "ok"]
    lines += ["", "## 结论", "",
              f"- 可用小时数:{len(reg) - len(flagged)}/{len(reg)};标记小时:{', '.join(r['dataset_id'] + '(' + r['data_quality'] + ')' for r in flagged) or '无'}。",
              "- 交易所时间回跳(≤ ~10ms)在研究流水线中按单调钳制处理(不丢事件、不前视);回测转换器同样钳制。",
              "- 帧内重复档 = Tardis 同一时间戳内同一价位多次更新(最后一次为准),非数据错误。",
              "- 快照块 = 文件头快照 + 断线重连快照;重连处簿会被重建,重建期间(同一帧内)不产生状态行。",
              "- 数据集划分(反过拟合):训练/研究池 = 2025-10-01、2026-01-01、2026-04-01 全部小时;OOS 池 = 2026-06-01、2026-07-01、2026-08-01,"
              "五个随机 1h 切片在参数冻结后以固定种子从 OOS 池抽取,训练阶段不触碰 OOS 池的策略级结果。"]
    os.makedirs(os.path.join(ROOT, "docs", "research"), exist_ok=True)
    open(os.path.join(ROOT, "docs", "research", "data_readiness.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    json.dump(reg, open(os.path.join(ROOT, "data", "research", "dataset_registry.json"), "w"), indent=1)
    print("\n".join(lines[:20]))
    print(f"registry: {len(reg)} datasets, flagged {len(flagged)}")


if __name__ == "__main__":
    main()
