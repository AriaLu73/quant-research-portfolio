# Research log

## Motivation

The experiment started from a live trading question: why did inventory-management intuition developed in ES perform poorly when transferred to BTC market making?

The working suspicion became that the two markets may have opposite short-horizon dependence at the one-second scale.

## ES experiment

1. Start from a large Databento ESU6 MBO CSV (~1.4 GB).
2. Reconstruct the order book from market-by-order events.
3. Track best bid and best ask.
4. Compute midprice as `(best_bid + best_ask) / 2`.
5. Sample to one-second frequency.
6. Compute midprice differences.
7. Plot the price series, ACF, and PACF.
8. Observe a negative lag-1 coefficient around -0.14; later lags are small.

The reconstruction stopped early, leaving ~15,542 seconds (~4h20m) in the exploratory sample.

## BTC experiment

1. Download Binance BTCUSDT one-second daily klines for 2026-10-20.
2. Extract the ZIP to disk.
3. Read the one-second close series.
4. Compute `diff(log(close))`.
5. Plot the price series, ACF, and PACF.
6. Observe a positive lag-1 coefficient around +0.15.

## Robustness check

The BTC return series was split into first and last halves of the day.

- First half ACF(1): +0.1620
- Last half ACF(1): +0.1492

This reduced the likelihood that the full-day result was caused by one isolated trend episode.

## Interpretation developed during the research

The key trading implication was not that ACF alone proves profitability. It was that a trader carrying an ES-style short-term mean-reversion prior into BTC inventory management may systematically make the wrong directional assumption after fills.

For market making, short-horizon directional expectations enter fair value, quote skew, cancellation, fill selection, hedging, and inventory decisions. Therefore, even a simple unconditional dependence test can reveal that a transferred market prior deserves re-examination.

## What remains untested

- multi-day / multi-regime stability;
- common price definition across ES and BTC;
- fill-conditional markout;
- queue position and execution probability;
- spread and fee economics;
- order-book imbalance and trade-flow conditioning;
- whether the signal survives realistic execution costs.
