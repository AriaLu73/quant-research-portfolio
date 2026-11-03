# ES vs BTC: Short-Horizon Autocorrelation and Market-Making Inventory Logic

This project documents an exploratory microstructure experiment comparing very short-horizon price dynamics in **E-mini S&P 500 futures (ES)** and **Bitcoin spot (BTCUSDT)**.

The motivation came from a practical market-making problem: inventory logic that felt natural in ES was performing poorly in BTC. The experiment asks whether the two markets exhibit different short-horizon return dependence, and whether that difference could matter for quoting and inventory management.

## Core question

> Can a market-specific short-horizon mean-reversion intuition from ES fail when transferred to BTC?

The experiment is deliberately simple: reconstruct or obtain a 1-second price series, compute 1-second changes/returns, inspect ACF/PACF, and compare the sign and magnitude of lag-1 dependence.

## Main exploratory findings

| Market | Price series used | Horizon | ACF(1) | Interpretation |
|---|---|---:|---:|---|
| ESU6 | reconstructed midprice | 1 second | ~ -0.14 | short-horizon mean reversion / bid-ask style reversal signature |
| BTCUSDT | Binance 1-second kline close | 1 second | ~ +0.15 | short-horizon continuation / momentum signature |
| BTCUSDT, first 12h | Binance 1-second kline close | 1 second | +0.1620 | positive dependence persists |
| BTCUSDT, last 12h | Binance 1-second kline close | 1 second | +0.1492 | positive dependence persists |

The BTC split-sample check was important because it showed that the positive lag-1 autocorrelation was not driven only by one isolated move within the day.

## Why this matters for market making

A market maker is constantly making short-horizon directional decisions even when quoting both sides. Fair value, quote skew, cancellation, fill selection, and inventory management all depend on an implicit forecast of future price.

If ES has a short-horizon reversal tendency while BTC has continuation at the same nominal horizon, then an inventory rule built around “a bad fill will mean-revert” can behave very differently across markets.

This project does **not** claim that a positive unconditional ACF mechanically implies a profitable momentum strategy, nor that every maker fill is adverse. It does show why transferring an ES-style inventory prior into BTC without validating the underlying price dynamics can be dangerous.

## Experimental workflow

### 1. ES: reconstruct a 1-second midprice series from MBO events

The ES source was a large Databento MBO CSV (~1.4 GB). The original reconstruction was interrupted before the full file finished processing, so the exploratory result used approximately **15,542 seconds (~4h20m)** of reconstructed data.

At each event, the local book state was updated, the best bid and best ask were tracked, and midprice was defined as:

\[
\text{mid}_t = \frac{\text{best bid}_t + \text{best ask}_t}{2}
\]

The event-level series was then sampled to 1-second frequency and price differences were computed:

\[
\Delta m_t = m_t - m_{t-1}
\]

ACF and PACF were inspected. The main visual result was approximately:

- ACF(1) ≈ **-0.14**
- PACF(1) ≈ **-0.14**
- PACF(2) ≈ **-0.04**
- later lags were near zero

### 2. BTC: obtain official Binance 1-second klines

BTCUSDT one-second klines were downloaded for **2026-10-20** from Binance public historical data. The daily ZIP was extracted to disk before reading into R.

The return series was:

\[
r_t = \log(C_t) - \log(C_{t-1})
\]

where \(C_t\) is the one-second close.

The resulting ACF/PACF showed positive lag-1 dependence, with ACF(1) visually around **+0.15**.

### 3. BTC robustness check: split the day in half

To test whether the full-day result was dominated by one large directional episode, the day was split into two equal 12-hour windows and ACF(1) was calculated separately.

- First 12h: **+0.1620**
- Last 12h: **+0.1492**

Both halves remained positive and similar in magnitude.

## Important methodological limitations

This is an exploratory comparison, not a controlled cross-market test.

1. **Different price definitions.** ES used reconstructed midprice differences; BTC used one-second kline close log returns.
2. **Incomplete ES reconstruction.** The ES result came from a partial run rather than the full source file.
3. **Potential discontinuities in ES sampling.** Distinct continuous segments may have been concatenated before calculating returns, which can contaminate lag statistics around segment boundaries.
4. **Single BTC day.** The BTC result was robust within that day, but not yet tested across many dates, volatility regimes, or sessions.
5. **Unconditional ACF is not fill-conditional markout.** Market-making adverse selection should ultimately be measured conditional on fills, side, queue position, spread, imbalance, and future markout.

These limitations are part of the project rather than hidden: the experiment was useful because it identified a hypothesis worth testing more rigorously.

## Repository structure

```text
.
├── README.md
├── R/
│   ├── 01_btc_download_and_acf.R
│   ├── 02_btc_split_sample.R
│   └── 03_es_midprice_acf_template.R
├── results/
│   └── summary_results.csv
├── data_notes/
│   ├── BTC_DATA.md
│   └── ES_DATA.md
├── figures/
│   └── README.md
└── .gitignore
```

## Reproducibility

The BTC scripts are designed to reproduce the public-data side of the experiment. The ES source data is not included in this repository; the ES script documents the reconstruction logic and requires the user to map the local Databento MBO schema if column names differ.

## Next research steps

The natural continuation is to move from unconditional autocorrelation to execution-conditioned microstructure tests:

- multi-day ACF stability across BTC and ES;
- midprice-vs-trade-price comparison;
- maker-fill markouts at 100 ms / 1 s / 5 s / 10 s;
- order-book imbalance and trade-sign conditioning;
- regime dependence by volatility and spread;
- inventory-control rules built on continuation vs mean-reversion priors.

## Research takeaway

> Experience in one market can become a liability in another when a market-specific intuition is mistaken for a universal principle.

The practical lesson from this experiment was not simply “BTC has momentum” or “ES mean-reverts.” It was that **inventory logic should be derived from the microstructure of the market being traded, not imported from another market by habit.**
