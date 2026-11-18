#!/usr/bin/env python3
"""Read-only: list every field that appears in recorded KuCoin feeds (lines "<recv_ns>\t<raw json>"), per subject.
Purpose (2026-10-28): check whether self-recorded L3 / public trades carry any user / account id.
Usage: .venv/Scripts/python.exe -I scripts/research5/l3_field_check.py <file.jsonl.gz> [...]
       .venv/Scripts/python.exe -I scripts/research5/l3_field_check.py --link <l3 file> [max messages]
  --link: per match, can maker / taker orderId be traced to its own received (clientOid)? what do update messages do?
"""
import collections, gzip, json, sys


def link(f, cap):
    recv = {}; first = {}; life = collections.defaultdict(list); matches = []; updates = []; n = 0
    with gzip.open(f, "rt", encoding="utf-8", errors="replace") as fh:
        try:
            for line in fh:
                p = line.rstrip("\n").split("\t", 1)
                if len(p) < 2: continue
                try: o = json.loads(p[1])
                except Exception: continue
                s = o.get("subject"); d = o.get("data") or {}
                if s is None: continue
                n += 1
                if n > cap: break
                if s == "received": recv[d["orderId"]] = d.get("clientOid")
                if s == "match":
                    matches.append(d)
                    for k in ("makerOrderId", "takerOrderId"): life[d.get(k)].append(("match", d.get("size"), d.get("remainSize")))
                else:
                    oid = d.get("orderId")
                    first.setdefault(oid, s)
                    life[oid].append((s, d.get("size") or d.get("reason"), d.get("price")))
                    if s == "update": updates.append(oid)
        except EOFError:
            pass
    def cnt(key):
        c = collections.Counter()
        for m in matches:
            oid = m.get(key)
            if not oid: c["empty id"] += 1
            elif oid not in recv: c["no received in file (older order)"] += 1
            elif recv[oid]: c["received + clientOid"] += 1
            else: c["received, clientOid empty"] += 1
        return dict(c)
    print("==", f, "messages", n, "matches", len(matches))
    print("  maker side:", cnt("makerOrderId"))
    print("  taker side:", cnt("takerOrderId"))
    print("  orders with received:", len(recv), " clientOid empty:", sum(1 for v in recv.values() if not v))
    pat = collections.Counter()
    for v in recv.values():
        if not v: continue
        if v.isdigit(): pat[f"digits|{len(v)}"] += 1
        else: pat["".join("9" if ch.isdigit() else ("a" if ch.isalpha() else ch) for ch in v)[:12] + f"..|{len(v)}"] += 1
    print("  clientOid shapes (top 8):", pat.most_common(8))
    print("  update messages:", len(updates))
    for oid in updates[:4]: print("   ", oid, "clientOid", recv.get(oid), "->", life[oid][:6])


if len(sys.argv) > 2 and sys.argv[1] == "--link":
    link(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 10**12)
    sys.exit(0)

for f in sys.argv[1:]:
    subj = collections.Counter(); keys = collections.defaultdict(collections.Counter); top = collections.Counter()
    reasons = collections.Counter(); n = 0; truncated = False
    with gzip.open(f, "rt", encoding="utf-8", errors="replace") as fh:
        try:
            for line in fh:
                p = line.rstrip("\n").split("\t", 1)
                if len(p) < 2: continue
                try: o = json.loads(p[1])
                except Exception: continue
                n += 1
                for k in o: top[k] += 1
                s = o.get("subject"); d = o.get("data") or {}
                subj[s] += 1
                for k in d: keys[s][k] += 1
                if s == "done": reasons[d.get("reason")] += 1
        except EOFError:
            truncated = True                               # recorder was stopped mid-hour
    print("==", f, "messages", n, "(truncated)" if truncated else "")
    print("  top-level:", sorted(top))
    for s in subj: print(f"  {s} ({subj[s]}):", sorted(keys[s]))
    if reasons: print("  done.reason:", dict(reasons))
