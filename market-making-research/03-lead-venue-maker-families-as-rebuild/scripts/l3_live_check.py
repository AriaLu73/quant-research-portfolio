#!/usr/bin/env python3
"""Show, live, what KuCoin's public order-by-order feed sends. Prints only; nothing is saved, no API key, no orders.

Connects with the public token (POST https://api-futures.kucoin.com/api/v1/bullet-public), subscribes
/contractMarket/level3v2:<SYMBOL> and prints messages for a few seconds, then a per-subject count.
Usage: .venv/Scripts/python.exe scripts/research5/l3_live_check.py [SYMBOL=XBTUSDCM] [seconds=10]
"""
import asyncio, collections, json, sys, time
import aiohttp


async def main(sym, secs):
    async with aiohttp.ClientSession() as s:
        async with s.post("https://api-futures.kucoin.com/api/v1/bullet-public") as r:
            d = (await r.json())["data"]
        srv = d["instanceServers"][0]["endpoint"]
        print("token from api/v1/bullet-public (no API key); server", srv)
        async with s.ws_connect(f"{srv}?token={d['token']}&connectId=l3check") as ws:
            await ws.receive()
            await ws.send_json({"id": "1", "type": "subscribe", "topic": f"/contractMarket/level3v2:{sym}", "response": True})
            cnt, t0 = collections.Counter(), time.time()
            while time.time() - t0 < secs:
                try:
                    m = await ws.receive(timeout=secs)
                except asyncio.TimeoutError:
                    break
                j = json.loads(m.data)
                if j.get("type") == "message":
                    cnt[j["subject"]] += 1
                    if sum(cnt.values()) <= 12:
                        print(m.data)
                elif j.get("type") in ("ack", "error"):
                    print("reply:", m.data)
            print(f"{sym}, {secs} s: {dict(cnt)}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "XBTUSDCM", float(sys.argv[2]) if len(sys.argv) > 2 else 10))
