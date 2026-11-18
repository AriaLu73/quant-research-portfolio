"""阶段 0:每个 UTC 日的录制缺口分布(附录第 7 条:阈值由用户在看到分布后定)。
输入 research_mm/data/quality/<sym>_<day>.json(l3_quality.py 产物)。
覆盖 = ∪ 每个小时文件 [first.ts, last.ts] − 文件内 time_gaps(> 5 s 的静默) − 文件间断点;缺口 = UTC 日 − 覆盖。
输出 reports/step00/gaps_<sym>.csv / .md
"""
import datetime as dt
import glob
import json
import os
import sys

NS = 1_000_000_000
ROOT = r""
REPRO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QDIR = os.path.join(ROOT, "research_mm", "data", "quality")


def union(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def day_bounds(day):
    t = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    return t, t + 86400 * NS


def run(sym):
    rows, md = [], []
    for p in sorted(glob.glob(os.path.join(QDIR, f"{sym}_2026????.json"))):
        q = json.load(open(p, encoding="utf-8"))
        day = q["day"]
        d0, d1 = day_bounds(day)
        cov, cuts, silence = [], [], []
        for f in q["files"]:
            if not f["first"]:
                continue
            cov.append([f["first"][1], f["last"][1]])
            lost_sn = {g[3] for g in f["sn_gaps"]} | {b[2] for b in f["breaks"] if b[2] is not None}
            for g in f["time_gaps"]:                 # [前一条 ts, 本条 ts, sn]:序号连续 = 交易所静默(没丢消息);否则 = 录制丢失
                if g[2] in lost_sn:
                    cuts.append([g[0], g[1]])
                else:
                    silence.append((g[1] - g[0]) / NS)
            for b in f["breaks"]:
                if b[0] is not None:
                    cuts.append([b[0], b[0] + 1])
        cov = union([[max(a, d0), min(b, d1)] for a, b in cov if min(b, d1) > max(a, d0)])
        # 减去静默
        res = []
        for a, b in cov:
            cur = a
            for c, e in union(cuts):
                if e <= cur or c >= b:
                    continue
                if c > cur:
                    res.append([cur, c])
                cur = max(cur, e)
            if cur < b:
                res.append([cur, b])
        covered = sum(b - a for a, b in res)
        gaps = []
        cur = d0
        for a, b in res:
            if a > cur:
                gaps.append([cur, a])
            cur = b
        if cur < d1:
            gaps.append([cur, d1])
        gaps = [[a, b] for a, b in gaps if b - a >= NS]          # 断点标记只有 1 ns,不算缺口;缺口 ≥ 1 s 才计
        gl = sorted(((b - a) / NS for a, b in gaps), reverse=True)
        n_mid = sum(1 for a, b in gaps if a > d0 and b < d1)        # 日内缺口(不含日首尾未录)
        edge = sum((b - a) for a, b in gaps if a == d0 or b == d1) / NS
        rows.append(dict(day=day, hours_files=len(q["hours"]), covered_h=covered / NS / 3600, cover_frac=covered / (86400 * NS),
                         n_gaps=len(gaps), n_gaps_intraday=n_mid, edge_missing_h=edge / 3600,
                         gap_max_s=gl[0] if gl else 0, gaps_gt_60s=sum(1 for g in gl if g > 60), gaps_gt_600s=sum(1 for g in gl if g > 600),
                         gaps_gt_3600s=sum(1 for g in gl if g > 3600), gap_list_s=[round(g, 1) for g in gl[:8]],
                         silence_n=len(silence), silence_total_s=round(sum(silence), 1), silence_max_s=round(max(silence), 1) if silence else 0.0,
                         silence_gt_60s=sum(1 for x in silence if x > 60)))
    os.makedirs(os.path.join(REPRO, "reports", "step00"), exist_ok=True)
    import csv
    with open(os.path.join(REPRO, "reports", "step00", f"gaps_{sym}.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    md.append(f"# {sym} 每个 UTC 日的录制缺口(质量文件 {len(rows)} 天)\n")
    md.append("缺口 = 录制断点(丢序号 / 缺文件 / 截断 / 断流)与日首尾未录;静默 = 序号连续但 > 5 s 无消息(交易所没发,没丢),单列。")
    md.append("")
    md.append("| UTC 日 | 小时文件 | 覆盖 h | 覆盖率 | 缺口数 | 日内缺口 | 日首尾未录 h | 最大缺口 s | >60s | >600s | >3600s | 最大若干缺口 s | 静默数 | 静默合计 s | 最长静默 s | 静默>60s |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        md.append(f"| {r['day']} | {r['hours_files']} | {r['covered_h']:.2f} | {r['cover_frac']:.1%} | {r['n_gaps']} | {r['n_gaps_intraday']} | "
                  f"{r['edge_missing_h']:.2f} | {r['gap_max_s']:.0f} | {r['gaps_gt_60s']} | {r['gaps_gt_600s']} | {r['gaps_gt_3600s']} | {r['gap_list_s']} | "
                  f"{r['silence_n']} | {r['silence_total_s']} | {r['silence_max_s']} | {r['silence_gt_60s']} |")
    with open(os.path.join(REPRO, "reports", "step00", f"gaps_{sym}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "XBTUSDTM")
