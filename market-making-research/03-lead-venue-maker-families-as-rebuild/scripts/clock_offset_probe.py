#!/usr/bin/env python3
"""Clock offset between the KuCoin futures clock, the Binance futures clock and this machine (standard library only).

NTP-style: ask each venue for its server time over a kept-alive connection; offset = server time − midpoint of our send / receive
times, known to within half the round trip. The lowest round trips give the tightest bound. Servers answer in whole milliseconds
(rounded down), so +0.5 ms is added. Public endpoints, no keys, nothing written to disk.
Usage: python3 clock_offset_probe.py [samples per venue, default 300]
"""
import http.client
import json
import statistics
import sys
import time

VENUES = {
    "kucoin_futures": ("api-futures.kucoin.com", "/api/v1/timestamp", lambda j: j["data"]),
    "binance_futures": ("fapi.binance.com", "/fapi/v1/time", lambda j: j["serverTime"]),
}


def sample(conn, path, get):
    t0 = time.time_ns()
    conn.request("GET", path)
    body = conn.getresponse().read()
    t1 = time.time_ns()
    srv = (get(json.loads(body)) + 0.5) * 1e6
    return (t1 - t0) / 1e6, (srv - (t0 + t1) / 2) / 1e6          # round trip ms, server clock − our clock ms


def main(n):
    conns = {v: http.client.HTTPSConnection(h, timeout=10) for v, (h, _, _) in VENUES.items()}
    rows = {v: [] for v in VENUES}
    for v in VENUES:                                              # first request pays the TLS handshake
        sample(conns[v], VENUES[v][1], VENUES[v][2])
    for _ in range(n):
        for v, (_, path, get) in VENUES.items():
            try:
                rows[v].append(sample(conns[v], path, get))
            except Exception:
                conns[v] = http.client.HTTPSConnection(VENUES[v][0], timeout=10)
        time.sleep(0.0137)                                        # not a multiple of 1 ms: spreads the rounding error
    est = {}
    for v, r in rows.items():
        r.sort()
        best = r[:max(len(r) // 4, 1)]                            # lowest round trips
        off = statistics.median(x[1] for x in best)
        est[v] = off
        print(f"{v}: samples {len(r)}, round trip min {r[0][0]:.2f} / median {statistics.median(x[0] for x in r):.2f} ms; "
              f"server clock − our clock {off:+.2f} ms (± {best[-1][0] / 2:.2f} ms at most; spread of the best quarter "
              f"{min(x[1] for x in best):+.2f} … {max(x[1] for x in best):+.2f})")
    print(f"KuCoin clock − Binance clock: {est['kucoin_futures'] - est['binance_futures']:+.2f} ms")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
