#!/usr/bin/env python3
"""Latency from this host to Binance, standard library only (meant to be piped to python3 on the colo box; reads only
public endpoints, writes nothing).

  1. network round trip   TCP handshake time (SYN -> SYN-ACK) to each endpoint, with the resolved addresses
  2. REST round trip      GET <time endpoint> on a kept-alive TLS connection; also gives the clock offset to Binance
                          (server time minus the midpoint of our send / receive times, from the fastest sample)
  3. market data delay    futures and spot bookTicker / aggTrade streams over a raw websocket: our receive time minus the
                          exchange's transaction time T and event time E, corrected by the clock offset from step 2
Usage: python3 binance_latency_probe.py [seconds_per_stream]
"""
import base64, json, os, socket, ssl, struct, sys, time

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
TCP_TARGETS = ["fapi.binance.com", "fstream.binance.com", "api.binance.com", "stream.binance.com", "api-futures.kucoin.com"]
REST = [("fapi.binance.com", "/fapi/v1/time"), ("api.binance.com", "/api/v3/time")]
STREAMS = [("fstream.binance.com", 443, "/ws/btcusdt@bookTicker", "futures bookTicker"),
           ("fstream.binance.com", 443, "/ws/btcusdt@aggTrade", "futures aggTrade"),
           ("stream.binance.com", 9443, "/ws/btcusdt@trade", "spot trade")]


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]


def tcp_rtt(host, n=40):
    out, addrs = [], set()
    for _ in range(n):
        ip = socket.gethostbyname(host)
        addrs.add(ip)
        t0 = time.perf_counter()
        s = socket.create_connection((ip, 443), timeout=5)
        out.append((time.perf_counter() - t0) * 1000)
        s.close()
    return out, sorted(addrs)


def rest(host, path, n=30):
    ctx = ssl.create_default_context()
    s = ctx.wrap_socket(socket.create_connection((host, 443), timeout=5), server_hostname=host)
    req = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: keep-alive\r\n\r\n".encode()
    rtt, best = [], None
    for _ in range(n):
        t0 = time.time()
        s.sendall(req)
        buf = b""
        while b"serverTime" not in buf or not buf.rstrip().endswith(b"}"):
            buf += s.recv(4096)
        t1 = time.time()
        srv = json.loads(buf[buf.rindex(b"{"):])["serverTime"]
        d = (t1 - t0) * 1000
        rtt.append(d)
        if best is None or d < best[0]:
            best = (d, srv - (t0 + t1) / 2 * 1000)
        time.sleep(0.05)
    s.close()
    return rtt, best[1]


def ws_lags(host, port, path, secs):
    """Minimal websocket reader (text frames only): yields receive-time minus T and minus E in ms for each message."""
    ctx = ssl.create_default_context()
    s = ctx.wrap_socket(socket.create_connection((host, port), timeout=10), server_hostname=host)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    buf = buf.split(b"\r\n\r\n", 1)[1]
    dT, dE, end = [], [], time.time() + secs
    while time.time() < end:
        while len(buf) < 2:
            buf += s.recv(65536)
        op, ln, off = buf[0] & 0x0F, buf[1] & 0x7F, 2
        if ln == 126:
            while len(buf) < 4:
                buf += s.recv(65536)
            ln, off = struct.unpack(">H", buf[2:4])[0], 4
        elif ln == 127:
            while len(buf) < 10:
                buf += s.recv(65536)
            ln, off = struct.unpack(">Q", buf[2:10])[0], 10
        while len(buf) < off + ln:
            buf += s.recv(65536)
        now = time.time() * 1000
        payload, buf = buf[off:off + ln], buf[off + ln:]
        if op != 1:
            continue
        m = json.loads(payload)
        if "T" in m:
            dT.append(now - m["T"])
        if "E" in m:
            dE.append(now - m["E"])
    s.close()
    return dT, dE


def main():
    print("host", socket.gethostname(), time.strftime("%F %T UTC", time.gmtime()))
    print("1. network round trip (TCP handshake), ms")
    for h in TCP_TARGETS:
        try:
            x, ips = tcp_rtt(h)
            print(f"   {h:26s} min {min(x):6.2f}  p50 {pct(x, .5):6.2f}  p95 {pct(x, .95):6.2f}   {ips[:4]}")
        except Exception as e:  # noqa: BLE001
            print(f"   {h:26s} failed: {e!r}")
    off = {}
    print("2. REST round trip on an open connection, ms, and clock offset (Binance time - ours)")
    for host, path in REST:
        try:
            x, o = rest(host, path)
            off[host] = o
            print(f"   {host + path:34s} min {min(x):6.2f}  p50 {pct(x, .5):6.2f}  p95 {pct(x, .95):6.2f}   clock offset {o:+.2f} ms")
        except Exception as e:  # noqa: BLE001
            print(f"   {host + path:34s} failed: {e!r}")
    print(f"3. market data delay over websocket, {SECS:.0f} s per stream, ms (after removing the clock offset)")
    for host, port, path, name in STREAMS:
        try:
            dT, dE = ws_lags(host, port, path, SECS)
            o = off.get("fapi.binance.com" if "fstream" in host else "api.binance.com", 0.0)
            line = f"   {name:20s} n {len(dE):5d}"
            if dT:
                line += f"  since trade time T: min {min(dT) + o:6.2f} p50 {pct(dT, .5) + o:6.2f} p95 {pct(dT, .95) + o:6.2f}"
            if dE:
                line += f"  | since event time E: min {min(dE) + o:6.2f} p50 {pct(dE, .5) + o:6.2f} p95 {pct(dE, .95) + o:6.2f}"
            print(line)
        except Exception as e:  # noqa: BLE001
            print(f"   {name:20s} failed: {e!r}")


if __name__ == "__main__":
    main()
