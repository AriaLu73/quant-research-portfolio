<div align="center">

# BTC Short-Horizon Predictability

**An empirical study of return persistence and order book signals.**

![Market: Binance BTCUSDT](https://img.shields.io/badge/Market-Binance_BTCUSDT-F0B90B?style=flat-square)
![Baseline: AR(1)](https://img.shields.io/badge/Baseline-AR(1)-2563EB?style=flat-square)
![Horizon: 100 ms](https://img.shields.io/badge/Horizon-100_ms-7C3AED?style=flat-square)

[Overview](#overview) · [Research Questions](#research-questions) · [Method](#method) · [Data](#data) · [Conclusion](#conclusion)

</div>

---

## Overview

I investigate whether recent BTC price movements help predict returns over the next 100 milliseconds.

I start with an **AR(1) baseline** for Binance BTCUSDT perpetual futures, then examine whether **order book imbalance (OBI)** adds information beyond past returns. The focus is on out-of-sample evidence—not an assumption that BTC follows an AR(1) process.

## Research Questions

> Does short-term dependence in BTC returns translate into useful predictions on unseen data?

| Focus | Question |
| :--- | :--- |
| **Return dependence** | Can the previous 100 ms mid-price return predict the next? |
| **Model adequacy** | Does AR(1) capture the main autocorrelation patterns? |
| **Predictive value** | Does it outperform a training-mean return baseline? |
| **Order book signals** | Does OBI improve predictions beyond AR(1)? |

## Method

**01 — Prepare the data**  
I construct non-overlapping mid-price returns from best bid and ask quotes, with explicit checks for missing data and time alignment.

**02 — Establish a baseline**  
I fit an AR(1) model with an intercept and compare its implied autocorrelation with the observed data.

**03 — Test on unseen data**  
I use chronological training, validation, and test splits, examine residual dependence, and compare prediction errors against a simple mean-return baseline.

**04 — Extend the model**  
I add top-of-book imbalance and test whether it provides incremental predictive value.

> **Evaluation principle:** Statistical significance, out-of-sample improvement, and trading profitability are separate claims. Mid-price predictability alone does not establish an executable trading edge.

## Data

| Item | Specification |
| :--- | :--- |
| **Venue** | Binance |
| **Instrument** | BTCUSDT USDⓈ-M perpetual futures |
| **Source** | [Binance Public Data](https://github.com/binance/binance-public-data) |
| **Records** | Historical `bookTicker`: best bid/ask prices and quantities |
| **Primary horizon** | 100 ms |
| **Candidate period** | March 2024, subject to archive validation |

Historical futures `bookTicker` availability is limited. I verify archive integrity and coverage before analysis. Trade prices and candles are not substitutes for the quote data required by this study.

---

## Conclusion

*To be completed after the empirical analysis.*

<!-- Summarize the evidence on return dependence, out-of-sample prediction, the incremental value of OBI, and the limits of the findings. Include negative results. -->
