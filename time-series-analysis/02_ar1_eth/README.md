<div align="center">

# Order Book Imbalance Persistence

**An AR(1) study of short-horizon ETHUSD L2 imbalance.**

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

I use my local L2 recordings for **`binance_spot` ETHUSD spot** (instrument id 2431025; tick size 0.01; lot size 0.0001, as stated in each file header), covering **2026-10-10 to 2026-10-19 UTC** (10 days). The raw files are not included in this repository.

| Property | Local data |
| :--- | :--- |
| Format | One JSON message per line: an initial full-book snapshot (155–203 levels), then incremental depth updates, best bid/offer messages, and trades |
| Timestamps | Nanoseconds; local receive time and exchange event time on every message |
| Continuity | Update ids are continuous in all 10 files (0 gaps); consecutive files overlap by about 8 minutes around midnight |
| Activity | Median gap between depth updates is about 140 ms; the longest silence without any message is 254 s |

Because the feed is incremental, `scripts/clean_l2.py` rebuilds the book from the snapshot. Any break in the update-id sequence stops the script. It checks for crossed books and compares the rebuilt best levels with the BBO stream (10,006 checks, 0 mismatches). Each file is clipped to its UTC day. The output is one top-10 snapshot per update, with mid price, spread, and mid-price change, plus a trade file. It is written to `data/cleaned/` together with a per-day `cleaning_audit.json`.

Analysis uses the local receive time, so each sample contains only information already received at that moment. Before evaluating predictions, I fixed K = 5 levels, a 1-second sampling grid, and a 300-second maximum book age. The age limit is valid for an incremental feed with continuous update ids, because no update means the book did not change.

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

Settings were frozen before the test period was opened ([freeze record](reports/2026-11-03_freeze_record.md)): K = 5, 1 s grid, local receive time, train 10-10 to 10-15, validation 10-16 to 10-17, test 10-18 to 10-19.

| Question | Finding |
| :--- | :--- |
| **Persistence** | Yes. Training φ = 0.949 (HAC 95% CI 0.948–0.951). Part of this is mechanical: in the test period, 72–74% of adjacent 1 s points have an unchanged book. |
| **Model adequacy** | Partial. Residual ACF is −0.16 at lag 1 and −0.03 at lag 2, so AR(1) leaves short-lag structure unexplained. |
| **Predictive value** | Strong against the training mean: test MSE is 90% lower (Diebold–Mariano, HAC 600 lags, p < 1e−49). Small against persistence: test MSE is 2.5% lower (p < 1e−28), but MAE is *worse* (0.0284 vs 0.0227). |
| **Stability** | AR(1) beat persistence on 3 of 4 out-of-sample days. It lost on the quietest validation day (10-17, 80% unchanged intervals). |

| Test set (172,799 pairs) | MSE | MAE |
| :--- | ---: | ---: |
| AR(1) | 0.00417 | 0.0284 |
| Persistence | 0.00427 | 0.0227 |
| Training mean | 0.04254 | 0.1578 |

**Takeaways**
- At 1 s, imbalance is highly predictable, but most of that comes from the book not changing.
- AR(1) adds only a modest squared-error gain over persistence, by shrinking toward the mean. This gain depends on the day.

**Limitations**
- Ten days of data cover few market regimes.
- The very small p-values reflect the large sample size. They do not indicate a large effect.
- These results do not imply return predictability or trading profit.

**Possible next steps**
- Model the "change vs no change" process separately.
- Test sensitivity to K and to the sampling interval.
- Test whether imbalance predicts mid-price changes. The cleaned data already include these fields.
