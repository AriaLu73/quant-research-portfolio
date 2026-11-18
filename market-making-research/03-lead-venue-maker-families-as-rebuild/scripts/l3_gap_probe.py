"""What are the single missing sequence numbers in the level3v2 files: lost messages or numbers never published?"""
import gzip, os, sys, collections
import orjson
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
f = os.path.join(ROOT, "data", "research5", "usdc_pairs_l3usdt", sys.argv[1], f"{sys.argv[2]}_XBTUSDTM_l3.jsonl.gz")
subj = collections.Counter(); around = collections.Counter(); keys = {}
last = None; prev_s = None; first_oid = None
recv, opened = set(), set()
lost_recv = lost_open = n_done = n_match = 0
gap_dt = []; examples = []
rows = []
for line in gzip.open(f, "rb"):
    i = line.find(b"\t")
    m = orjson.loads(line[i + 1:])
    d = m.get("data"); s = m.get("subject")
    if not d or not s:
        continue
    subj[s] += 1
    keys.setdefault(s, set()).update(d.keys())
    sn = d.get("sequence", m.get("sn"))
    if last is not None and sn == last + 2:
        around[(prev_s, s)] += 1
        if len(examples) < 6:
            examples.append((prev_row, line[i + 1:i + 400]))
    elif last is not None and sn > last + 2:
        gap_dt.append((sn - last - 1, (int(line[:i]) - prev_local) // 1000000, int(d["ts"]) // 1000000))
    last = sn; prev_s = s; prev_row = line[i + 1:i + 400]; prev_local = int(line[:i])
    oid = d.get("orderId")
    if s == "received":
        if first_oid is None:
            first_oid = int(oid)
        recv.add(oid)
    elif s == "open":
        opened.add(oid)
    elif s == "match":
        n_match += 1
        mk = d.get("makerOrderId")
        if not mk:
            empty_mk = globals().get("empty_mk", 0) + 1
        elif first_oid and int(mk) > first_oid and mk not in opened:
            lost_open += 1
    elif s == "done":
        n_done += 1
        if first_oid and int(oid) > first_oid and oid not in recv:
            lost_recv += 1
        recv.discard(oid); opened.discard(oid)
print("subjects", dict(subj))
for k, v in keys.items(): print(k, sorted(v))
print("single gaps by (before, after):", around.most_common(12))
print("orders created in-file: done without received", lost_recv, "of", n_done, "| match on maker never opened", lost_open, "of", n_match)
print("big gaps (missing, local gap ms, exchange ts ms):", gap_dt[:20], "| matches with empty maker id:", globals().get("empty_mk", 0))
for a, b in examples: print(a.decode()); print(b.decode()); print()
