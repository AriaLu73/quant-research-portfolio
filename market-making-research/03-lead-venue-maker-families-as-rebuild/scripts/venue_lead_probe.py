#!/usr/bin/env python3
"""research5: which venue moves first on BTC? A short live probe on public feeds (no keys, no orders).

Best bid / ask of the BTC perpetual on Binance, OKX, Bybit, Hyperliquid and KuCoin (plus Binance spot), each update kept
with the EXCHANGE's own timestamp and our receive time. Run from the home PC, so only exchange timestamps are used for
lead / lag; their clocks are NTP-level (about a millisecond), Hyperliquid stamps by block.
Writes one npz with (exchange ts ms, receive ns, mid) per venue; analyse with venue_lead_eval.py.
Usage: .venv/Scripts/python.exe scripts/research5/venue_lead_probe.py <minutes> <out.npz>
"""
import asyncio, json, sys, time
import aiohttp
import numpy as np

DATA = {}


def put(venue, ts_ms, bid, ask):
    DATA.setdefault(venue, []).append((float(ts_ms), time.time_ns(), (float(bid) + float(ask)) / 2))


async def ws_loop(http, name, url, subs, handler, stop_at, ping=None):
    while time.time() < stop_at:
        try:
            async with http.ws_connect(url, heartbeat=None if ping else 15) as ws:
                for s in subs:
                    await ws.send_json(s)
                last = time.time()
                while time.time() < stop_at:
                    try:
                        m = await ws.receive(timeout=5)
                    except asyncio.TimeoutError:
                        m = None
                    if ping and time.time() - last > 15:
                        await ws.send_str(ping) if isinstance(ping, str) else await ws.send_json(ping)
                        last = time.time()
                    if m is None:
                        continue
                    if m.type != aiohttp.WSMsgType.TEXT:
                        if m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                            break
                        continue
                    if m.data in ("pong", "ping"):
                        continue
                    try:
                        handler(json.loads(m.data))
                    except (KeyError, IndexError, TypeError, ValueError):
                        pass
        except Exception as e:                                   # noqa: BLE001 - keep the other venues running
            print(name, "reconnect:", repr(e)[:80], flush=True)
            await asyncio.sleep(1)


def h_binance_f(m):
    d = m.get("data", m)
    if d.get("e") == "bookTicker":
        put("binance_perp", d["T"], d["b"], d["a"])


def h_binance_s(m):
    if "b" in m and "a" in m and "u" in m:                       # spot bookTicker has no exchange time: use receive time
        put("binance_spot", time.time_ns() / 1e6, m["b"], m["a"])


def h_okx(m):
    for d in m.get("data", []):
        put("okx", d["ts"], d["bids"][0][0], d["asks"][0][0])


BYBIT = {}


def h_bybit(m):
    d = m.get("data")
    if d and m.get("topic", "").startswith("orderbook.1."):
        if d.get("b"):
            BYBIT["b"] = d["b"][0][0]
        if d.get("a"):
            BYBIT["a"] = d["a"][0][0]
        if "b" in BYBIT and "a" in BYBIT:
            put("bybit", m.get("cts") or m["ts"], BYBIT["b"], BYBIT["a"])


def h_hl(m):
    if m.get("channel") == "bbo":
        d = m["data"]
        b, a = d["bbo"]
        if b and a:
            put("hyperliquid", d["time"], b["px"], a["px"])


def h_kucoin(m):
    if m.get("subject") == "tickerV2":
        d = m["data"]
        put("kucoin", d["ts"] / 1e6, d["bestBidPrice"], d["bestAskPrice"])


async def main(minutes, out):
    stop_at = time.time() + minutes * 60
    async with aiohttp.ClientSession() as http:
        async with http.post("https://api-futures.kucoin.com/api/v1/bullet-public") as r:
            k = (await r.json())["data"]
        ku_url = f'{k["instanceServers"][0]["endpoint"]}?token={k["token"]}&connectId=probe'
        await asyncio.gather(
            ws_loop(http, "binance_perp", "wss://fstream.binance.com/stream?streams=btcusdt@bookTicker", [], h_binance_f, stop_at),
            ws_loop(http, "binance_spot", "wss://stream.binance.com:9443/ws/btcusdt@bookTicker", [], h_binance_s, stop_at),
            ws_loop(http, "okx", "wss://ws.okx.com:8443/ws/v5/public", [{"op": "subscribe", "args": [{"channel": "bbo-tbt", "instId": "BTC-USDT-SWAP"}]}], h_okx, stop_at, ping="ping"),
            ws_loop(http, "bybit", "wss://stream.bybit.com/v5/public/linear", [{"op": "subscribe", "args": ["orderbook.1.BTCUSDT"]}], h_bybit, stop_at, ping={"op": "ping"}),
            ws_loop(http, "hyperliquid", "wss://api.hyperliquid.xyz/ws", [{"method": "subscribe", "subscription": {"type": "bbo", "coin": "BTC"}}], h_hl, stop_at, ping={"method": "ping"}),
            ws_loop(http, "kucoin", ku_url, [{"id": "1", "type": "subscribe", "topic": "/contractMarket/tickerV2:XBTUSDTM", "response": True}], h_kucoin, stop_at, ping={"id": "p", "type": "ping"}),
        )
    np.savez_compressed(out, **{v: np.array(rows) for v, rows in DATA.items()})
    for v, rows in DATA.items():
        a = np.array(rows)
        print(f"{v:13s} updates {len(a):7d}  receive - exchange ts: median {np.median(a[:, 1] / 1e6 - a[:, 0]):7.1f} ms", flush=True)
    print("PROBE_DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]), sys.argv[2]))
