#!/usr/bin/env python3
"""research5 SP-1: record KuCoin spot books and trades together with the best bid / ask of the same coin's USDT perpetual
(public feeds only, no auth, no orders).

Purpose: test "quote the thin spot pair around the liquid perpetual of the same venue, hedge on the perpetual".
  spot   /market/level2:<SYM>   L2 increments (per change: price, size, sequence; message time in ms)
         /market/match:<SYM>    every trade with taker and maker order ids
         REST /api/v1/market/orderbook/level2_100   top-100 snapshot after every connect and every --snap-s seconds
  perp   /contractMarket/tickerV2:<SYM>   best bid / ask; a line is written only when a PRICE changes (sizes are not needed
         for a hedge leg and would multiply the volume)
Output: data/research5/spot_perp/<YYYYMMDD>/<HH>_<sym>_{l2,trades,snap,bbo}.jsonl.gz, lines "<recv_ns>\t<raw json>";
status.txt every 5 minutes. Recorded on the home PC: use exchange timestamps, never recv_ns.
Universe: data/research5/spot_perp_universe_<date>.json (list of {spot, perp, ...}).
Usage: python scripts/detach.py --log logs/r5_spot_perp_recorder.log -- .venv/Scripts/python.exe scripts/research5/spot_perp_recorder.py --hours 240
"""
import argparse, asyncio, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research2"))
import aiohttp
import websockets
import kc_l3_recorder as R   # nap, status (file layout shared with the other recorders)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rec_common as C       # SafeSink, single_instance, stalled

SPOT_REST, FUT_REST = "https://api.kucoin.com", "https://api-futures.kucoin.com"
KIND = {"/market/level2": "l2", "/market/match": "trades", "/contractMarket/tickerV2": "bbo"}
PER_TOPIC = 90                      # symbols per subscribe message (KuCoin allows 100)
STALL_S = 45.0                      # 60 pairs never stay silent this long: a quiet connection is a dead one -> reconnect


def kind_of(topic):
    ch, sym = topic.rsplit(":", 1)
    return f"{sym}_{KIND.get(ch, ch.strip('/').replace('/', '_'))}"


def topic_of(raw):
    i = raw.find('"topic":"')
    return raw[i + 9: raw.find('"', i + 9)] if i >= 0 else ""


def bbo_prices(raw):
    """(best bid price, best ask price) strings of a tickerV2 message, or None."""
    i, j = raw.find('"bestBidPrice":"'), raw.find('"bestAskPrice":"')
    if i < 0 or j < 0:
        return None
    return raw[i + 16: raw.find('"', i + 16)], raw[j + 16: raw.find('"', j + 16)]


def bbo_changed(last, kind, raw):
    """True when the bid or ask price differs from the last line written for this contract (and remembers the new pair)."""
    p = bbo_prices(raw)
    if p is None or last.get(kind) == p:
        return False
    last[kind] = p
    return True


def chunks(prefix, syms, n=PER_TOPIC):
    return [prefix + ",".join(syms[i:i + n]) for i in range(0, len(syms), n)]


async def token(http, rest):
    async with http.post(f"{rest}/api/v1/bullet-public") as r:
        d = (await r.json())["data"]
    s = d["instanceServers"][0]
    return f"{s['endpoint']}?token={d['token']}", s["pingInterval"] / 1000.0


async def spot_snapshot(http, sink, sym):
    try:
        async with http.get(f"{SPOT_REST}/api/v1/market/orderbook/level2_100", params={"symbol": sym}, timeout=aiohttp.ClientTimeout(total=20)) as r:
            sink.write(f"{sym}_snap", await r.text())
    except Exception as e:                                      # noqa: BLE001 - recorder must keep running
        sink.marker(f"{sym}_snap", event="snapshot_error", err=repr(e))


async def snapshots(http, sink, syms, stop_at):
    for s in syms:
        if time.time() >= stop_at:
            return
        await spot_snapshot(http, sink, s)
        await asyncio.sleep(0.15)


async def stream(http, sink, name, rest, topics, snap_syms, stop_at, only_bbo_changes=False):
    """One WS connection; reconnects with backoff; takes spot snapshots of snap_syms after every connect."""
    backoff, last = 1.0, {}
    while time.time() < stop_at:
        try:
            url, ping_s = await token(http, rest)
            async with websockets.connect(url, max_size=None, ping_interval=None, close_timeout=5) as ws:
                await asyncio.wait_for(ws.recv(), 10)
                for i, t in enumerate(topics):
                    await ws.send(json.dumps({"id": f"{name}{i}", "type": "subscribe", "topic": t, "response": True}))
                sink.marker("connections", event="connect", conn=name, topics=len(topics))
                snap_task = asyncio.ensure_future(snapshots(http, sink, snap_syms, stop_at))
                backoff, last_ping, last_msg = 1.0, time.time(), time.time()
                while time.time() < stop_at:
                    if time.time() - last_ping > ping_s * 0.5:
                        await ws.send(json.dumps({"id": str(int(time.time() * 1000)), "type": "ping"}))
                        last_ping = time.time()
                    try:
                        raw = await asyncio.wait_for(ws.recv(), 5)
                    except asyncio.TimeoutError:
                        if C.stalled(last_msg, time.time(), STALL_S):
                            raise RuntimeError(f"no message for {STALL_S:.0f} s")
                        continue
                    ns = time.time_ns()
                    last_msg = time.time()
                    if '"type":"message"' not in raw:
                        if '"error"' in raw:
                            sink.marker("errors", event="ws_error", conn=name, raw=raw[:300])
                        continue
                    kind = kind_of(topic_of(raw))
                    if only_bbo_changes and not bbo_changed(last, kind, raw):
                        continue
                    sink.write(kind, raw, ns)
                snap_task.cancel()
        except Exception as e:                                  # noqa: BLE001 - reconnect on anything
            sink.marker("errors", event="disconnect", conn=name, err=repr(e)[:300])
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


async def periodic_snap(http, sink, syms, every, stop_at):
    while time.time() < stop_at:
        await R.nap(every, stop_at)
        await snapshots(http, sink, syms, stop_at)


async def main(ns):
    out = ns.out if os.path.isabs(ns.out) else os.path.join(ROOT, ns.out)
    os.makedirs(out, exist_ok=True)
    uni = json.load(open(ns.universe if os.path.isabs(ns.universe) else os.path.join(ROOT, ns.universe), encoding="utf-8"))
    spot, perp = [u["spot"] for u in uni], [u["perp"] for u in uni]
    stop_at = time.time() + ns.hours * 3600
    lock = C.single_instance(out)   # noqa: F841 - held for the life of the process
    sink = C.SafeSink(out)
    async with aiohttp.ClientSession() as http:
        tasks = [stream(http, sink, "spot_l2", SPOT_REST, chunks("/market/level2:", spot), spot, stop_at),
                 stream(http, sink, "spot_tr", SPOT_REST, chunks("/market/match:", spot), [], stop_at),
                 stream(http, sink, "perp_bbo", FUT_REST, chunks("/contractMarket/tickerV2:", perp), [], stop_at, only_bbo_changes=True),
                 periodic_snap(http, sink, spot, ns.snap_s, stop_at), R.status(sink, stop_at, out)]
        try:
            await asyncio.gather(*tasks)
        finally:
            sink.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="data/research5/spot_perp_universe_20261002.json")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--snap-s", type=float, default=300.0)
    ap.add_argument("--out", default="data/research5/spot_perp")
    asyncio.run(main(ap.parse_args()))
