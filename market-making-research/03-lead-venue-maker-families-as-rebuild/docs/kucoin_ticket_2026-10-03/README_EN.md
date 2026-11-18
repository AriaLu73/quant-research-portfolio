# Order entry delay inside the exchange on our Unified Account — request for diagnosis

**From:** ME Capital (market maker, Futures OUR_FEE_TIER)
**Account:** UID [id removed], Unified Account (UTA); API key remark [id removed]
**Colocation:** source IP OUR_IP (OUR_DATACENTER OUR_DATACENTER, zone OUR_DATACENTER), KuCoin colo endpoints
**Order entry:** private WebSocket order channel (`/v2/private`, `op: uta.order` / `uta.cancel`); REST `/api/ua/v2/unified/order/*` as fallback
**Period measured:** 2026-10-02 18:49 – 21:03 UTC
**Contracts:** XBTUSDCM (3,307 orders) and XBTUSDTM (23 orders); all limit, post-only, cross margin, 44 – 223 contracts

## What we see

About one in eight of our orders spends 10 – 50 ms inside the exchange between the moment it is received and the moment
it rests in the book. This happens when the market is busy, and other participants get slower then too; but at the same
load some participants almost never wait while we (and at least one other large sender, at the same instants) do, and
orders that the exchange received **after** ours enter the book **before** ours. See "Same load, two groups" below.

Our side of the path is fast and stable: from our engine sending the order to the exchange's "received" timestamp the
median is 1.16 ms and the 99th percentile 3.07 ms.

## How it was measured

Both timestamps come from the exchange, on the exchange's clock.

1. **Public feed** `/contractMarket/level3v2`: every `open` message carries `orderTime` (order received) and `ts`
   (order resting in the book). We recorded this feed for all participants and looked up our own orders by `orderId`.
2. **Private pushes** for our own orders (`orderAll`): the first push when the order is received and the push when it
   is open. The two sources agree.

## Numbers (time from `orderTime` to `ts`, ms)

| XBTUSDCM, 18:49 – 21:03 UTC | orders | p50 | p90 | p95 | p99 | slower than 10 ms | slower than 20 ms |
|---|---|---|---|---|---|---|---|
| Our orders | 3,307 | 1.43 | 11.70 | 18.70 | 36.86 | 12.7% | 4.5% |
| All other participants | 109,082 | 2.1 | 3.7 | 5.3 | 20.9 | 2.3% | 1.0% |

(The percentiles in the second row are those of all 112,389 orders including ours; the shares are for the other
participants only.) The two most active order senders on this contract, identified only by the pattern of their public
`clientOid`, have 0.8% and 0.3% of their orders slower than 10 ms.

On XBTUSDTM we only sent 23 orders in this period: 7 of them (30%) took more than 20 ms, against 1.1% of all
3.5 million orders on that contract.

See `entry_delay_XBTUSDCM.png` and `summary_entry_delay.csv`.

## Same load, two groups (19:00 – 21:03 UTC)

Most of our orders are sent when the price moves, which is when the exchange is busiest, so the raw comparison above
overstates the difference. Grouped by load (messages on XBTUSDCM + XBTUSDTM within ±50 ms of the order), the share of
orders taking more than 10 ms:

| messages per 100 ms | 0–343 | 343–744 | 744–1200 | 1200–1800 | >1800 |
|---|---|---|---|---|---|
| our orders | 5.4% | 5.3% | 7.5% | 19.8% | 42.0% |
| fastest large sender | 0.0% | 0.0% | 0.6% | 1.1% | 8.5% |
| another large sender | 2.2% | 2.5% | 3.5% | 6.1% | 2.5% |
| one other large sender | 0.7% | 2.0% | 11.4% | 27.9% | 49.9% |
| all other participants | 0.3% | 1.1% | 5.1% | 11.5% | 15.2% |

