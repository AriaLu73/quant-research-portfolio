# KuCoin Futures public order-by-order (L3 / MBO) feed - minimal demo, no API key needed.
# pip install websockets
import asyncio, json, time, urllib.request, websockets

SYMBOL = "XBTUSDTM"          # BTC/USDT perpetual; XBTUSDCM = BTC/USDC, ETHUSDTM, SOLUSDTM ...
SECONDS = 10

req = urllib.request.Request("https://api-futures.kucoin.com/api/v1/bullet-public", data=b"", method="POST")
d = json.load(urllib.request.urlopen(req))["data"]
url = f'{d["instanceServers"][0]["endpoint"]}?token={d["token"]}&connectId=demo'


async def main():
    async with websockets.connect(url, max_size=None) as ws:
        print(await ws.recv())                                    # {"type":"welcome",...}
        await ws.send(json.dumps({"id": "1", "type": "subscribe",
                                  "topic": f"/contractMarket/level3v2:{SYMBOL}", "response": True}))
        t0, n = time.time(), 0
        while time.time() - t0 < SECONDS:
            msg = json.loads(await ws.recv())
            if msg.get("type") == "message":
                n += 1
                if n <= 20:
                    print(msg["subject"], msg["data"])
            else:
                print(msg)                                        # {"type":"ack"} on success
        print(f"{n} order events in {SECONDS} s")

asyncio.run(main())
