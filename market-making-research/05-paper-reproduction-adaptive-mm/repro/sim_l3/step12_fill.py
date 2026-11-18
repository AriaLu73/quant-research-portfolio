"""Step 12 补跑(用户 2026-11-08:"现在启动没有跑完的回测")。
任务书 Step 12 要求每个 Δt 都回测全部测试日并按 g1/g2/g3 出 Table 8;11-07 之前 l3sim 列只跑了 10-16/17/18 三天、g3、Δt ∈ {100,250,500,1000},
2000 ms 没有 l3sim 回放。本脚本把缺的补齐:
  * Δt ∈ {250, 500, 2000, 1000, 100}(按此优先级)× 全部 9 个测试日 × {XBTUSDTM, XBTUSDCM, ETHUSDCM};
  * 每个 (合约, Δt, 日):缺 P2 完整版目录(γ*,ē = V_LO,该 Δt 自己的 Step 2–4 产物)就先建(不存 φ),再跑 step14_run(1.8 ms,--bbo,P1 g1/g2/g3 + P2 g3 同场);
  * 已有 {day}_bbo.npz、P1_M_g1/g2/g3 与 P2 文件的 (Δt, 日) 跳过;Δt = 1000 的旧文件(Table 10/11 的输入)先整目录备份到 backup_20261108/ 再重跑;
  * 每个合约全部跑完后重出 reports/step12/table8_l3sim_<sym>.md(五个 Δt、9 天、g1/g2/g3)。
并行 2、BelowNormal(用户 11-08:打游戏时给 CPU 让路)。日志 logs/step12_fill.log(本脚本)+ logs/step12_fill_<sym>_dt<dt>_<day>.log(每个子任务)。
用法  python step12_fill.py [--par 2] [--dts 250,500,2000,1000,100] [--syms XBTUSDTM,XBTUSDCM,ETHUSDCM]
"""
import glob
import os
import shutil
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
REPRO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import step14_batch as S14B    # noqa: E402

PY = sys.executable
FLAGS = 0x08000000 | 0x00004000          # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS
LOGS = os.path.join(REPRO, "logs")
V_LO = {"XBTUSDTM": 24, "XBTUSDCM": 74, "ETHUSDCM": 696}
KINDS = "g1,g2,g3"


def out_dir(sym, d):
    return os.path.join(REPRO, "data", "step14", sym) if d == 1000 else os.path.join(REPRO, "data", "step14", sym, f"dt{d}")


def test_days(sym):
    return sorted({os.path.basename(p)[:8] for p in glob.glob(os.path.join(REPRO, "data", "step01", sym, "202610*.npz"))})


def done(sym, d, day, gamma):
    od = out_dir(sym, d)
    need = [f"{day}_bbo.npz", f"{day}_P2_g{gamma:g}_L1.8.npz"] + [f"{day}_P1_M_{k}_L1.8.npz" for k in KINDS.split(",")]
    return all(os.path.exists(os.path.join(od, f)) for f in need)


def backup_dt1000(sym):
    od = out_dir(sym, 1000); bk = os.path.join(od, "backup_20261108")
    if os.path.exists(bk):
        return
    os.makedirs(bk)
    for p in glob.glob(os.path.join(od, "*.npz")) + glob.glob(os.path.join(od, "*.json")):
        shutil.copy2(p, bk)
    print(f"[backup] {sym} dt1000 → {bk}", flush=True)


def main(par, dts, syms):
    os.makedirs(LOGS, exist_ok=True)
    gam = {s: S14B.gamma_star(s) for s in syms}
    jobs = []
    for d in dts:
        for s in syms:
            if d == 1000:
                backup_dt1000(s)
            for day in test_days(s):
                if done(s, d, day, gam[s]):
                    continue
                jobs.append((s, d, day))
    print(f"[plan] {len(jobs)} 个 (合约, Δt, 日) 任务,并行 {par}:", flush=True)
    for j in jobs:
        print("   ", *j, flush=True)
    running, t_all = [], time.time()
    remaining_per_sym = {s: sum(1 for j in jobs if j[0] == s) for s in syms}
    while jobs or running:
        while jobs and len(running) < par:
            s, d, day = jobs.pop(0)
            name = f"step12_fill_{s}_dt{d}_{day}"
            code = (f"import sys,os; sys.path.insert(0, r'{HERE}'); sys.path.insert(0, r'{os.path.join(REPRO, 'b')}'); sys.path.insert(0, r'{os.path.join(REPRO, 'a')}');"
                    f"import step13_build as S13, step14_run as S14; import os;"
                    f"p=os.path.join(r'{REPRO}','data','step13','{s}','dt{d}','{day}_g{gam[s]:g}_e{V_LO[s]}.npz');"
                    f"(S13.build('{s}', {V_LO[s]}, '{day}', gamma={gam[s]}, dt_ms={d}, e_bar={V_LO[s]}, store_phi=False) if not os.path.exists(p) else None);"
                    f"S14.run('{s}', {V_LO[s]}, '{day}', lats=(1.8,), gamma={gam[s]}, dt_ms={d}, record_bbo=True, kinds=tuple('{KINDS}'.split(',')))")
            fh = open(os.path.join(LOGS, name + ".log"), "w", encoding="utf-8")
            running.append((name, s, subprocess.Popen([PY, "-X", "utf8", "-c", code], stdout=fh, stderr=subprocess.STDOUT, creationflags=FLAGS, cwd=REPRO), fh, time.time()))
            print(f"[start] {name}  {time.strftime('%m-%d %H:%M')}", flush=True)
        time.sleep(15)
        for x in running[:]:
            if x[2].poll() is not None:
                x[3].close(); running.remove(x)
                remaining_per_sym[x[1]] -= 1
                print(f"[end]   {x[0]} rc={x[2].returncode} t={(time.time() - x[4]) / 60:.0f} min  剩余任务 {len(jobs) + len(running)}", flush=True)
                if remaining_per_sym[x[1]] == 0:
                    r = subprocess.run([PY, "-X", "utf8", "-c",
                                        f"import sys; sys.path.insert(0, r'{HERE}'); import step12_l3sim as T; T.table('{x[1]}', {V_LO[x[1]]}, [100,250,500,1000,2000], {test_days(x[1])!r}, {gam[x[1]]})"],
                                       cwd=REPRO, creationflags=FLAGS, capture_output=True, text=True, encoding="utf-8", errors="replace")
                    print(f"[table8] {x[1]} rc={r.returncode}\n{r.stdout[-1500:]}\n{r.stderr[-800:]}", flush=True)
    print(f"STEP12_FILL_DONE 总耗时 {(time.time() - t_all) / 3600:.1f} h", flush=True)


if __name__ == "__main__":
    arg = lambda f, d: sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d
    main(int(arg("--par", "2")), [int(x) for x in arg("--dts", "250,500,2000,1000,100").split(",")], arg("--syms", "XBTUSDTM,XBTUSDCM,ETHUSDCM").split(","))