Weighted to our load, other participants have 6.0% of orders slower than 10 ms against our 11.9%. The slow sender in
the table is slow at the same instants as we are: when our order is slow, its orders within ±5 ms are slow 56% of the
time (9% when ours is fast); the fastest sender's orders, 1%. Example, one 5 ms window: ours [id removed]
received [time removed], resting [time removed] (31 ms); [id removed] received [time removed], resting [time removed] (34 ms);
[id removed] received [time removed], resting [time removed] (1 ms). Where the order is placed (improving the touch, joining it,
or deeper) does not change this. Senders are told apart only by the pattern of their public `clientOid`.

## Orders received later rest earlier

For each of our orders that took more than 10 ms we looked at other participants' orders whose `orderTime` was up to
5 ms **later** than ours. In 92% of these cases at least one of those later orders has a smaller `sequence` in the
level3 feed, i.e. it entered the book before our order (2.3 such orders on average). When our order is fast (within
3 ms) this happens in 1% of cases. So the matching engine is not stalled at these moments; our order is held somewhere
between receipt and the book.

`slow_orders_XBTUSDCM.csv` lists the 421 slow orders with `orderId`, `clientOid`, both timestamps, and for 219 of them
one example of an order that was received later and rested earlier (its `orderId` and timestamps).

## What we ruled out on our side

- **Our software and network:** engine send → exchange "received" timestamp is 1.16 ms at the median, 1.59 ms at p90,
  3.07 ms at p99.
- **Bursts of our own requests:** we usually send four orders within one millisecond. The share of slow orders is the
  same for the first, second, third and fourth order of a group (about 12% each), and the same for an order sent alone.
- **Idle time, side, size:** no difference.
- **Our request rate and open orders:** the delay does not depend on how many requests we sent in the previous 1 s or
  10 s, or on how many of our orders were resting (rank correlations −0.08 to 0.02).
- **Our own cancels in flight:** only 43 of 2,705 orders (19:00 – 21:03) had a cancel of ours sent in the previous 5 ms.
- **The WebSocket order channel:** a minimal script placing orders through REST showed the same pattern earlier the same
  day (received → open: median 0.3 ms, p90 5.9 ms, maximum 54 ms over 20 orders).

Cancels are affected as well: from our cancel request to the exchange's "cancelled" timestamp the median is 3.7 ms,
p90 15.6 ms, p99 32.4 ms (3,410 cancels). We cannot split this path because there is no "received" timestamp for cancels.

## Questions

1. At busy moments, which queue between `orderTime` and `ts` holds our orders for 10 – 50 ms, and why do some
   participants not wait in it? Is it per gateway, per connection, per account type (Unified vs classic), per API tier,
   a pre-trade risk / margin check of the Unified Account, or something specific to post-only orders under cross margin?
2. Is this delay specific to the Unified Account order path? Would the same orders through a classic futures account
   (or a sub-account in classic mode) avoid it?
3. Is there an order-entry path for market makers that does not go through this step (a dedicated gateway, a different
   endpoint or protocol, a priority setting)?
4. Does the same apply to cancels, and is there a faster cancel path?
5. Could you look up some of the listed `orderId`s in your internal logs and tell us where the time was spent?

We can run controlled tests at any time (specific contracts, order types, REST against WebSocket, with or without
post-only) and send the order ids.

## Files

| file | content |
|---|---|
| `summary_entry_delay.csv` | percentiles of `ts − orderTime` for our orders and for all participants, both contracts |
| `our_orders_XBTUSDCM.csv` | all 3,307 of our orders: `orderId`, `clientOid`, side, price, size, received (UTC), resting (UTC), delay ms |
| `our_orders_XBTUSDTM.csv` | the same for our 23 orders on XBTUSDTM |
| `slow_orders_XBTUSDCM.csv` | the 421 orders slower than 10 ms, with the number of later-received orders that rested earlier and one example |
| `entry_delay_XBTUSDCM.png` | share of orders slower than x ms, our orders against all other participants |

Times are UTC. `received` is `orderTime` (nanosecond stamp, shown to the microsecond); `resting` is `ts` of the `open`
message (millisecond resolution), so individual delays are accurate to about 1 ms.
