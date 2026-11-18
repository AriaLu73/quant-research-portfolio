"""Step 4 批跑:每个 (合约, Δt, 日) 对 g1/g2/g3 累计状态计数(count, n_plus, n_minus, n_11),存 data/step04/<sym>/dt<ms>/<day>.npz。
训练窗模型 = 窗内各日计数相加(ArrivalModel 可加),所以按日存计数即可。另存每日的 Figure 5 序列(g1)。
输入  优先用 data/step02 的 frame 存档(含指标与缺口);没有就从 step01 ladder 重建。
用法  python step04_batch.py <sym> [dt_ms,...] [--tag base]
"""
import datetime as dt
import glob
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台 gbk 会在打印表格时崩

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPRO, "data"))
import arrivals as AR            # noqa: E402
import events as EV              # noqa: E402
import ladder_store as LS        # noqa: E402

NS = 1_000_000_000


def frame_from_step02(path):
    z = np.load(path)
    return EV.EventFrame(int(json.loads(bytes(z["meta"]).decode())["dt_ms"]), z["t0"], z["ind_plus"], z["ind_minus"], z["vol_plus"], z["vol_minus"],
                         z["n_plus"], z["n_minus"], z["mid2"], z["gap"], np.full(len(z["t0"]), -1)), json.loads(bytes(z["meta"]).decode())


def frame_from_step01(sym, day, dt_ms):
    files = sorted(glob.glob(os.path.join(REPRO, "data", "step01", sym, f"{day}_*.npz")))
    lads = [LS.load(p, keys=LS.LIGHT_KEYS) for p in files]
    t = int(dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc).timestamp()) * NS
    return EV.build(lads, dt_ms, t, t + 86400 * NS), dict(src=lads[0]["meta"]["src"])


def main():
    sym = sys.argv[1]
    dts = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else [1000]
    tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else "base"
    gs = {k: AR.GState(k) for k in ("g1", "g2", "g3")}
    rows = []
    for dt_ms in dts:
        od = os.path.join(REPRO, "data", "step04", sym, f"dt{dt_ms}")
        os.makedirs(od, exist_ok=True)
        s2 = sorted(glob.glob(os.path.join(REPRO, "data", "step02", sym, tag, f"dt{dt_ms}", "*.npz")))
        days = [os.path.basename(p)[:8] for p in s2] or sorted({os.path.basename(p)[:8] for p in glob.glob(os.path.join(REPRO, "data", "step01", sym, "*.npz"))})
        for day in days:
            p2 = os.path.join(REPRO, "data", "step02", sym, tag, f"dt{dt_ms}", f"{day}.npz")
            fr, meta = frame_from_step02(p2) if os.path.exists(p2) else frame_from_step01(sym, day, dt_ms)
            arrs, row = {}, dict(sym=sym, day=day, src=meta["src"], dt_ms=dt_ms, n=len(fr), n_gap=int(fr.gap.sum()))
            for k, g in gs.items():
                m = AR.ArrivalModel(g).add(fr).finalize()
                arrs[f"{k}_count"], arrs[f"{k}_plus"], arrs[f"{k}_minus"], arrs[f"{k}_11"] = m.count, m.n_plus, m.n_minus, m.n_11
                chk = m.check_legal()
                row[k] = dict(n_seen=chk["n_seen"], n_unseen=chk["n_unseen"], states_lt_30=chk["states_lt_30"], pi11_gt_min=chk["pi11_gt_min"],
                              base=m.base)
            t, M, P = AR.figure5_series(fr, AR.ArrivalModel(gs["g1"]).add(fr).finalize())
            np.savez_compressed(os.path.join(od, f"{day}.npz"), **arrs, fig5_t=t, fig5_M=M, fig5_P=P,
                                meta=np.bytes_(json.dumps(dict(sym=sym, day=day, dt_ms=dt_ms, src=meta["src"])).encode()))
            rows.append(row)
            print(f"{sym} {day} dt={dt_ms} src={meta['src']} g3 seen {row['g3']['n_seen']}/81 base pi+ {row['g3']['base']['pi_plus']:.4f}", flush=True)
    rep = os.path.join(REPRO, "reports", "step04")
    os.makedirs(rep, exist_ok=True)
    with open(os.path.join(rep, f"daily_{sym}.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1, default=float)
    print("STEP04_DONE", flush=True)


if __name__ == "__main__":
    main()
