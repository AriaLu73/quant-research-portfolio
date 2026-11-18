#!/usr/bin/env python3
"""research5 A-2: record Binance USD-M futures best bid / ask over the public websocket (no key, no orders).

Why: Binance publishes no historical bookTicker for 2026, so A-1 had to rebuild Binance quotes from trades. For the final,
never-seen exam of the cross-venue strategy we record the real quotes ourselves, together with KuCoin's books
(usdc_pair_recorder.py --l3 none --l2 <same contracts> --out data/research5/xvenue_ku).
A row is written only when a symbol's bid or ask PRICE changes (size-only updates are dropped: Binance is the deep side,
its sizes do not bind us), which cuts the volume by an order of magnitude.
Output: data/research5/xvenue_bn/<YYYYMMDD>/<HH>.csv.gz, rows
  recv_ns,symbol,trade_time_ms(T),event_time_ms(E),bid,bid_qty,ask,ask_qty
Recorded on the home PC: use the exchange times T / E for alignment, never recv_ns.
Stop: create data/research5/xvenue_bn/STOP, or let --hours run out.
Usage: python scripts/detach.py --log logs/r5_xvenue_bn.log -- .venv/Scripts/python.exe scripts/research5/binance_bookticker_recorder.py --hours 240
"""
import argparse, asyncio, gzip, json, os, site, sys, time

try:
    import websockets
except ModuleNotFoundError:     # started via WMI (scripts/detach.py): the per-user site dir is not on sys.path
    site.addsitedir("AppData/Roaming/Python/Python%d%d/site-packages" % sys.version_info[:2])
    import websockets

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rec_common as C       # fresh_gz, single_instance, stalled
OUT = os.path.join(ROOT, "data", "research5", "xvenue_bn")
STALL_S = 45.0               # 22 symbols never stay silent this long: a quiet connection is a dead one -> reconnect
WS = "wss://fstream.binance.com/stream?streams="
SYMBOLS = ("BTCUSDT,ETHUSDT,ZECUSDT,NEARUSDT,DOGEUSDT,HYPEUSDT,1000PEPEUSDT,SUIUSDT,LTCUSDT,UNIUSDT,TAOUSDT,ADAUSDT,ARBUSDT,AKEUSDT,ENAUSDT,ONDOUSDT,"
           "LINKUSDT,XMRUSDT,ONEUSDT,PUMPUSDT,DOTUSDT,WLDUSDT,USELESSUSDT,INJUSDT")


def price_changed(last, sym, bid, ask):
    """True when the bid or ask price of sym differs from the last row written for it (and remembers the new pair)."""
    if last.get(sym) == (bid, ask):
        return False
    last[sym] = (bid, ask)
    return True


def row_of(recv_ns, d):
    """bookTicker payload -> CSV row."""
    return f'{recv_ns},{d["s"]},{d.get("T", "")},{d.get("E", "")},{d["b"]},{d["B"]},{d["a"]},{d["A"]}\n'


class Sink:
    def __init__(self):
        self.key, self.fh, self.n, self.flushed = None, None, 0, time.time()

    def write(self, recv_ns, line):
        key = time.strftime("%Y%m%d%H", time.gmtime(recv_ns // 1_000_000_000))
        if key != self.key:
            if self.fh:
                self.fh.close()
            self.fh, _ = C.fresh_gz(os.path.join(OUT, key[:8]), key[8:], "", ext=".csv.gz")     # never append to an existing file
            self.key = key
        self.fh.write(line)
        self.n += 1
        if time.time() - self.flushed > 30:
            self.fh.flush()
            self.flushed = time.time()


async def run(symbols, stop_at):
    sink, last, backoff = Sink(), {}, 1.0
    url = WS + "/".join(s.lower() + "@bookTicker" for s in symbols)
    while time.time() < stop_at and not os.path.exists(os.path.join(OUT, "STOP")):
        try:
            async with websockets.connect(url, max_size=None, ping_interval=None, close_timeout=5) as ws:
                backoff = 1.0
                print(time.strftime("%F %T"), "connected", len(symbols), "symbols", flush=True)
                t_conn = last_msg = time.time()
                while time.time() < stop_at and time.time() - t_conn < 23 * 3600:       # Binance drops a connection after 24 h
                    try:
                        raw = await asyncio.wait_for(ws.recv(), 10)
                    except asyncio.TimeoutError:
                        if os.path.exists(os.path.join(OUT, "STOP")):
                            return
                        if C.stalled(last_msg, time.time(), STALL_S):
                            raise RuntimeError(f"no message for {STALL_S:.0f} s")
                        continue
                    ns = time.time_ns()
                    last_msg = time.time()
                    d = json.loads(raw).get("data")
                    if d and d.get("e") == "bookTicker" and price_changed(last, d["s"], d["b"], d["a"]):
                        sink.write(ns, row_of(ns, d))
                    if sink.n and sink.n % 200_000 == 0:
                        print(time.strftime("%F %T"), "rows", sink.n, flush=True)
                        sink.n += 1
        except Exception as e:  # noqa: BLE001 - reconnect on anything
            print(time.strftime("%F %T"), "disconnect", repr(e)[:200], flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
    if sink.fh:
        sink.fh.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--symbols", default=SYMBOLS)
    ns = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    lock = C.single_instance(OUT)
    asyncio.run(run([s for s in ns.symbols.split(",") if s], time.time() + ns.hours * 3600))
