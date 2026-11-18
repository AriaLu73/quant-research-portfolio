"""research3: public BTC-USDC spread of every purchased hour (data/oos/ku_buyc), to pick the narrow hours for the v9 run.
Per hour: median spread bp (1 s grid), share of seconds with spread <= 1 bp, number of prints. Read-only; light (no pandas).
usage: uh_spread_scan.py [symbol=BTC-USDC]   -> data/research3/uh_val/spread_hours_<symbol>.csv"""
import gzip, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sym = sys.argv[1] if len(sys.argv) > 1 else "BTC-USDC"
SRC = os.path.join(ROOT, "data", "oos", "ku_buyc")
out = os.path.join(ROOT, "data", "research3", "uh_val", f"spread_hours_{sym}.csv")
done = set()
if os.path.exists(out):
    done = {l.split(",")[0] for l in open(out, encoding="utf-8").read().splitlines()[1:]}
else:
    open(out, "w", encoding="utf-8").write("hour,median_spread_bp,share_le_1bp,prints\n")
for h in sorted(os.listdir(SRC)):
    if h in done:
        continue
    day = h.split("_")[0]
    p = os.path.join(SRC, h, "kucoin", "swap", sym, "feed_raw", f"depth_deltas-{day}.jsonl.gz")
    if not os.path.exists(p):
        continue
    B, A, bb, ba = {}, {}, None, None
    nxt, sp = None, []
    with gzip.open(p, "rt") as f:
        for l in f:
            o = json.loads(l)
            if o.get("snapshot"):
                B.clear(); A.clear(); bb = ba = None
            for px, q in o["bids"]:
                x = float(px)
                if float(q) == 0:
                    if B.pop(x, None) is not None and x == bb:
                        bb = None
                else:
                    B[x] = 1
                    if bb is not None and x > bb:
                        bb = x
            for px, q in o["asks"]:
                x = float(px)
                if float(q) == 0:
                    if A.pop(x, None) is not None and x == ba:
                        ba = None
                else:
                    A[x] = 1
                    if ba is not None and x < ba:
                        ba = x
            if not (B and A):
                continue
            if bb is None:
                bb = max(B)
            if ba is None:
                ba = min(A)
            t = o["ts_ns"]
            if nxt is None:
                nxt = t + 60_000_000_000
            while t >= nxt:                      # 1 s grid, state before this update is not kept: use the current one
                if ba > bb:
                    sp.append((ba - bb) / ((ba + bb) / 2) * 1e4)
                nxt += 1_000_000_000
    n = 0
    tp = os.path.join(SRC, h, "kucoin", "swap", sym, "feed_raw", f"ticks-{day}.jsonl.gz")
    if os.path.exists(tp):
        with gzip.open(tp, "rt") as f:
            n = sum(1 for _ in f)
    if sp:
        s = sorted(sp)
        open(out, "a", encoding="utf-8").write("%s,%.3f,%.3f,%d\n" % (h, s[len(s) // 2], sum(x <= 1.0 for x in s) / len(s), n))
    print(h, len(sp), flush=True)
print("SCAN DONE", flush=True)
