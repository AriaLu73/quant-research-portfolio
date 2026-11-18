Hi, a follow-up on the order entry delay on our account (UID [id removed], Unified Account, Futures OUR_FEE_TIER, colo source IP OUR_IP). We re-checked everything and need to correct one point and sharpen the question.

What we measure: for each order, `ts − orderTime` of its `open` message in your public `/contractMarket/level3v2` feed, i.e. both timestamps are yours. Our own side (our engine → your `orderTime`) is 1.2 ms median, 3.1 ms p99. All times below are UTC, 2026-10-02, XBTUSDCM.

1) Correction: when the market is busy, everybody gets slower, so "other participants are not slow" was too strong. But at the same load, participants split into two groups. At 744–1800 messages per 100 ms (XBTUSDCM + XBTUSDTM), the share of orders taking more than 10 ms is:
- the fastest large sender: 0.6–1.1%
- another large sender: 3.5–6.1%
- us: 7.5–19.8%
- one other large sender: 11.4–27.9%, slow at the same instants as us (when our order is slow, its orders within ±5 ms are slow 56% of the time; the fastest sender's orders, 1%)

Same 5 ms window, three orders:
- ours 495605371856031745: received 20:58:50.553293, resting .584 (31 ms)
- 495605371835072517: received .548487, resting .582 (34 ms)
- 495605371835043844: received .548950, resting .550 (1 ms)

2) Orders received after ours rest before ours:
- ours 495605399030927361: received 20:58:57.032027, resting .075
- 495605399030939658: received .032482 (later), resting .034 (earlier)

3) It is not our sending pattern: no relation to our request rate, our number of open orders, our own cancels in flight, price placement (touch vs deep), side or size; REST orders show the same as WebSocket.

Questions:
1. At busy moments, what queue do our orders wait in between `orderTime` and `ts`, and why do some participants not wait in it? Is it per gateway, per connection, per account type (Unified vs classic), or per API tier?
2. What should we change to be on the fast path: a classic futures account or sub-account, a different endpoint, a market-maker gateway, a priority setting?
3. Could you look up these order ids in your logs and tell us where the time was spent?
XBTUSDCM: 495573039476445187, 495578942044966916, 495579169187500034, 495581038337134595, 495588047585349641, 495590420819021827, 495605371856031745, 495605399030927361
XBTUSDTM: 495578262756462598, 495605523010359304

We can run any controlled test you suggest and send the order ids. Full data available if useful.
