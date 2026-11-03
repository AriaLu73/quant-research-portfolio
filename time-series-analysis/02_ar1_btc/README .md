<div align="center">

# Order Book Imbalance Persistence

**An AR(1) study of short-horizon dynamics in L2 market data.**

![Data: L2 Order Book](https://img.shields.io/badge/Data-L2_Order_Book-2563EB?style=flat-square)
![Model: AR(1)](https://img.shields.io/badge/Model-AR(1)-7C3AED?style=flat-square)
![Focus: Imbalance Persistence](https://img.shields.io/badge/Focus-Imbalance_Persistence-0891B2?style=flat-square)

[Portfolio](../../README.md#projects) · [Overview](#overview) · [Research Questions](#research-questions) · [Method](#method) · [Conclusion](#conclusion)

</div>

---

## Overview

I investigate whether order book imbalance persists over short horizons and whether its current value helps predict its next value.

Using local L2 order book data, I aggregate bid and ask quantities across multiple price levels and model the resulting imbalance series with an **AR(1) baseline**. The goal is to understand how quickly a book's directional imbalance fades, persists, or reverses.

## Research Questions

| Focus | Question |
| :--- | :--- |
| **Persistence** | Does the current imbalance contain information about the next observation? |
| **Model adequacy** | Can AR(1) explain the observed autocorrelation, or does dependence remain in the residuals? |
| **Predictive value** | Does AR(1) outperform a training-mean imbalance baseline on unseen data? |
| **Stability** | Are the findings consistent across different time periods? |

## Data

I use my local L2 dataset rather than downloading a new L1 archive. Before analysis, I verify the instrument, timestamp precision, available depth, and whether the records contain snapshots or incremental updates.

If reconstruction is required, I first establish a valid initial book and check update continuity. The sampling interval and number of included levels are fixed after inspecting the data structure, before evaluating predictions.

## Method

**01 — Measure imbalance**  
I compare total bid and ask quantities across the first K levels on each side:

$$I_t=\frac{\sum_{i=1}^{K}Q^b_{t,i}-\sum_{i=1}^{K}Q^a_{t,i}}{\sum_{i=1}^{K}Q^b_{t,i}+\sum_{i=1}^{K}Q^a_{t,i}}$$

Here, K is the number of levels, i is the level index, and Qᵇ and Qᵃ are bid and ask quantities at time t. The imbalance I ranges from −1 to +1; positive values indicate more displayed bid quantity. Observations with a zero denominator are treated as missing.

**02 — Fit a baseline**  
I predict the next imbalance using an AR(1) model with an intercept:

$$I_{t+1}=c+\phi I_t+\varepsilon_{t+1}$$

The intercept c captures a fixed offset, φ measures linear dependence on the previous imbalance, and ε is the unexplained component. All quantities in this equation are dimensionless.

**03 — Evaluate on unseen data**  
I preserve chronological ordering, compare predictions with a training-mean baseline, and examine autocorrelation, residuals, and prediction errors. Realized observations remain fixed when comparing candidate models.

> **Interpretation:** Predicting future imbalance is different from predicting future returns. I also report predictions outside the valid imbalance range rather than silently clipping them.

---

## Conclusion

*To be completed after the empirical analysis.*

<!-- Summarize persistence, model adequacy, out-of-sample improvement, stability, and limitations. Include negative findings. -->
