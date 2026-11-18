#!/usr/bin/env python3
"""research5 X-3: record the USDC-margined perps and their USDT twins on KuCoin Futures (public feeds only, no auth, no orders).

Purpose: fresh, never-seen days for the USDC-maker / USDT-hedge line (all purchased days are used up), with order ids on
every public trade (paired prints can be removed exactly) and order-by-order data on the maker leg (queue-exact fills).
Reuses the tested pieces of scripts/research2/kc_l3_recorder.py (Sink, stream, periodic_snap, status); that file is not changed.
  --l3   symbols with the order-by-order feed (/contractMarket/level3v2), one connection each
  --l2   symbols with L2 increments + public trades + REST L2 snapshots (should include the --l3 symbols)
Output: data/research5/usdc_pairs/<YYYYMMDD>/<HH>_<sym>_{l3,l2,trades,snap}.jsonl.gz, lines "<recv_ns>\t<raw json>";
status.txt every 5 minutes. Recorded from the home PC: use exchange timestamps for event time, not recv_ns.
Stop: runs --hours then exits (pid is in the detach log).
Usage: python scripts/detach.py --log logs/r5_usdc_pair_recorder.log -- .venv/Scripts/python.exe scripts/research5/usdc_pair_recorder.py --hours 192
"""
import argparse, asyncio, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research2"))
import aiohttp
import kc_l3_recorder as R
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rec_common as C       # SafeSink, single_instance, stall_guard (only with --safe)

USDC = "XBTUSDCM,ETHUSDCM,SOLUSDCM,XRPUSDCM,SUIUSDCM"
USDT = "XBTUSDTM,ETHUSDTM,SOLUSDTM,XRPUSDTM,SUIUSDTM"
KIND = {"/contractMarket/level3v2": "l3", "/contractMarket/level2": "l2", "/contractMarket/execution": "trades"}


def kind_of(topic):
    ch, sym = topic.rsplit(":", 1)
    return f"{sym}_{KIND.get(ch, ch.strip('/').replace('/', '_'))}"


def plan(l3_syms, l2_syms, per_conn=4):
    """Connections as (name, topics, symbols to snapshot after connect): one per L3 symbol, L2+trades in groups of per_conn symbols."""
    conns = [(f"l3_{s}", [f"/contractMarket/level3v2:{s}"], []) for s in l3_syms]
    for i in range(0, len(l2_syms), per_conn):
        g = l2_syms[i:i + per_conn]
        conns.append((f"l2_{i // per_conn}", [f"/contractMarket/level2:{s}" for s in g] + [f"/contractMarket/execution:{s}" for s in g], g))
    return conns


async def main(ns):
    out = ns.out if os.path.isabs(ns.out) else os.path.join(ROOT, ns.out)
    os.makedirs(out, exist_ok=True)
    stop_at = time.time() + ns.hours * 3600
    l3 = [s for s in ns.l3.split(",") if s and s != "none"]
    l2 = [s for s in ns.l2.split(",") if s and s != "none"]       # "none" = no symbols (an empty argument does not survive detach.py)
    lock = C.single_instance(out) if (ns.safe or ns.guard) else None   # noqa: F841 - held for the life of the process
    if ns.guard:                    # keep the plain file names other tools expect: make this hour's files clean, then append
        print(time.strftime("%F %T"), "healed", C.heal_hour(out), "files of the current hour", flush=True)
    sink = C.SafeSink(out) if ns.safe else R.Sink(out)
    async with aiohttp.ClientSession() as http:
        tasks = [R.stream(http, sink, name, topics, kind_of, snaps, stop_at) for name, topics, snaps in plan(l3, l2)]
        tasks += [R.periodic_snap(http, sink, l2, ns.snap_s, stop_at), R.status(sink, stop_at, out)]
        if ns.safe or ns.guard:
            tasks.append(C.stall_guard(sink, ns.stall_s, stop_at))
        try:
            await asyncio.gather(*tasks)
        finally:
            sink.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--l3", default=USDC + ",XBTUSDTM")
    ap.add_argument("--l2", default=USDC + "," + USDT)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--snap-s", type=float, default=300.0)
    ap.add_argument("--out", default="data/research5/usdc_pairs")
    ap.add_argument("--safe", action="store_true", help="one instance per folder, never append to an existing file, exit when no data arrives for --stall-s")
    ap.add_argument("--guard", action="store_true", help="one instance per folder, heal this hour's files before appending (file names unchanged), exit when no data arrives for --stall-s")
    ap.add_argument("--stall-s", type=float, default=60.0)
    asyncio.run(main(ap.parse_args()))
