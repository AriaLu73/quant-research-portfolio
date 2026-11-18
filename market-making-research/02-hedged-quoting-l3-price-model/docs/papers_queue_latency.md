# Queue position, fill probability, adverse selection and latency: study report on six papers

Date: 2026-10-01. Scope: research3 literature pass. Source material: original full texts (PDF + pymupdf text) saved under
`docs\research3\papers\`:

| # | File stem | Source obtained | Pages | Full text? |
|---|-----------|-----------------|-------|------------|
| 1 | `albers2025_mm_dilemma` | arXiv:2502.18625v2 (23 Nov 2025) | 46 | yes |
| 2 | `moallemi_yuan2017_queue_position` | author page moallemi.com (`queue-value-2016.pdf`, "Current Revision: June 2017" = SSRN 2996221 version) | 33 | yes |
| 3 | `lehalle_mounjid2017_latency` | arXiv:1610.00261v4 (15 Mar 2018 revision of the 2016/2017 paper) | 27 | yes |
| 4 | `huang_lehalle_rosenbaum2015_queue_reactive` | arXiv:1312.0563v2 (3 Sep 2014; published JASA 110(509), 2015) | 29 | yes |
| 5 | `wu_etal2019_qr_hawkes` | arXiv:1901.08938v1 (25 Jan 2019) | 27 | yes |
| 6 | `gould_bonart2016_queue_imbalance` | arXiv:1512.03492v1 (11 Dec 2015) | 30 | yes |

All page numbers below refer to the PDF page of the saved file (which equals the printed page number for papers 1, 3, 4, 5, 6; for paper 2 the printed page number equals the PDF page). Every number labelled **[paper result]** is transcribed from the text or a table; every statement labelled **[inference]** is mine and was not made by the authors.

Conventions for the "implications" sections and the hypothesis cards — **our conditions** (as supplied by the coordinator, 2026-10-01):

- Venue: KuCoin USDT- and USDC-margined perpetuals. Maker fee **OUR_FEE** (USDT, OUR_FEE_TIER), **OUR_FEE** (USDC); taker **OUR_FEE**.
- Latency: REST order round trip **1.9 ms** (one-way ≈ 1 ms); market-data one-way ≈ **2.2 ms**. So the shortest event→our-order-at-engine path is ≈ 3.2 ms [inference: 2.2 + 1.0].
- Backtests currently **assume queue-front matching** (our resting order is filled by the first contra trade at its price).
- Historical data: **Tardis L2 increments + trades, no order IDs** (so exact queue position and individual cancellations are not observable historically; an L3 collector has been written but no L3 history is assumed here).
- Instruments: mid-cap coins with tick **≥ 1 bp** and 1–2-tick spreads ("large relative tick"); BTC with tick ≈ **0.01 bp** ("small relative tick").

Every card below uses these numbers; where a paper's number is converted into our units the conversion is marked [inference].

---

## 1. Albers, Cucuringu, Howison, Shestopaloff (2025) — "The Market Maker's Dilemma: Navigating the Fill Probability vs. Post-Fill Returns Trade-Off"

**Citation.** J. Albers, M. Cucuringu, S. Howison, A. Y. Shestopaloff, "The Market Maker's Dilemma: Navigating the Fill Probability vs. Post-Fill Returns Trade-Off", arXiv:2502.18625v2 [q-fin.TR], 23 Nov 2025 (dated November 25, 2025 on the title page). Oxford / Oxford-Man / QMUL / Memorial.

### 1.1 Exact experimental setup (Section 2, pp. 9–10)

- **Venue / contract.** Binance USDT-margined (linear) Bitcoin perpetual — "the most liquid crypto market globally" (p. 9). The authors note Binance is L2-only; exact fill-time queue position was reconstructed from the public trades feed (see below).
- **Order size.** Minimum-sized maker orders throughout, "due to cost constraints" (p. 16). No larger sizes were traded; larger-size fill probabilities are obtained by the identity P(fill | LA+q, Qopp) (p. 16), and the authors expect post-fill returns to *deteriorate* with size (footnote 13, p. 22).
- **Two live experiments** (p. 9–10):
  1. *Continuous Quoting Mode*: always one buy at top bid and one sell at top ask; if the touch moved away without a fill the order was cancelled and reposted at the new touch; after a fill a new order was posted immediately. **12–19 Feb 2024**, **232,897 orders, 127,051 filled, 105,846 cancelled unfilled** [paper result]. This is the dataset used in the paper.
  2. *Periodic Quoting Mode*: every 10 s post one buy at top bid and one sell at top ask regardless of inventory/active orders; cancel if the touch moves away. **21–31 Aug 2024**, **172,800 orders, 95,998 filled** [paper result]. "Results from both modes were essentially identical" (p. 10).
- **Cancellation rule (the key design choice).** An order is cancelled *if and only if* its price level stops being the touch on its side (p. 8, p. 3). This removes "signal bias" (cancellation policies of real makers), which the authors argue biases historical fill estimates low: Lokin & Yu report <2% fill probability with balanced queues vs. **~50%** in this experiment (p. 4) [paper result].
- **Latency treatment.** "we treat latency as being negligible" (p. 11) — explicitly a simplification; "a meticulous treatment of latency reinforces our conclusions" (p. 11); footnote 14 (p. 23): the imbalance taker strategy ignores latency, "potentially leading to an overstatement of results". The one place latency enters the argument is competition to be first to post after a price change (p. 6, footnote 15 p. 25), which they describe as "extremely competitive and typically involves latency optimization and/or special order types".
- **Fees assumed.** Best Binance tier: taker **1.5 bp**, maker **−0.5 bp** (rebate) (p. 10). Tick [amount removed] ≈ **0.03 bp** at the time, "negligible compared to fees"; spread "virtually always one tick wide"; several hundred thousand USD at each top level (p. 10). All PnL figures assume the best fee tier; "any strategy results analyzed below would only deteriorate with less favorable fees" (p. OUR_FEE).
- **Queue position measurement.** Binance publishes, for every taker order, all maker fills in execution-priority order with unique ids; a maker knows its own id, so summing the earlier fills in the burst and comparing to the top-of-book quantity gives the exact fill-time queue position QP_T(o) (p. 17). Intermediate-time LA_t/LB_t would need L3, "which is not available on the main cryptocurrency exchanges" — footnote 11 (p. 16) names the exceptions: **Bitfinex, Coinbase, Bitstamp, Kraken, and KuCoin** [paper result — relevant to us, see 1.7].

### 1.2 Definitions and formulas (Section 1.2, pp. 7–9)

- Imbalance, eq. (1), p. 7:  `imb_t := (B_t − A_t)/(B_t + A_t) ∈ (−1, 1)` where B_t, A_t are top bid/ask quantities. "Favorable" imbalance for a buy: imb_t > 0.5; for a sell: imb_t < −0.5 (p. 7).
- Liquidity ahead / behind and queue position (p. 7–8):
  `LA_t(o) := Σ_{j<j0} q_{t,1,j}`, `LB_t(o) := Σ_{j>j0} q_{t,1,j}`,
  `QP_t(o) := LA_t / (B_t − q_{t,1,j0}) = LA_t/(LA_t + LB_t)`, 0 = front, 1 = back.
- Microprice (p. 8): `p^µ_t := (B_t p^a_{t,1} + A_t p^b_{t,1})/(B_t + A_t)`.
- Instantaneous price drift, eq. (2), p. 9 (in bp, signed so positive = favourable):
  `dr(o) = sgn(o)·(p^µ_{t0+τ0}/p_{t0} − 1)·10^4` if mid unchanged at fill, else `sgn(o)·(p^mid_{t0+τ0}/p_{t0} − 1)·10^4`.
- Drift after τ seconds, eq. (3), p. 9: `dr_τ(o) := sgn(o)·(p^µ_{t0+τ}/p_{t0} − 1)·10^4`.
- "Unprofitability Principle" (p. 5, stated "in cartoon form"): `Ease of prediction × ease of exploitation < c`.

### 1.3 Fill probability results (Section 4, pp. 13–16; Figure 4 p. 14)

- Mechanism (p. 13): fill requires a sell taker of size > LA_T; small near-side queue ⇒ high fill probability; large opposite-side queue ⇒ price less likely to move away ⇒ longer residence ⇒ higher fill probability.
- **Figure 4** (p. 14): fill probability surface over (Q^near, Q^opp) in USD, 20×20 equal-width bins to the 99th percentile, Delaunay-smoothed. "as low as 30%" when near-side large and opposite small; "exceeds 90%" when near-side very small and opposite very large (p. 15) [paper result]. Fill probability is *not* a function of imbalance alone (p. 15).
- **OLS fit** (p. 15): `z = β0 + β1 Q^near + β2 Q^opp + β3 imb + ε`, queues normalised by 99th percentile; **R² = 0.946**; **β0 = 0.5649, β1 = 0.0159, β2 = 0.1013, β3 = −0.3166**; all significant except Q^opp (p = 0.065) [paper result]. (Note: the text's variable naming around β1/β2 is muddled — "Q^near and Q^opp denote the normalized opposite-side and near-side queue sizes" — but the stated dominant drivers are near-side size and imbalance, p. 15.)
- Intermediate-time update (p. 15): zero-intelligence estimate P(fill | LA_t, Q^opp_t) is an **upper bound** because LB_t build-up reduces near-side taker arrivals, etc.; a linear interpolation `QP_t·pr(LB_t,Q^opp) + (1−QP_t)·pr(LA_t,Q^opp)` is suggested but left for future work.
- Larger orders (p. 16): P(full fill of size q | LA, Q^opp) = P(min-size fill | LA + q, Q^opp).

### 1.4 Post-fill markouts by queue position and queue sizes (Section 5, pp. 16–19; Table 1 p. 19; Figures 5–10 pp. 18–19; Appendix A Figures 20–29 p. 40–41)

- Markout definition (p. 17): limit price vs **midprice one second after the fill**, in bp, **excluding the maker rebate**. Queue sizes at fill time binned small/medium/large by quantiles; QP_T binned [0,0.1), [0.1,0.4), [0.4,0.75), [0.75,1].
- Mechanism (p. 16): if QP_T = 1 (LB_T = 0) the very taker that fills you moves the mid against you; large LB_T shields you; adverse selection increases with Q^opp_T because a favourable post-fill move needs the opposite queue to be eaten.
- **Table 1 (p. 19), average 1-s markout in bp** [paper result]:

| Queue sizes at fill | QP 0–0.1 | QP 0.1–0.4 | QP 0.4–0.75 | QP 0.75–1 |
|---|---|---|---|---|
| Large near, small opp (favourable imb) | **−0.058** (std 1.0) | −0.586 | −0.743 | **−0.775** (std 1.6; min −27.3) |
| Large near, large opp | **−0.296** (std 0.9) | −0.882 | −0.967 | **−1.157** (std 1.1) |
| Small near, small opp | −0.562 (std 1.6) | −0.711 | −0.622 | −0.677 (std 2.2) |
| Small near, large opp (adverse imb) | **−0.539** (std 0.8) | −0.645 | −0.686 | **−0.763** (std 0.9) |

- Reading (pp. 17–19): every cell is negative before rebate. Front-of-queue in a large near-side queue with favourable imbalance is "predominantly at positive values" with a spike at small positive markouts, but the mean is still −0.058 bp (p. 17). Back-of-queue fills in a large queue are "almost all" adverse. When the near-side queue is small, queue position "does not matter much" (−0.539 vs −0.763) because LB is small either way (p. 18–19). Transitions across medium bins are smooth (p. 19).
- Figure 11 (p. 21): fill probability vs 5-second post-terminal return is strongly anti-correlated. Unconditional expected return of a maker order **≈ OUR_FEE gross, ≈ −0.3 bp net of the OUR_FEE rebate** (p. 20) [paper result].

### 1.5 Naive and imbalance-based two-sided makers (Section 6, pp. 20–24)

- Basic MM strategy (p. 21): min-size buy at top bid and sell at top ask; once inventory is ±1, quote only the side that flattens; repost at the new touch when the price moves away; return to two-sided when flat.
- **Result (p. 22, Figure 12–13)**: over ~3 days 7 hours the strategy "has lost almost 60%" (cumulative return in bp on the min-size notional), **annualised Sharpe −109.0**, average holding ≈ 11 s [paper result]. Realised-spread histogram: mode is a small positive spread, but frequent large and "occasional catastrophic" losses dominate (p. 22).
- **Table 2 (p. 24), net of fees, per trade** [paper result]:

| Strategy | Trades | Mean return (bp) | Std (bp) | Avg holding (s) |
|---|---|---|---|---|
| Imbalance taker (|imb|>0.5) | 18,927 | −1.9621 | 2.1653 | 15.04 |
| Naive maker | 12,623 | −0.4307 | 2.6486 | 22.56 |
| Imbalance maker w/o cancel (post if |imb|>0.5) | 8,851 | −0.4705 | 2.8529 | 32.17 |
| Imbalance maker w/ cancel (cancel at imb 0.0) | 7,333 | −0.4921 | 3.1143 | 38.83 |

- Interpretation by the authors (p. 23): the taker strategy has ≈ **OUR_FEE pre-fee per round trip** but the OUR_FEE taker fee per leg kills it; the maker strategies "are primarily undermined by fill probability: they almost always miss out on favorable price moves and are left with the smaller number of fills corresponding to reversals". The cancel rule only catches slowly drifting imbalance, not sudden moves from large takers.
- Statement on the literature (p. 20): the "common misconception ... that market makers can simply post orders at the top bid and ask prices to earn the spread plus rebates" (Avellaneda–Stoikov-type Poisson fills, no post-fill drift) is "a quick path to bankruptcy due to negative price drift". This replicates DeLise (2024) on US Treasuries.
- Threading the needle (pp. 23–25): the only profitable cell is front-of-queue in a large near-side queue with favourable imbalance. To get there you must post when the queue is still small (i.e. typically under *adverse* imbalance) and have the imbalance flip — which needs a signal.

### 1.6 Reversal model (Section 7, pp. 25–35)

- Universe: orders with predicted fill probability > 80% from the Figure 4 surface; 182,381 orders; first half train, second half test; opposite queue on average 40% larger than near side (p. 26) [paper result].
- Label φ(o) = 1 iff the order fills and `ret_{T,T'}(o) := sgn(o)(p(o)/p_{T'} − 1)·10^4 > 0`, p_{T'} = near-side top price at the first post-fill price change (p. 26).
- Logistic model `P(φ=1) = 1/(1 + exp(α0 + Σ α_i x_i))` (p. 26) with **173 features** (p. 27): volatility (stdev of 100/500 ten-second returns), amplitude/VWAP return over 100 ms, 1 s, 5 s, 30 s, 300 s windows × 3 non-overlapping lags, trade-size/count/volume features, return autocovariance, trade intensity, top-of-book liquidity, [amount removed]-depth cost, top-of-book survival time, age since last touch change; all sign-normalised to near/opposite side (p. 28). Only ~15% of orders in the set are reversals (p. 28).
- **Table 3 (p. 29), undirectional strategy, logistic regression** [paper result]: threshold 0 → 21,689 orders/day, fill prob 0.882, 5-s return −0.74 bp; threshold 0.30 → 233 orders/day, 0.855, **−0.32 bp** (t = 3.06, p = 0.0011); threshold 0.36 → 69/day, 0.791, **+0.27 bp**; threshold 0.50 → 9/day, +3.02 bp. Random forest reaches positive 5-s return only at threshold 0.46 (96 orders/day, +0.05 bp). Economic significance "at a reversal probability of approximately 24–26%" where returns are "about 0.1–0.2 bp better than randomly placed orders" (p. 29).
- **Table 4 (p. 31), balanced-inventory strategy (round trips, OUR_FEE rebate added per round trip)** [paper result]: threshold 0 = naive: 15,380 fills/day, **−0.44 bp/round trip**, Sharpe −109; LR threshold 0.24: 654 fills/day, **+0.71 bp**, std 13.69, holding 268 s, **Sharpe +11.97** (p = 0.016); threshold 0.26: 426 fills/day, +1.21 bp, holding 409 s, Sharpe 26.1. Random forest reaches +0.59 bp only at threshold 0.34 (692 fills/day). Rows with holding > 600 s are suppressed.
- Feature economics (pp. 31–34): reversals are more likely with negative recent return autocovariance (oscillation, not trend) over the last 15 s, a sharp drop in the last 100 ms, high trade intensity / short top-of-book survival, low pre-existing liquidity at the touch but ample liquidity just below, many small sell trades recently with low total sell volume, and emerging buy trades in the last 5 s. Permutation importance (RF): `ret_autocorr_sum_30s_w0` 1.00, `velocity_tr_30s_w0` 0.93, `ob_bid_liq` 0.67, `totb_mean` 0.57, `sell_count_30s_w0` 0.27, `amplitude_100ms_w0` 0.12 (p. 34).
- Authors' own caveats (p. 31, p. 36): the Sharpe "is unlikely to persist with larger-than-minimum-sized orders", assumes the best rebate, profits "likely not scalable", model is a proof of concept.

### 1.7 Limitations (as stated by the authors, plus mine)

- Min-size orders only; the authors expect worse results with size (footnote 13, p. 22; p. 31).
- Latency ignored (p. 11, footnote 14 p. 23).
- One venue, one week (Feb 2024) for the headline dataset; the August 2024 periodic experiment is said to match but is not tabulated.
- Markout horizon 1 s (Table 1) / 5 s (Tables 3–4); no longer horizons reported.
- **[inference]** The reversal model's positive-return rows have tens to a few hundred orders per day and 3.5 test days; standard deviations of 13–22 bp per round trip vs. means ~1 bp — the point estimates are fragile even if the t-tests pass.
- **[inference]** The "adverse imbalance ⇒ high fill" mechanism is partly an artefact of the no-cancel design: a real maker can cancel, so the empirical fill-probability surface is an upper bound on what a maker who cancels on adverse signals would experience, and the post-fill return is a lower bound on what a maker with a cancel signal achieves. The paper's own Table 2 shows a crude cancel rule does not help; a better one might.

### 1.8 Implications for a KuCoin maker (≈ 3.2 ms event-to-order path, OUR_FEE USDT / OUR_FEE USDC rebate)

- **Rebate arithmetic [inference].** Substituting our OUR_FEE rebate for their −0.5 bp: unconditional maker markout OUR_FEE gross → **−0.1 bp net** (vs. their −0.3). Naive two-sided round trip −0.44 bp at OUR_FEE rebates → **≈ −0.04 bp** at OUR_FEE rebates; imbalance maker w/ cancel −0.49 → ≈ −0.09 bp. So on Binance-BTC-like adverse selection, the extra 0.2 bp/leg rebate roughly *neutralises* the naive-maker loss but does not make it profitable, and every one of their caveats (size, latency, less favourable fee tier) pushes it back below zero. This is the single most important calibration point for the U15 "volume first" plan: the cost of buying volume with naive two-sided quotes is of order 0–0.5 bp per round trip on a BTC-like book, *if* KuCoin adverse selection matches Binance's — which must be measured, not assumed. On the USDC line (OUR_FEE) the same arithmetic gives −0.8 + 1.2 = **+0.4 bp per fill** and −1.44 + 2.4 = **≈ +0.96 bp per naive round trip** [inference], but USDC books are far thinner than USDT books, which puts them in Albers' "small near-side queue" rows at best and makes the Binance adverse-selection number the least transferable there. Taker exits at OUR_FEE are never covered: Albers' imbalance taker earns ≈ +1 bp gross per round trip against OUR_FEE of fees on our schedule.
- **Front-of-queue positions become net positive at OUR_FEE [inference from Table 1].** All four QP 0–0.1 cells (−0.058, −0.296, −0.562, −0.539) exceed OUR_FEE, so the 1-s markout net of our rebate is positive for front-of-queue fills in every queue-size configuration; back-of-queue fills in large queues (−0.775, −1.157) remain negative or marginal. The strategic content is therefore "own the front of the queue or don't be in it", and the paper says the only way to get there without a race is to post early in a small queue under adverse imbalance — i.e. a reversal signal.
- **Large-tick mid-caps vs BTC [inference].** Albers' Binance BTC book has a 0.03 bp tick but behaves like a large-tick book (1-tick spread, hundreds of k USD at the touch); footnote 7 (p. 5) attributes this to rebates as much as tick size. On KuCoin mid-caps the spread is pinned at 1 tick by the tick itself, so the Table 1 mechanics (fill ⇔ the taker eats through you; back-of-queue fill ⇒ mid moves against you) apply directly and the markout magnitudes scale with the tick in bp rather than with 0.03 bp. On KuCoin BTC the spread may be several ticks and the top queues thin; then "front vs back" matters less (their small-near-side rows) and the relevant question becomes the spread-capture vs drift trade-off at a multi-tick spread, which this paper does not cover.
- **Our backtest assumption is the one the paper singles out as untenable [paper result → inference].** Albers (p. 6) criticise models that assume "the maker order is always at the front of the queue" and show in Table 1 that, in large queues, front-decile fills beat back-quartile fills by 0.7–0.9 bp at 1 s. Our backtests assume queue-front matching, so on any symbol whose touch queue is large relative to typical trade size (mid-caps with tick ≥ 1 bp) they are biased upward by an amount of the same order as our whole rebate. This is the first thing to quantify (card below, test T1).
- **Data constraint [inference].** KuCoin does publish L3 (footnote 11, p. 16), which would give LA_t, LB_t, QP_t exactly, but our standard dataset is Tardis L2 increments + trades without order IDs. With that data queue position can only be *bracketed*: an optimistic bound (we are at the front; any contra trade at our price fills us — the current assumption) and a pessimistic bound (we join at the back; liquidity ahead = displayed size at post time, reduced only by trades at our price, never by cancellations). Exact queue position requires either our own L3 recording or the live experiment, where our own order events give it directly. The cheapest decisive experiment is exactly theirs: min-size, cancel-iff-not-at-touch, one week, one contract, then tabulate Table 1 and Table 2 for KuCoin.
- **Latency [inference].** They treat latency as zero and say it only strengthens their conclusions. Our event-to-order path is ≈ 3.2 ms (2.2 ms market data + ≈ 1 ms order entry). Queue position can be bought by speed only at price changes (footnote 15), and at 3.2 ms we should assume we are *not* first at a newly formed level on liquid symbols — which again argues against the queue-front backtest assumption. The latency matters most on the cancel side (see paper 3).

### 1.9 Hypothesis card — Albers et al. (2025)

**Strategy hypothesis (what is the edge?)**
A touch maker's net edge per fill = rebate − adverse selection, and adverse selection is set by queue position at fill. H1a: fills taken from the front of a large same-side queue have 1-s markout above OUR_FEE (net positive after the USDT rebate), fills from the back do not. H1b: a naive always-two-sided touch quoter nets approximately (gross markout + rebate) ≈ 0 on USDT and is positive only on the USDC rebate. H1c: posting into an adverse imbalance is profitable only on the subset of "reversals" identified by a separate signal. [H1a–c are my restatement of the paper's findings in our fee units — inference.]

**Economic mechanism (why should this edge exist?)**
Mechanical: a back-of-queue order is filled only by a taker large enough to consume the whole queue, which moves the mid through the order; a front-of-queue order is filled by any taker and keeps liquidity behind it as a shield (p. 16). Persistence: short-horizon returns are positively autocorrelated, so the fill-producing move continues (p. 12). Exchange rebates exist precisely to pay makers for this drift; the edge survives only where the rebate exceeds the drift for the queue position actually achieved.

**Required data (L1 / L2 / L3 / trades / order events)**
Paper: own live order events (post, fill, cancel) + Binance L2 + public trades with per-maker-fill ordering. For us: trades + L2 increments (touch sizes at post and at fill) suffice to bracket the effect; own order events (live) or L3 are needed for exact queue position. L1 alone is not enough (need size at the touch through time).

**Holding horizon (1ms / 10ms / 100ms / …)**
Markout measured at 1 s (Table 1) and 5 s (Fig. 11, Tables 3–4). Inventory holding of the naive maker ≈ 11–23 s; of the reversal strategy ≈ 270–600 s. Not a millisecond strategy; the millisecond part is only the race to be first at a new level.

**Expected signal (what observable predicts the edge?)**
Queue position at fill QP_T, same-side and opposite-side touch sizes at fill (terciles), i.e. liquidity behind LB_T. For reversals: negative return autocovariance over the last 3 × 5 s, 100 ms signed return, inter-trade time over 30 s, mean top-of-book survival time, touch liquidity vs depth just behind it, count vs volume of recent same-direction trades (pp. 31–34).

**Execution dependency (queue / latency / fill probability)**
Queue: decisive (0.7–0.9 bp front-to-back in large queues). Fill probability: 30–90%, anti-correlated with post-fill return — cannot be optimised in isolation. Latency: ignored in the paper; for us it determines whether we are ever at the front of a newly formed level (3.2 ms event-to-order path).

**Failure modes (why might it disappear?)**
Order size above minimum (authors expect worse, fn. 13); thinner KuCoin queues put us in the "small near-side" rows where queue position does not help (−0.54 to −0.76 bp regardless); KuCoin toxicity higher than Binance (lagging venue ⇒ more stale-quote arbitrage); rebate tier lost; competitors faster to new levels; the reversal model's profit rests on tens to hundreds of orders/day over 3.5 test days.

**Evidence (paper + empirical result, with numbers)**
Binance BTCUSDT perp, 12–19 Feb 2024, 232,897 min-size orders (127,051 filled). 1-s markout before rebate: large-near/small-opp front decile −0.058 bp vs back quartile −0.775 bp; large/large −0.296 vs −1.157; small-near/large-opp −0.539 vs −0.763 (Table 1). Unconditional OUR_FEE gross, −0.3 bp net of OUR_FEE rebate. Naive maker −0.43/−0.44 bp per round trip net, Sharpe −109; imbalance maker −0.47, with cancel −0.49; imbalance taker −1.96 (Table 2). Fill-probability OLS R² 0.946. Reversal logistic at threshold 0.24: +0.71 bp/round trip, 654 fills/day, Sharpe 12 (Table 4).

**Test (the exact experiment we should run on KuCoin Futures data)**
- *T1 — historical bracket (Tardis L2 increments + trades).* Contracts: one mid-cap USDT perpetual with tick ≥ 1 bp and 1–2-tick spread, its USDC twin if traded, and XBTUSDTM. Training days only (September days outside the 9-day final exam). Synthetic min-size orders in the paper's Periodic mode: every 10 s one buy at best bid and one sell at best ask, arrival delayed 3.2 ms, cancelled iff the level stops being the touch. Fill rule under two queue models: (F) front — first contra trade at our price fills us (current backtest assumption); (B) back — liquidity ahead = displayed size at arrival, reduced only by trade volume at that price (no credit for cancellations). Statistic: mean signed markout (fill price vs mid at +1 s and +5 s, bp) per model, overall and by tercile of same-side × opposite-side touch size at fill; day-block bootstrap 95% CI.
  - Pass/fail for "queue-front backtests are biased": biased if markout(F) − markout(B) ≥ 0.3 bp with CI excluding 0 on the symbol (Albers' analogue is 0.7–0.9 bp); not material if < 0.1 bp.
  - Pass/fail for H1b (naive touch quoting is a free source of volume): pass if the 5-s markout under model B is > OUR_FEE (USDT) / > OUR_FEE (USDC) with the CI lower bound above the threshold; fail if the point estimate is below the threshold. Report F as the optimistic bound only.
- *T2 — live replication (own order events).* Same contracts, minimum size, one week, cancel-iff-not-at-touch. Exact queue position from our own acknowledgements and the L2 size at acknowledgement. Statistic: Table 1 grid (QP_T quartile × queue-size tercile) and Table 2 round-trip return net of actual fees. Pass for H1a: front-quartile cell > OUR_FEE and back-quartile cell lower by ≥ 0.3 bp, both with CI; fail if the cells are statistically indistinguishable.

---

## 2. Moallemi & Yuan (2017) — "A Model for Queue Position Valuation in a Limit Order Book"

**Citation.** C. C. Moallemi and K. Yuan, "A Model for Queue Position Valuation in a Limit Order Book", Columbia Business School working paper, initial version Dec 2016, current revision June 2017; SSRN 2996221. Full text obtained from the author's page (moallemi.com).

### 2.1 Market / data / tick / fee context

- US equities, **NASDAQ ITCH** market-by-order feed, **August 2013** (22 trading days for BAC calibration, 21 days in Table 2, 30 days for backtest averages) (pp. 16, 22–23).
- Large-tick stocks only: "the bid-ask spread rarely exceeds the minimum tick size" (Eisler et al. definition, p. 6). BAC: ADV 88M shares, spread ≈ 1 tick ≈ **7 bp** of price (p. 16) [paper result]. Nine names in Table 2 (p. 22): BAC, CSCO, GE, F, INTC, PFE, PBR, EEM, EFA; average spreads 0.996–1.021 ticks.
- Fee: NASDAQ liquidity rebate **0.3 ticks**; liquidity premium `δ0 = half-spread + rebate = OUR_FEE ticks` (p. 18) [paper result].
- Only the NASDAQ book (no cross-venue aggregation); pro-rata markets excluded (footnote 2, p. 2).

### 2.2 Model (Section 2, pp. 6–12)

- Infinitesimal sell limit order posted at the best ask P^A at t = 0, held until filled or until the price changes (then cancelled by assumption). Risk-neutral, zero rate. Latent efficient price `P_t = E[P | F_t]` (Doob martingale).
- **Eq. (1), p. 8 (accounting identity):** `V_t = α_t (δ_t − AS_t)`, with `α_t = P(FILL | F_t)`, `δ_t = P^A − P_t` (liquidity premium), `AS_t = E[(P_{τ*} − P_t) | F_t, FILL]` (adverse selection). In words (p. 9): "order value = fill probability × (liquidity spread premium − adverse selection cost)".
- **Price dynamics, eq. (2), p. 9:** `P_t = P0 + λ Σ_{i: τ^u_i ≤ t} u_i + Σ_{k: τ^J_k ≤ t} J_k` — linear permanent impact λ per signed trade size u_i (Poisson rate µ, i.i.d. density f, E[u]=0), plus price jumps J_k (Poisson rate γ, E[J]=0). Upward jump fills all asks; downward jump cancels the order (pp. 9–12). Eq. (3): `δ_t = δ0 − λ Σ u_i − Σ J_k`. Volatility `σ_P = sqrt(µ λ² σ²_u + γ σ²_J)` (p. 10).
- **Queue dynamics (Section 2.3, pp. 11–12):** trade u ≥ q fills; 0 ≤ u < q moves you to q − u; cancellations shrink the whole queue proportionally, `q → ℓ q`, ℓ i.i.d. on [0,1] with density g, Poisson rate η⁺ — "Proportional and Uniform Cancellations" and "Uninformed Cancellations" assumptions (p. 12).
- **Lemma 1, eq. (4), p. 13** (uniformised, ζ = µ + γ + η⁺):
  `V(q,δ) = (µ/ζ) E_u[ 1{0≤u<q} V(q−u, δ−λu) + 1{u≥q}(δ−λu) + 1{u<0} V(q, δ−λu) ] + (γ/ζ) E_J[ 1{J>0}(δ−J) ] + (η⁺/ζ) E_ℓ[V(ℓq, δ)]`.

### 2.3 Theorem 1 (p. 14) — verbatim structure

`V(q,δ) = α(q) δ − β(q)` (eq. 5), with α, β the unique solutions of the Volterra equations

- **eq. (6):** `α(q) = µ/(µp⁺_u + γ + η⁺) · [ p⁺_u + ∫_0^q (α(q−x) − 1) f(x) dx ] + γ p⁺_J /(µp⁺_u + γ + η⁺) + η⁺/(µp⁺_u + γ + η⁺) ∫_0^1 α(ℓq) g(ℓ) dℓ`
- **eq. (7):** `β(q) = µ/(µp⁺_u + γ + η⁺) · [ ∫_0^q β(q−x) f(x) dx + λ ∫_0^q (α(q−x) − 1) x f(x) dx − λ ū⁺ (α(q) − 1) ] + γ J̄⁺/(µp⁺_u + γ + η⁺) + η⁺/(µp⁺_u + γ + η⁺) ∫_0^1 β(ℓq) g(ℓ) dℓ`
- **eq. (8), boundary:** `α(0) = (µp⁺_u + γp⁺_J)/(µp⁺_u + γ)`, `β(0) = µ γ(1−p⁺_J)/(µp⁺_u + γ)² · λ ū⁺ + γ/(µp⁺_u + γ) · J̄⁺`,
  where `p⁺_u = P(u>0)`, `ū⁺ = E[u 1{u>0}]`, `p⁺_J = P(J>0)`, `J̄⁺ = E[J 1{J>0}]`.
- Inputs needed (p. 14): γ/µ, η⁺/µ, f(·), λ, p⁺_J, J̄⁺/p⁺_J. Only *ratios* of arrival rates matter (no time value).
- **Theorem 2 (p. 15):** α_t = α(q), AS_t = β(q)/α(q); α non-increasing in q; β/α > 0; with η = 0, α(q) → p⁺_J and β(q) → J̄⁺ as q → ∞.
- **Theorem 3 (pp. 15–16), closed form for two-sided exponential trade sizes and no cancellations:** `α(q) = p⁺_J + µ(1−p⁺_J)/(µ+2γ) · e^{−bq}` (eq. 9), β(q) given by eq. (10), `b = (γ+ζ)θ/(µ/2+γ)`.

### 2.4 How α(q), β(q) are estimated (Section 4, pp. 16–18)

They are **not estimated directly**; they are computed by solving (6)–(7) numerically after calibrating the primitives daily:
- *Price jumps*: any change of best bid/ask, including executions that deplete the queue. Jump size = price change **Δt = 1 minute after** the move (the latent price is unobservable; post-move price taken as unbiased) (p. 17, footnote 8). Rate γ by counting, averaged over bid and ask sides.
- *Trades*: aggressive orders reconstructed by aggregating same-side fills within **2 ms**; if the price changes in the window it is a jump, not a trade. Trade-size distribution ≈ log-normal, MLE for mean/std; µ by counting (p. 17).
- *Cancellations*: each cancellation viewed as proportional shrinkage ℓ of the whole queue, ℓ fitted with a **Beta** distribution; η by counting (p. 18).
- *Impact λ*: Kyle–Obizhaeva invariance, **eq. (11), p. 18**: `λ = C (Pσ)^{4/3} V^{−2/3}`, C = 0.0156 (footnote 9), P price, σ daily return vol, V daily share volume.
- *Liquidity premium*: δ0 = 0.8 ticks (half-spread 0.5 + rebate OUR_FEE).
- **Table 1 (p. 19), BAC Aug 2013** [paper result]: µ 0.81–2.25 trades/min; average trade size 1,582–3,669 shares; η 85.8–178.2 cancels/min; γ 0.44–1.39 jumps/min; average jump size 0.75–1.25 ticks; λ 3.53–5.99 (bp per 1% of daily volume); average queue 33,647–60,888 shares. Day-to-day variation comes almost entirely from γ/µ and η/µ (p. 18).

### 2.5 Empirical value of queue front vs average (Section 4.3 and 5, pp. 18–24)

- Figure 3 (p. 21), BAC: fill probability decreasing and flattening in q; adverse selection increasing in q; order value decreasing. **Front-of-queue vs average-queue-length value difference: 0.26 ticks on 8/9/2013 and 0.21 ticks on 8/20/2013**, "comparable to the bid-ask spread" (p. 20) [paper result]. The worse day had γ/µ = 0.69 vs 0.43 (p. 20).
- **Table 3 (p. 23), 30-day averages, model vs artificial-order backtest** [paper result]:

| Symbol | Order value (end of queue) model / sim (ticks) | Fill prob model / sim | Adverse selection model / sim (ticks) | Touch value (front) model / sim (ticks) |
|---|---|---|---|---|
| BAC | 0.14 / 0.14 | 0.62 / 0.60 | 0.57 / 0.57 | **0.36 / 0.31** |
| CSCO | 0.08 / 0.07 | 0.63 / 0.59 | 0.68 / 0.68 | 0.24 / 0.21 |
| GE | 0.08 / 0.09 | 0.62 / 0.60 | 0.67 / 0.65 | 0.19 / 0.23 |
| F | 0.13 / 0.15 | 0.65 / 0.64 | 0.60 / 0.53 | 0.24 / 0.23 |
| INTC | 0.11 / 0.09 | 0.64 / 0.61 | 0.63 / 0.56 | 0.28 / 0.23 |
| PFE | 0.12 / 0.11 | 0.63 / 0.58 | 0.62 / 0.61 | 0.16 / 0.21 |
| PBR | −0.03 / −0.04 | 0.57 / 0.53 | 0.85 / 0.89 | 0.03 / 0.03 |
| EEM | 0.07 / 0.08 | 0.63 / 0.63 | 0.69 / 0.64 | 0.21 / 0.15 |
| EFA | 0.03 / 0.04 | 0.57 / 0.53 | 0.74 / 0.73 | 0.06 / 0.09 |

- Reading: even at the back of the queue, a large-tick order is worth +0.03…+0.15 ticks *after* the 0.3-tick rebate is included in δ0 (PBR negative); adverse selection alone is 0.53–0.89 ticks — i.e. **larger than the half-spread (0.5)** in every name; only the rebate keeps back-of-queue orders positive. Front-of-queue is worth 0.03–0.36 ticks more.
- Backtest method (Section 5.1, pp. 22–23): 1,000 random insertion times per day between 10:00 and 15:30; "regular" orders appended to the back, "touch" orders inserted at the front; cancelled when a better price appears on the same side; filled when a later-arriving order at the same price is filled; fundamental value = **mid one minute after execution**; averaged over 30 days because "these estimates are very noisy" (p. 24).

### 2.6 Limitations

- Stated: no time value; single infinitesimal order (no impact); prices do not move within the model except by exogenous jumps; cancellations uniform and uninformed (they acknowledge Cont et al. 2014 find cancellations correlated with price moves, p. 12); latent price proxied by 1-minute-ahead price.
- **[inference]** Uniform proportional cancellation overstates how fast a back-of-queue order advances (real cancellations are concentrated at the back — see Huang et al. p. 16 citing Gareche et al.). The model is silent on who owns the queue and therefore on the race to the front; it values a position you already have.
- **[inference]** The 1-minute fundamental horizon is long relative to HFT markouts; adverse selection in ticks at 1 minute contains both the informational component and mean-reverting noise.

### 2.7 Implications for a KuCoin maker

- **Units [inference].** BAC's 0.21–0.26 tick front-vs-average value at a 7 bp tick is ≈ 1.5–OUR_FEE; the touch-vs-back gap of 0.22 ticks (0.36 − 0.14) is ≈ 1.5 bp. On a KuCoin mid-cap with a tick of, say, 2–5 bp, the same fractions would be ≈ 0.4–1.3 bp, i.e. of the same order as our entire rebate — queue position is not a second-order effect there. On KuCoin BTC (tick ≈ 0.01 bp) the queue value in bp is negligible *by this model*, and what matters is β(q)/α(q) in bp, which this model cannot supply without a tick-scale to anchor to; the Albers grid is the better tool for BTC.
- **Calibration recipe we can lift [inference].** Everything in Section 4 is computable from Tardis L2 increments + trades, because the model deliberately needs only aggregate primitives: γ/µ (touch changes per aggressive order), the log-normal trade-size fit with 2 ms same-side aggregation, p⁺_J and E[J | J>0] with a chosen Δt, and λ from Kyle–Obizhaeva or a direct regression. The one piece that degrades without order IDs is the cancellation model: η/µ and the Beta fit for the proportional shrinkage ℓ must be inferred from touch-size decrements not explained by trades, and the *position* of cancellations in the queue is unobservable (the paper assumes uniform anyway). Solving (6)–(7) then gives α(q), β(q) per day per symbol — a normalised, parameter-light fill-probability and adverse-selection model that fits the "all parameters normalised, cite literature" rule. The daily variation in γ/µ (0.43 vs 0.69 on two BAC days) is the model's warning that a static fill model is wrong.
- **Rebate as the marginal profit [paper result reinterpreted].** With δ0 = 0.5 + 0.3, back-of-queue value is +0.03…+0.15 ticks; without the 0.3 rebate every back-of-queue value in Table 3 would be negative. Our OUR_FEE rebate on a mid-cap with a tick of 2–5 bp is 0.14–0.35 ticks — comparable to NASDAQ's 0.3 ticks, so the same "rebate carries the back of the queue" regime is plausible; on BTC it is ~70 ticks of rebate and the model's spread-vs-adverse-selection framing collapses into "is the drift in bp smaller than OUR_FEE", which is Albers' question.
- **Sizing [inference].** The model is for an infinitesimal order; for our sizes the correct α is Albers' P(fill | LA + q, Q^opp) shift, and β should rise with size because we are then filled only by larger takers.

### 2.8 Hypothesis card — Moallemi & Yuan (2017)

**Strategy hypothesis (what is the edge?)**
On a large-tick instrument a resting order's expected value is V(q, δ) = α(q)·δ − β(q); it is positive at the back of the queue only because of the rebate, and it rises by a sizeable fraction of a tick toward the front. H2: on KuCoin mid-caps (tick ≥ 1 bp) queue priority is worth ≥ 0.1 tick, so (i) keeping an aged order beats cancel-and-repost unless the signal is worth more than that, and (ii) a backtest that grants queue-front priority overstates order value by that amount. [inference: translation to our instruments]

**Economic mechanism (why should this edge exist?)**
Queue position filters the contra-side population: a back-of-queue order trades in the next instant only against a large (more likely informed) order, a front order against any order (p. 3, after Glosten 1994); plus a dynamic option value from moving up the queue as trades and cancellations clear the orders ahead (p. 4). With a binding tick, traders cannot buy priority by price, so they pay for it with time.

**Required data (L1 / L2 / L3 / trades / order events)**
Paper: NASDAQ ITCH (order-level, L3). Minimum for the parametric model: trades (for µ, trade-size law, 2 ms aggregation) + L1/L2 touch changes (for γ, jump sizes) + touch-size decrements not explained by trades (for η and the shrink fraction ℓ). The front-vs-back artificial-order backtest needs L3 to be exact; with L2 it can be run only as the front/back bracket of card 1.

**Holding horizon (1ms / 10ms / 100ms / …)**
Order lifetime = until fill or until the touch price changes (seconds to minutes on a large-tick book; BAC had 0.4–1.4 price jumps per minute). Valuation horizon for adverse selection: mid 60 s after the fill.

**Expected signal (what observable predicts the edge?)**
Queue ahead q in units of average trade size; the day's ratio γ/µ (price jumps per trade — 0.43 vs 0.69 on two BAC days moved front-vs-average value from 0.26 to 0.21 ticks); η/µ; liquidity premium δ (half-spread + rebate, in ticks).

**Execution dependency (queue / latency / fill probability)**
Entirely a queue-position result. Latency matters only through the queue position it buys at a newly formed level (p. 3). Fill probability α(q) falls from α(0) toward p⁺_J ≈ probability that the next jump is through the order.

**Failure modes (why might it disappear?)**
Small relative tick (BTC): priority is bought by price improvement and the model is out of scope; spreads of 2 ticks allow in-spread orders that the model forbids; informed cancellations (the model assumes uninformed, uniform); our order is not infinitesimal; rebate change moves δ0 one-for-one.

**Evidence (paper + empirical result, with numbers)**
BAC, Aug 2013: value at front minus value at average queue length 0.26 ticks (8/9) and 0.21 ticks (8/20), tick ≈ 7 bp. Nine names, 30-day averages (Table 3): back-of-queue value −0.03…+0.14 ticks (model) with δ0 = 0.8 ticks including a 0.3-tick rebate; front ("touch") value 0.03…0.36 ticks; fill probability 0.57–0.65; adverse selection 0.57–0.85 ticks; model vs artificial-order simulation agree within ≈ 0.05 ticks on order value.

**Test (the exact experiment we should run on KuCoin Futures data)**
- Contract: a mid-cap USDT perpetual with tick ≥ 1 bp whose spread is 1 tick ≥ 80% of the time (report the share); repeat on one 2-tick-spread symbol as an out-of-scope control. Data: Tardis L2 increments + trades, training days only.
- Step 1 (calibration, per day): µ and log-normal trade sizes from trades aggregated within 2 ms per side; γ, p⁺_J, E[J | J>0] from touch-price changes with the post-jump price taken Δt = 60 s later (and 5 s as a sensitivity); η and a Beta fit of ℓ from non-trade touch decrements; δ0 = 0.5 tick + rebate in ticks (OUR_FEE or OUR_FEE divided by the tick in bp); λ by regression of 60-s mid change on signed aggregated trade size. Solve eqs. (6)–(7) on a q-grid.
- Step 2 (model-free check): 1,000 artificial orders per day at uniform random times, each evaluated as a "touch" order (front) and as a "regular" order (back, pessimistic rule of card 1); value = signed (fill price − mid 60 s after fill) + rebate if filled, 0 if cancelled.
- Statistics: (a) V_front − V_back in ticks and bp; (b) V_back; (c) |model − simulation| for order value, fill probability and adverse selection.
- Pass/fail: H2 passes if V_front − V_back ≥ 0.1 tick (the paper's own "comparable to the spread" bar, p. 24) with a day-bootstrap 95% CI excluding 0, and the model is usable if (c) ≤ 0.05 tick on order value. H2 fails (queue position not worth modelling on that symbol) if the gap is < 0.05 tick. Separately, "joining the back of the queue is +EV at our rebate" passes if V_back > 0 with CI.

---

## 3. Lehalle & Mounjid (2016/2018) — "Limit Order Strategic Placement with Adverse Selection Risk and the Role of Latency"

**Citation.** C.-A. Lehalle (CFM and Imperial College) and O. Mounjid (UPMC), "Limit Order Strategic Placement with Adverse Selection Risk and the Role of Latency", arXiv:1610.00261v4 [q-fin.TR], 15 Mar 2018 (first posted Oct 2016). Published version: Market Microstructure and Liquidity 3(1), 2017 (not checked; the arXiv v4 is what was read).

### 3.1 Market / data context (Section 2, pp. 3–9)

- **NASDAQ-OMX Stockholm, AstraZeneca, 2 Jan – 30 Sep 2013**, CFM direct-feed order book synchronised with **labelled** trades (buyer and seller member ids); 376,672 trades (Figure 1 caption, p. 5). Primary market share 72.24% of traded value (Table 1, p. 3). Large-tick stock ("spread equals to one tick", p. 9).
- Participant classes (Table 2, p. 6; Appendix B pp. 26): Global Investment Banks (Barclays, Citi, Commerzbank, DB, HSBC, Merrill, Nomura), High Frequency Participants (All Options, Hardcastle, IMC, KCG, MMX, Nyenburgh, Optiver, Spire, SSW, WEBB, Wolverine; IMC/KCG/Optiver/Spire tagged market makers), Institutional Brokers (ABG Sundal Collier, Citadel Securities Europe, Erik Penser, Jefferies, Neonet, Remium, Timber Hill).
- No fee model in the paper; results are in ticks in a stylised model. **No empirical latency-cost magnitude in real-market units is reported** — the latency cost is a numerical output of the control model (Section 4.2). Be explicit: any bp figure for latency cost must come from our own calibration, not this paper.

### 3.2 Imbalance-implied fair price (Section 2.2, pp. 4–5, and Section 3.2, p. 13)

- Imbalance, eq. (1), p. 4: `Imb_t := (Q^Bid_t − Q^Ask_t)/(Q^Bid_t + Q^Ask_t)`.
- Empirical: `E((P_{t+δt} − P_t) × sign(Imb_t) | Imb_t) > 0` (p. 4); Figure 1a (p. 5): mid move over the next 50 trades is "highly linearly positively correlated" with imbalance, range roughly −8…+8 (units of the plot, ticks-scale) over Imb ∈ (−0.8, 0.8); Figure 1b: participants are most active at extreme imbalance (share of events 0.35–0.75).
- Microprice at infinity: `P_{+∞}(t) = lim_{δt→∞} E(P_{t+δt} | P_t, Imb_t)` (p. 5).
- **Terminal constraint / fair price used in the control problem (p. 13, unnumbered):**
  `P_{∞,k} = F(Q^Opp_k, Q^Same_k, P_k) = P_k + (α/2) · (Q^Same_k − Q^Opp_k)/(Q^Opp_k + Q^Same_k)` for all k,
  where α "represents the sensitivity of futur prices to the imbalance" and the formula is written from the buy order's viewpoint (Same = bid). Simulations use α = 4 (pp. 15, 19) and compare α = 2, 5, 10 for latency cost (Figure 11, p. 19). Appendix C (p. 27) restates the resulting expected gain as `∆P = ±0.5 + (α/2) × Imb`.
- The authors stress (p. 12) that valuing the fill against P_{+∞} rather than the mid at t = 0 (as in Moallemi 2014) is what "introduces an effect close to adverse selection aversion": the controller will not sit at the top of a tiny queue facing a large opposite queue.

### 3.3 Who accepts adverse fills (Section 2.3, pp. 5–9)

- Neutralised average imbalance at the moment a class's limit order is executed, `ρ_τ(a) = (Q^same − Q^opposite)/(Q^same + Q^opposite)` averaged with equal buy/sell weights R′(a) (p. 6).
- **Table 2 (p. 6)** [paper result]: average imbalance at execution — Global Banks sell 0.35 / buy −0.38 (62,111 / 63,566 events); HFP sell 0.32 / buy −0.33 (52,315 / 46,875); Institutional Brokers sell 0.57 / buy −0.52 (6,226 / 4,646). (Sign convention here: a *buy* limit executed at Imb −0.5 means the bid queue was much smaller than the ask — an adverse book.)
- **Figure 2 (p. 7)**: Institutional brokers accept fills at the most adverse imbalance (≈ −0.5); Global banks in between; HFP about half as adverse (≈ −0.3). Splitting HFP: HF market makers accept *more* adverse imbalance than the HFP average ("probably for inventory reasons: they have to alternate buys and sells ... probably paid back from this adverse selection by bid-ask spread gains"), HF proprietary traders the least adverse (p. 7).
- **Figure 3 (p. 8)**, price profiles ±400 trades around the fill, in units of the average spread: brokers buy while the price is falling and it keeps falling after (≈ −0.08 to −0.10 spreads); for banks the price is flat before and drops after; for HFP the price *rises* before they are filled ("It implies that they inserted their limit order shortly before the trade", p. 8); HF prop traders suffer less post-fill adverse move than HF market makers (p. 9).
- Authors' reading (p. 9): "there is a value in taking liquidity imbalance into account"; the HFP profile is evidence of a cancel-and-reinsert policy driven by imbalance.

### 3.4 State space, controls, dynamics (Section 3, pp. 9–14)

- One atomic buy order q_ε at the best bid, horizon T_f; if unfilled at T_f, cross the spread (p. 9).
- **State (p. 9):** `U^µ_t = (Q^{Before,µ}_t, Q^{After,µ}_t, Q^{Opp,µ}_t, P^µ_t)` — quantity ahead of the order, behind it, at the opposite best, and the mid; `Q^Same = Q^Before + Q^After`. Discrete chain adds `Exec_n ∈ {−1,0,1}` (p. 13).
- **Flows (p. 10):** four counting processes with intensities `λ^{Opp,+}, λ^{Same,+}` (insertions) and `λ^{Opp,−}, λ^{Same,−}` (cancellations *and* trades, not distinguished), functions of (Q^Opp, Q^Same) only, with bid-ask symmetry; unit quantities. Eq. (2), p. 10:
  `Q^Opp_t = Q^Opp_{t−} + q∆N^{Opp,+} − q∆N^{Opp,−}`; `Q^Before_t = (Q^Before_{t−} − q∆N^{Same,−}) 1{Q^Before_{t−} ≥ q}`; `Q^After_t = Q^After_{t−} + q∆N^{Same,+} − q 1{0 ≤ Q^Before_{t−} < q} ∆N^{Same,−}`.
- **Depletion rules (pp. 10–11):** if Q^Opp hits 0 the price ticks up, a discovered quantity `Q^Disc` becomes the new opposite and an inserted quantity `Q^Ins` fills the gap on our side, Q^After = 0 (we are re-posted at the top of the new bid if we were in the book); if Q^Before hits 0 we are executed; if Q^Same hits 0 the price ticks down.
- **Controls (pp. 11–12):** `C = {s, c}` — *c* stay; *s* cancel and wait, re-inserting later "at the top of Q^same" (i.e. at the back of the queue — the cost of cancelling is losing priority).
- **Objective (p. 12):** `V_T(0,U) = sup_µ E[∆P^µ_∞]`, `∆P^µ_∞ = lim_{t→∞}(P^µ_t − P^{Exec,µ}_{T_Exec})`, execution price `P_t − 1/2` if filled passively, `P_t + 1/2` if forced to cross at T_f. Discrete version: `Z_{k0} = P_{∞,k0} − P_{Exec,k0}` (eq. 3, p. 13); `V_{U0,f} = sup_µ E(Z_{k0})` with DP `G_f = Z_f, G_n = max(P^c_n G_{n+1}, P^s_n G_{n+1})` (eq. 4, p. 14). Transition probabilities in Appendix A (pp. 23–25) are products `λ∆t Π(1 − λ'∆t)`.
- **Framework 1 assumptions (p. 13):** one small order that does not move imbalance; queue decreases = trades (no cancel/trade distinction); unit moves; intensities functions of best-limit quantities only; no simultaneous events.

### 3.5 Numerical results (Section 4, pp. 14–19)

- Two intensity specifications (pp. 14–15): (CONST) `λ^{·,+} = 0.06, λ^{·,−} = 0.5`, Q^Disc = 6, Q^Ins = 4; (IMB) `λ^{Opp,+} = λ⁺_0 + β⁺ Q^Opp/(Q^Opp+Q^Same)`, `λ^{Opp,−} = λ⁻_0 + β⁻ Q^Same/(Q^Opp+Q^Same)` with λ⁺_0 = 0.06, λ⁻_0 = 0.5, β⁺ = 0.075, β⁻ = 0.25, `Q^Disc = ⌈6 + 3·Q^Same⌉`, `Q^Ins = ⌈2 + 0.5·Q^Same⌉` (typo in paper lists θ^disc twice); α = 4, f = 20, P0 = 10. The (IMB) shape is stated to be "compatible with empirical findings of [Huang et al., 2015]" (p. 15).
- Figure 7 (p. 15): optimal control cancels at t = 0 when initial imbalance is strongly negative (red points); E(∆P | Exec) for the no-control "join the bid" policy falls to ≈ −1.5 at Imb ≈ −1 while the optimal control keeps it near 0 or above; under (IMB) the controller cancels earlier because cancellation intensity is imbalance-sensitive (p. 16).
- Figure 8 (p. 16): price improvement of OC over NC is ≈ 0 for positive imbalance and up to ≈ +1.5–2.0 (ticks, model units) at strongly negative imbalance; average execution price improved by up to ≈ 0.7–0.8.
- Figure 9 (p. 17): OC has longer duration (it waits); stay ratio falls as imbalance turns negative. Figure 10 (p. 18): value increases and concavely saturates with remaining time; activity rises near T_f.
- **Latency cost definition, eq. (5), p. 18:** a participant with latency factor τ ∈ N* observes the chain only every τ steps, `U^µ_{τn}`; `Latency_{U0,f}(τ) = V_{U0,f} − V_{U0,f,τ}`, `V_{U0,f,τ} = sup_µ E(Z_{τ,f})`.
- **Figure 11 (p. 19)** [paper result, model units = ticks of the toy book, initial Imb = 0.5, Q^After = 2, Q^Before = 1, Q^Opp = 1]: latency cost rises monotonically with τ from 1.5 to 5.5 and is higher for higher α: under (CONST) roughly 0.2 → 1.0 for α = 10, lower for α = 2; under (IMB) roughly 0.1 → 0.8. Conclusions (p. 19): "The latency cost increases with the latency factor τ"; "The latency cost is higher when sensitivity to adverse selection increases (i.e α is big)"; "being able to predict future liquidity consuming flows is of less use if you can't cancel and reinsert your limit orders at each change of the orderbook state ... the faster will have more profits than the slower".

### 3.6 Limitations

- Stated (pp. 20): single order, no inventory, no game between participants, parameters not estimated from data ("currently our simulations are highly memory consuming"), value of speed may depend on market stress.
- **[inference]** Latency is measured in *book events*, not seconds, and the toy intensities (0.06 insertions, 0.5 removals per step) are arbitrary; the reported latency costs (0.1–1.0 ticks) are not transferable numbers. The empirical part shows *who* eats adverse fills, not how much latency costs them.
- **[inference]** Cancelling and re-inserting at the back is the only control; the model cannot represent price-improving quotes (small tick) or partial cancels, so it is a large-tick result.

### 3.7 Implications for a KuCoin maker

- **What "1 ms" buys [inference].** The relevant quantity is τ = (our reaction time) / (inter-event time at the touch), not milliseconds. On KuCoin mid-caps with tens of ms between top-of-book events, our ≈ 3.2 ms event-to-order path (2.2 ms data + ≈ 1 ms order entry) puts us at τ ≈ 1 — the paper's full-information controller — so imbalance-driven cancel/re-insert is fully available and the latency cost curve says we lose little versus the ideal. On KuCoin BTC with sub-ms event spacing (and 5 ms as our historical backtest assumption), τ ≫ 1: by Figure 11 the value of an imbalance cancel signal is largely eroded, and the higher α is (the more imbalance predicts price on BTC at short horizons), the more we lose. This argues for measuring inter-event times per symbol before investing in a cancel-signal on BTC.
- **Rebate interaction [inference].** The model's payoff has no fee; adding a OUR_FEE rebate shifts the "stay" region toward more adverse imbalance (the paper's own reading of HF market makers, p. 7: they accept worse imbalance because spread/rebate pays them back). For a 1-tick-spread mid-cap the rebate is a fixed fraction of the tick and the α/2·Imb threshold at which cancelling beats staying can be computed with our calibrated α — this is the normalised cancel rule that fits the "no un-normalised thresholds" red line.
- **The behavioural evidence is a benchmark [paper result → inference].** If our fills on KuCoin cluster at neutralised imbalance ≈ −0.5 we are trading like the institutional brokers (Figure 2); ≈ −0.3 like HFP; the HF prop traders show that with fast cancel/re-insert one can be filled at near-zero imbalance with a rising pre-fill price (Figure 3b). Computing R′ and the ±N-trade price profile on our own fills is a cheap diagnostic that needs no model.
- **Formula to reuse [paper result].** `P_∞ = P_mid + (α/2)·Imb` with α estimated per symbol from E[mid move over next N trades | Imb] (their Figure 1a is linear). For small-tick BTC they warn (p. 5) that first-level imbalance alone is weak and deeper levels should be included; Gould & Bonart quantify this (paper 6).

### 3.8 Hypothesis card — Lehalle & Mounjid (2016/2018)

**Strategy hypothesis (what is the edge?)**
A resting order that is cancelled when the touch imbalance turns strongly against it and re-inserted later obtains a better expected price than one that always stays, and the gain shrinks as reaction latency (measured in book events) grows. H3: on KuCoin mid-caps our 3.2 ms path is fast enough (τ ≈ 1) for the imbalance cancel to add value net of lost queue priority; on BTC it is not (τ ≫ 1). [inference: mapping to our latency]

**Economic mechanism (why should this edge exist?)**
Touch imbalance predicts the next mid move, P_∞ = P + (α/2)·Imb; a passive buy filled when the bid is thin is filled just before the price drops (adverse selection). Cancelling avoids that fill at the cost of re-entering at the back of the queue and possibly never trading. Slow participants (institutional brokers) do not make this trade-off and supply the adverse fills.

**Required data (L1 / L2 / L3 / trades / order events)**
Paper: L1 sizes and prices from a direct feed + trades labelled with member identity. For us: L1/L2 touch sizes + trades for α and for the control backtest; own order events (fills with timestamps) for the "who accepts adverse fills" diagnostic. Participant labels do not exist on KuCoin — only our own fills can be classified.

**Holding horizon (1ms / 10ms / 100ms / …)**
Decision clock = every top-of-book event (the model's time step). Evaluation horizon: mid move over the next ~50 trades (Figure 1a) and price profile over ±400 trades (Figure 3). In clock time this is tens of ms to tens of seconds on a mid-cap, sub-ms to seconds on BTC [inference].

**Expected signal (what observable predicts the edge?)**
Own-side neutralised imbalance ρ = (Q^same − Q^opp)/(Q^same + Q^opp) and quantity ahead/behind the order; α estimated as twice the slope of forward mid move (in ticks) on imbalance.

**Execution dependency (queue / latency / fill probability)**
Latency: central — τ = reaction time ÷ inter-event time. Queue: each cancel forfeits priority (re-insert at the back). Fill probability: the controller deliberately lowers it (longer strategy duration, Figure 9).

**Failure modes (why might it disappear?)**
τ > 1 on fast books; spread > 1 tick (the model has no in-spread orders; first-level imbalance loses power, p. 5); a rebate large enough that staying beats cancelling (HF market makers in the paper accept more adverse imbalance than HF prop traders); everyone running the same rule so that queues evaporate together; Albers' evidence that a crude imbalance-cancel rule (cancel at imb = 0) did not improve a touch maker on Binance (−0.49 vs −0.47 bp).

**Evidence (paper + empirical result, with numbers)**
AstraZeneca, NASDAQ-OMX, Jan–Sep 2013, 376,672 trades. Average imbalance at passive execution (Table 2): institutional brokers +0.57 (sell) / −0.52 (buy); global banks +0.35 / −0.38; HFP +0.32 / −0.33; HF prop traders least adverse (Figure 2b). Post-fill mid move for brokers ≈ −0.08 to −0.10 average spreads (Figure 3). Model: optimal control beats "join the bid" by up to ≈ 1.5–2 ticks at imbalance ≈ −1 (Figure 8a, toy parameters); latency cost rises from ≈ 0.1–0.2 to ≈ 0.8–1.0 ticks as τ goes 1.5 → 5.5 and is larger for larger α (Figure 11). No empirical latency cost in market units is reported.

**Test (the exact experiment we should run on KuCoin Futures data)**
- Contracts: one mid-cap USDT perpetual (tick ≥ 1 bp, 1-tick spread most of the time) and XBTUSDTM. Data: Tardis L2 increments + trades, training days.
- Step 0: median and 10th-percentile inter-event time at the touch, Δ_e; τ = 3.2 ms ÷ Δ_e. Report per symbol and per hour.
- Step 1: α per symbol = 2 × OLS slope of (mid after 50 trades − mid now, in ticks) on touch imbalance; report R² and linearity (Figure 1a analogue).
- Step 2: single-order control backtest, buy and sell symmetric, back-of-queue entry (pessimistic rule of card 1). Policy NC: join the touch, never cancel until the level is no longer the touch. Policy OC(θ): cancel when ρ < −θ, re-join at the back when ρ > −θ/2, with θ on a grid {0.3, 0.5, 0.7} chosen on half the training days and evaluated on the other half. Run OC with 0 ms and with 3.2 ms reaction delay. Statistic: mean signed (mid after 50 trades − fill price) in bp per *submitted* order (unfilled = 0) plus rebate × fill rate; Latency cost = value(OC, 0 ms) − value(OC, 3.2 ms).
- Pass/fail: H3 passes on a symbol if value(OC, 3.2 ms) − value(NC) ≥ +0.2 bp per submitted order with day-bootstrap 95% CI excluding 0 on the held-out days, and latency cost ≤ 50% of the zero-latency improvement. Fails if the improvement is < 0.1 bp or the CI includes 0. Prediction to be falsified: pass on the mid-cap, fail on BTC.
- Diagnostic on live fills (any strategy already running): neutralised imbalance at our passive fills R′ and the ±400-trade price profile. Benchmark: |R′| ≈ 0.33 = HFP-like, ≥ 0.5 = institutional-broker-like (we are the adverse-fill supplier).

---

## 4. Huang, Lehalle, Rosenbaum (2015) — "Simulating and Analyzing Order Book Data: The Queue-Reactive Model"

**Citation.** W. Huang (LPMA UPMC & Kepler-Cheuvreux), C.-A. Lehalle (CFM), M. Rosenbaum (LPMA UPMC), "Simulating and analyzing order book data: The queue-reactive model", arXiv:1312.0563v2, 3 Sep 2014; Journal of the American Statistical Association 110(509):107–122, 2015.

### 4.1 Market / data context (Section 2.2, pp. 5–6)

- Cheuvreux LOB database, **Euronext Paris, January 2010 – March 2012**, 5 best limits each side, every book change; first and last trading hour removed. Two large-tick stocks: **France Telecom** (159,250 orders/day, 7,282 trades/day, average spread 1.43 ticks) and **Alcatel-Lucent** (129,400 / 8,626 / 1.99 ticks) (Table 1, p. 6). "Large tick asset" = spread almost always 1 tick; framework "relevant for any asset whose average spread is smaller than 2.5 ticks" (footnote 1, p. 2). No fees.
- Quantities in units of **AES_i** (average event size at limit i, includes insertions and cancellations), not ATS; FTE: ATS 637, AES1 836, AES2 1068, AES3 1069 shares (Table 2, p. 28). Queue size = ⌈volume / AES_i⌉ (p. 7). K = 3 limits per side (p. 7).
- Reference price p_ref (p. 6): mid when spread is odd in ticks; when even, mid ± tick/2 choosing the value closest to the previous p_ref.

### 4.2 Model and estimation (Sections 2.1–2.3, pp. 4–8)

- 2K-dimensional continuous-time Markov jump process X(t) = (q_{−K},…,q_{−1},q_1,…,q_K) with generator `Q_{q,q+e_i} = f_i(q)`, `Q_{q,q−e_i} = g_i(q)` (p. 4). **Theorem 2.1 (p. 5):** ergodic under Assumption 1 (negative drift for large queues: `f_i(q) − g_i(q) < −δ` when q_i > C_bound) and Assumption 2 (bounded total insertion rate).
- **Model I** (p. 7): independent queues, `f_i(q) = λ^L_i(q_i)`, `g_i(q) = λ^C_i(q_i) + λ^M_i(q_i)`, bid-ask symmetric.
- **Estimation (p. 8), MLE = conditional empirical means:**
  `Λ̂_i(n) = (mean(∆t_i(ω) | q_i(ω) = n))^{−1}`,
  `λ̂^L_i(n) = Λ̂_i(n)·#{T_i(ω) ∈ E⁺, q_i(ω)=n}/#{q_i(ω)=n}`, likewise for cancellations (E⁻) and market orders (E^t); recording restarts at each p_ref change. CIs from CLT (Appendix 5.2).
- **Invariant distribution, Model I (p. 10):** `ρ_i(n) = λ^L_i(n)/(λ^C_i(n+1) + λ^M_i(n+1))`, `π_i(n) = π_i(0) Π_{j=1}^n ρ_i(j−1)`, `π_i(0) = (1 + Σ_n Π_j ρ_i(j−1))^{−1}`. Figure 3 (p. 11): matches empirical queue distributions well; the Poisson model (constant L/M, linear C) does not.

### 4.3 Key empirical shapes of the intensities (Section 2.3.2, pp. 8–9; Figure 2 p. 8; Alcatel Figure 13 p. 26) [paper result]

- **Limit insertion at Q±1:** "approximately a constant function of the queue size, with a significantly smaller value at 0" (posting into an empty best queue creates a new price level — risky). At Q±2 and Q±3: *decreasing* in queue size — "posting orders at the second limit when the corresponding queue size is small to seize priority" (p. 9).
- **Cancellation at Q±1:** "increasing concave function for q±1 between 0 and 25, and becomes flat/slightly decreasing for larger values. This result is in contrast to the classical way to model this flow, where one often considers a linearly increasing cancellation rate" — explained by *priority value*: orders in a long queue have valuable priority and are cancelled less (p. 9). At Q±2 the asymptote is reached faster and is lower; at Q±3 nearly linear above 3 AES and large when the queue equals one (alone in the queue ⇒ cancel quickly).
- **Market orders at Q±1:** "The rate decreases exponentially with the available volume at Q±1" — "rushing for liquidity" when liquidity is rare, "waiting for better price" when abundant (p. 9). Order of magnitude (Figure 2, FTE): insertion ≈ 1.5–3 /s, cancellation up to ≈ 0.8 /s, market orders ≈ 0.05–0.3 /s.
- **Model IIa (pp. 11–12, Figure 4):** Q±2 intensities depend on 1{q±1 > 0}; when q±1 = 0 insertion at Q±2 reaches its asymptote quickly (market makers rarely allow >3-tick spreads), cancellation is higher; when Q±2 is best, market-order intensity is similar to Q±1 but shows an unexpected *increase* above 5 AES2. Invariant law via QBD / matrix-geometric (Appendix 5.3).
- **Model IIb — bid-ask coupling (pp. 13–14, Figure 6; m = 4 AES1, l = 9 AES1 for FTE):** limit insertion at Q1 is a *decreasing* function of the opposite queue size and "significantly larger" when the opposite queue is empty; cancellation rate is a decreasing function of opposite-side liquidity ("when this level becomes low, many market participants cancel their limit orders and send market orders since the market is likely to move in an unfavorable direction"); market orders are *more* frequent when opposite liquidity is abundant (the target queue is then "relatively cheap") and larger when the opposite queue is empty than when it is merely small (p. 14).
- **Execution probability application (Section 2.5, p. 16, Figure 9):** probability that a buy order at Q−1 of size n0 = 1 AES executes before Q1 depletes, as a function of initial (bid, ask) sizes, via Monte Carlo under Assumptions 3–4 (cancellations uniform across the queue; our order never cancelled; cancellation intensity scaled by (q−n0)/q). All three QR models give similar surfaces; "the Poisson model clearly overestimates them" (p. 16). Caveat (p. 16): "Orders with lower priority are actually more likely to be canceled, see Gareche ... execution probabilities might be slightly overestimated".

### 4.4 Queue-reactive model with price moves (Section 3, pp. 17–18)

- p_ref moves by one tick with probability θ when the mid moves *and* q±1 = 0 (triggers: in-spread insertion while the other side is empty, last order cancelled, last order consumed); with probability θ_reinit the whole book is redrawn from the invariant law ("percentage of price changes due to exogenous information") (p. 17). Calibrated on 10-minute mid volatility and the Robert–Rosenbaum mean-reversion ratio η = N_c/(2N_a): **θ = 0.7, θ_reinit = 0.85** for FTE (p. 20).
- **Maximal mechanical volatility (p. 18):** with θ_reinit = 0, θ = 1, the purely book-driven volatility is **5 bp vs 14 bp empirical** (10-min), and η = 0.08 vs empirical 0.39 — endogenous queue dynamics alone are far too mean-reverting; "the often reversed bid-ask imbalance immediately after a change of p_ref" [paper result].
- Order-placement application (Section 3.2, pp. 19–22): "Fire and forget" vs "Pegging to the best" tactics, 60 AES1 over 20 × 10-min slices; pegging has higher passive fill rate but larger and progressive impact; impact concave in time and size (square-root-like), Figures 11–12.

### 4.5 Limitations

- Stated: no order-flow memory (Hawkes) — "adding such feature ... would probably be relevant" (p. 22); constant order sizes per level; only 2 stocks; cancellation position within the queue unmodelled (Assumptions 3–4).
- **[inference]** Intensities are per-second in a 2010–2012 European equity book; only the *shapes* transfer. The 2.5-tick average-spread applicability bound (footnote 1) excludes small-tick BTC-style books from direct use of Model I/II.

### 4.6 Implications for a KuCoin maker

- **Fill model in the backtester [inference].** Our engine fills from L2 deltas with a queue estimate. The paper's Figure 9 shows a Poisson/linear-cancel fill model *overestimates* execution probability relative to queue-reactive intensities, and its own Assumption 3–4 note says even the QR estimate is biased upward because real cancellations come from the back. Since our 2026-09-12 fix showed the earlier positive results were fill-model artefacts, the queue-reactive shapes are the literature basis for a conservative fill model: market-order intensity falling exponentially with our-side queue size, cancellation-ahead-of-us concave and *lower* for long queues (our position improves slowly in long queues), plus the Model IIb coupling (fewer insertions behind us and more cancellations ahead of us when the opposite queue thins — which is exactly when we are about to be adversely filled).
- **Estimation is feasible on Tardis L2 + trades [paper result → inference].** The authors themselves used a 5-level aggregated book, not order-level data. The estimator is a conditional mean of inter-event times per queue-size bin; events are classified as L (size increase at a level), M (decrease matched by a trade print at that price) or C (decrease with no matching trade); per symbol per day it needs a few thousand events. Normalising queue size by AES (not ATS) makes the intensity curves comparable across mid-caps, satisfying the normalisation rule.
- **Mid-caps vs BTC [inference].** For a mid-cap with 1-tick spread the QR framework applies as is (spread < 2.5 ticks). The finding that insertion intensity is *constant* in queue size while cancellation saturates means long queues persist — being at the back of a long mid-cap queue is a long wait with adverse selection at the end (Albers Table 1 back-of-queue rows). For BTC with a multi-tick spread the second/third-limit behaviour (insertion decreasing in queue size, priority-seeking at the second level, in-spread posting) is the relevant part; Model I's Q±1 shapes will not fit.
- **Mechanical volatility [inference].** Their result that queue dynamics generate only ~1/3 of volatility and over-strong mean reversion implies that a simulator without exogenous re-initialisation (θ_reinit) will under-represent the sudden adverse moves that Albers identifies as the dominant loss source. Any QR-based simulator we build must include θ_reinit-type shocks calibrated to KuCoin realised vol.

### 4.7 Hypothesis card — Huang, Lehalle & Rosenbaum (2015)

**Strategy hypothesis (what is the edge?)**
Primarily a fill-model hypothesis rather than an alpha: order-flow intensities at each level are functions of the queue state, so execution probability of a resting order depends on queue size ahead and on the opposite queue, and state-blind (Poisson) or queue-front fill models overstate it. H4a: on KuCoin mid-caps a queue-reactive fill model predicts synthetic-order execution frequency materially better than our queue-front assumption. Secondary, tradable idea reported by the authors: H4b — posting at the second level when that queue is small "to seize priority" yields a front position when the level becomes the touch (pp. 9, 12).

**Economic mechanism (why should this edge exist?)**
Participants react to the visible book: takers "rush for liquidity" when the touch is thin and wait when it is thick (market-order intensity decays exponentially in queue size); holders of priority in long queues cancel less (priority value ⇒ concave, saturating cancellation rate); when the opposite queue thins, same-side makers cancel and takers switch to market orders because the efficient price has moved toward them (Model IIb).

**Required data (L1 / L2 / L3 / trades / order events)**
Paper: 5-level aggregated book updates + trades (no order IDs). For us: Tardis L2 increments + trades are the same class of data and sufficient: classify each change at a level as L (increase), M (decrease matched by a trade print at that price) or C (decrease without a trade).

**Holding horizon (1ms / 10ms / 100ms / …)**
Model clock = periods of constant reference price (the paper's large-tick stocks: seconds to minutes; Wu et al. report ≈ 100 s for the Bund, ≈ 16 s for the DAX). Intensities are per second: insertions ≈ 1.5–3 /s, cancellations ≤ 0.8 /s, market orders 0.05–0.3 /s at the touch for France Telecom.

**Expected signal (what observable predicts the edge?)**
Queue size at Q±1, Q±2, Q±3 in AES units; indicator that Q±1 is empty; opposite-queue bucket (empty / ≤ 33rd pct / middle / ≥ 67th pct). Derived: arrival/departure ratio ρ(n) = λ^L(n)/(λ^C(n+1)+λ^M(n+1)).

**Execution dependency (queue / latency / fill probability)**
Fill probability and queue position: the whole point. Latency: none in the model. H4b depends on latency only weakly (the order is placed before the level becomes the touch).

**Failure modes (why might it disappear?)**
Small tick / average spread > 2.5 ticks (outside the stated validity range, fn. 1); strong order-flow memory (paper 5 shows QR alone misfits inter-event times); crypto regime shifts within a day; cancellation position unobserved, so execution probabilities remain biased upward (authors' own caveat, p. 16); purely endogenous dynamics under-produce volatility (5 bp vs 14 bp), so a QR simulator without exogenous shocks understates adverse moves.

**Evidence (paper + empirical result, with numbers)**
France Telecom and Alcatel-Lucent, Euronext Paris, Jan 2010 – Mar 2012 (≈ 159k / 129k orders per day, spreads 1.43 / 1.99 ticks). Shapes: touch insertion ≈ constant in queue size (lower at 0); touch cancellation concave up to ≈ 25 AES then flat; touch market-order rate exponentially decreasing in queue size; second-level insertion decreasing in queue size. Invariant queue distributions from Model I match the empirical ones, the Poisson model does not (Figure 3); Poisson model "clearly overestimates" execution probability (Figure 9). Maximal mechanical volatility 5 bp vs empirical 14 bp per 10 min; η 0.08 vs 0.39; calibrated θ = 0.7, θ_reinit = 0.85.

**Test (the exact experiment we should run on KuCoin Futures data)**
- Contract: a mid-cap USDT perpetual with tick ≥ 1 bp and average spread < 2.5 ticks (state the measured average); XBTUSDTM as an expected out-of-range control. Data: Tardis L2 increments + trades, training days; first half for estimation, second half for evaluation.
- Step 1: AES per level; queue size = ⌈size/AES⌉; estimate λ^L, λ^C, λ^M per queue-size bin at Q±1..Q±3 with the paper's conditional-mean estimator (p. 8), plus Model IIb conditioning on the opposite-queue tercile. Shape checks: sign of the log-slope of λ^M in q (expected negative), concavity of λ^C.
- Step 2 (model adequacy): invariant law π from the Model I formula (p. 10) vs the empirical touch-queue distribution sampled every 30 s on the evaluation days. Statistic: total-variation distance. Pass ≤ 0.10; fail > 0.20.
- Step 3 (fill-model test, the decision-relevant one): synthetic min-size orders joining the back of the touch at random times, held until fill or until the opposite touch queue depletes. Compare realised "filled" frequency under the pessimistic back-of-queue rule of card 1 with (a) the queue-front assumption and (b) QR Monte Carlo (Assumptions 3–4), in a 5 × 5 grid of (same-side, opposite-side) queue-size quintiles. Statistic: mean absolute error in fill probability across cells. Pass for H4a: MAE(QR) ≤ 0.05 and MAE(queue-front) ≥ 0.10; H4a fails if queue-front is within 0.05 of realised (then the current assumption is harmless on that symbol).
- Step 4 (H4b): synthetic orders placed at the second level whenever q_{±2} ≤ 1 AES and held; record, for those that become the touch, the fraction of the level's size that is behind them and their +1 s / +5 s markout after fill. Pass: median liquidity-behind share ≥ 50% and net markout (with rebate) higher than back-of-touch joins by ≥ 0.3 bp with CI excluding 0.

---

## 5. Wu, Rambaldi, Muzy, Bacry (2019) — "Queue-reactive Hawkes models for the order flow"

**Citation.** P. Wu, M. Rambaldi, J.-F. Muzy, E. Bacry (Université Paris-Dauphine CEREMADE; CNRS Université de Corse), "Queue-reactive Hawkes models for the order flow", arXiv:1901.08938v1 [q-fin.TR], 25 Jan 2019.

### 5.1 Market / data context (Section 2.2, pp. 5–6)

- **Eurex futures, Bund and DAX, 1 Oct 2013 – 30 Sep 2014**, level-1 tick-by-tick snapshots with microsecond stamps and trade markers; 9:00–21:00 Frankfurt (p. 5). **Table 1 (p. 6)** [paper result]: Bund 5.41×10⁷ limit, 4.67×10⁷ cancel, 6.29×10⁶ market orders per day at the best quotes; average spread 1.012 ticks, median 1.0; AES 6.34 contracts; median inter-event time 4.89×10⁻⁴ s. DAX 5.46×10⁶ / 5.62×10⁶ / 6.68×10⁵; spread 1.591 (median 2.0); AES 1.30; median inter-event 1.73×10⁻³ s. Bund = large tick, DAX = smaller tick, "slimmer queues" (p. 5). No fees.
- Queue in AES units, eq. (10), p. 6: `q(t) = ⌈v(t)/AES⌉`. Bund queue distribution broad up to ~150 AES; DAX concentrated below ~10 (Figure 1, p. 6). Periods of constant p_ref: 1,207,099 (Bund), 417,581 (DAX); mean realisation length τ_m ≈ 100 s (Bund), ≈ 16 s (DAX) (p. 6). Queue autocorrelation time τ_c ≈ 15 s Bund, ≈ 2 s DAX (p. 11).

### 5.2 Models

- **General QRH, eq. (2), p. 2:** `λ^ℓ(t) = µ^ℓ(q(t)) + Σ_m ∫ φ^{ℓm}(t − s, q(t)) dN^m_s`.
- **QRH-I (single best queue, fixed price), eq. (4), p. 4:** `λ^ℓ(t) = µ^ℓ(q(t−)) + Σ_m ∫_0^t φ^{ℓm}(t−s) dN^m_s`, ℓ, m ∈ {L, M, C}; λ^M = λ^C = 0 when q = 0. Kernels: sums of exponentials, eq. (6): `φ^{ℓm}(t) = Σ_{u=1}^U α^{ℓm}_u β_u e^{−β_u t}` with **U = 3; β = 60, 1500, 5500 s⁻¹ (Bund), 40, 2100, 5200 s⁻¹ (DAX)** (p. 6). Log-likelihood eq. (5)/(7), convex; (q, ō) is Markov and V-uniformly ergodic if Σ_{ℓ∈I} µ^ℓ(q) ≥ c q and µ^L bounded (Appendix A.1).
- **QRH-II (both best queues, Bacry et al. 8-event model P⁺, P⁻, L^a, L^b, C^a, C^b, M^a, M^b), eq. (17), p. 12:** `λ^ℓ(t) = f^ℓ(q_a(t), q_b(t)) · ( µ^ℓ + Σ_m ∫_0^t φ^{ℓm}(t−s) dN^m_s )`, f normalised by `f^ℓ(q¹_a, q¹_b) = 1` (eq. 18), states = quintile pairs; estimated by least squares (eq. 20, p. 15) to allow negative (inhibitory) kernels, since positive-constrained MLE biases kernels (p. 14).

### 5.3 Results — self/cross excitation share [paper result]

- Goodness of fit (Tables 2–3, p. 7): QRH-I vs QR log-likelihood 2.055×10⁸ vs 2.046×10⁷ (Bund), 9.506×10⁶ vs 7.268×10⁵ (DAX); LR test p < 10⁻¹⁶; inter-event-time QQ plots (Figure 2, p. 8) show QR badly misses the distribution and QRH-I reproduces it. Table 4–5 (p. 13): QRH-II beats pure Hawkes, LR p < 10⁻¹⁶.
- **Endogenous fraction, eq. (14), p. 8:** `e^ℓ(q) = 1 − µ^ℓ(q)/Λ^ℓ(q)`, Λ^ℓ(q) = E[λ^ℓ | q]. "a large part, from 60% to 80%, of the total average intensity is explained by the self- and cross-exciting effect" (p. 8). Figure 5 (p. 10) axis ranges: Bund e^L 60–85%, e^C 75–100%, e^M 60–100%; DAX e^L 50–75%, e^C 55–85%, e^M 45–60%. "for cancel and market orders, the intensity is maximally explained by the Hawkes term when the queue is small ... the opposite effect is found for limit orders, namely an higher endogeneity for higher values of q" (p. 9).
- Baseline shapes under QRH-I (Figure 4, p. 9): µ^M decreasing in q (as Huang), µ^C increasing for large q, and — unlike Huang's stocks — µ^L *decreasing* in q ("a lesser quest for priority when q is large"); all baseline levels far below the QR-model µ's because the Hawkes part absorbs most intensity (p. 8).
- **Kernel norm matrices, Figure 6 (p. 10), QRH-I (same side):** strong diagonal (self-excitation from order splitting); "market orders influence liquidity much more than the opposite effect"; "**market order[s] have on average an exciting effect on cancellations** ... a flow of market order at a given price signals that the 'true' price is closer to that side and therefore liquidity adapts, with outstanding orders being canceled in order not to be adversely selected" (p. 9–10). Norms in the 0.15–0.60 range on the colour scale.
- **QRH-II state functions (Figures 9–10, pp. 16–17):** the imbalance `I(t) = (q_b − q_a)/(q_b + q_a)` (eq. 21, p. 15) "captures most of the variations" of f^ℓ. Bund: f spans "almost three orders of magnitude" for P and M events across I ∈ (−1, 1); threshold effect — below I = −1/2 upward mid moves are "dramatically inhibited", while large positive I only marginally raises them; M-event f "gets very large ... when there is hardly anything left on the ask side" (rushing for the last liquidity); L and C "much less sensitive to the state of the book" (p. 15). DAX: dependence "much less pronounced" except for mid-price changes; regime switch around I = 1/2 for M and C when the ask queue is very small and the spread is one tick (p. 15). Bund quintile edges (Figure 9 caption): ]0,80], ]80,165], ]165,258], ]258,386], ]386,∞[ contracts; DAX: ]0,2], ]2,3], ]3,5], ]5,8], [8,∞[.
- QRH-II kernel matrix (Figure 11, p. 18, least squares): Bund — a mid-up (P⁺) *lowers* limit-order rate on the ask and raises cancels on the ask (efficient price near the ask ⇒ no gain from posting there); limit orders on one side coupled with cancels on the other ("a simple market maker strategy (rebalancing of the position)") — absent on DAX; on DAX market/limit/cancel orders influence price changes more because queues are thin (p. 17). Average-intensity reproduction error 4–14% (Table 6, p. 17).
- **Mean reversion (Table 7, p. 18):** probability two successive mid changes have opposite direction: **Bund 0.65, DAX 0.56**. In QRH-II this is carried by f(q_a,q_b), not by P⁺→P⁻ kernels (Figure 12, p. 18: imbalance right after a P⁺ is mostly negative).

### 5.4 Limitations

- Stated (p. 19): QRH-II treats queues as exogenous; unit order sizes; no spread dependence (needed for small tick); memory reset at each p_ref change in QRH-I; stability theory for queue-dependent Hawkes incomplete.
- **[inference]** Level-1 only; futures with a single venue; 2013–14. The 60–80% endogeneity figure depends on the exponential-kernel horizon choice (slowest β = 40–60 s⁻¹ ⇒ ~20 ms memory); longer memory would push it higher.

### 5.5 Implications for a KuCoin maker

- **Fill and cancel dynamics are event-driven, not Poisson [paper result → inference].** With 60–80% of top-of-book intensity being self/cross-excited, and especially with **trades exciting same-side cancellations**, the moments after a taker hits our side are exactly when (i) queue ahead of us shrinks fastest (others cancel), (ii) more takers arrive (M self-excitation), and (iii) the mid is most likely to move against us. A fill model or a simulator with state-only (QR) intensities will miss the clustering that concentrates fills into adverse bursts; QRH-I is the minimum structure. The tick (Bacry et al. `tick` library) implements this class; U = 3 exponentials with β spanning ~10 ms to ~1 s is their working choice.
- **Imbalance dependence is a large-tick phenomenon [paper result].** On the Bund the imbalance moves P and M intensities by ~3 orders of magnitude; on the DAX (spread ~1.6 ticks) the effect is weak except for mid moves. Mapping: mid-cap USDT/USDC perps with a 1-tick spread ⇒ Bund-like, imbalance is the state variable to condition quotes and cancels on, and the −1/2 threshold for "price move against us is almost certain" is a normalised trigger; BTC with a multi-tick spread ⇒ DAX-like, first-level imbalance is a weak driver and we need spread and deeper levels (also Lehalle p. 5, Gould & Bonart Section 7).
- **The "rush for the last liquidity" [paper result → inference].** On the Bund, market-order intensity explodes when the opposite queue is nearly empty. For us as the maker on the *other* side this is the arrival of the taker burst that will lift the level; for our order on the *thin* side it is the fill-then-move event. A cancel rule keyed to the thin-side queue dropping below a quintile threshold is the practical form of this.
- **Mean-reversion rate as a normalised statistic [paper result].** 0.65 (Bund) vs 0.56 (DAX) is a one-number summary of how much of the post-fill adverse move reverts; Albers' "reversals" (15% of high-fill-prob orders) live in the same quantity. Measuring it per KuCoin symbol tells us how large-tick-like each mid-cap is.

### 5.6 Hypothesis card — Wu, Rambaldi, Muzy & Bacry (2019)

**Strategy hypothesis (what is the edge?)**
Top-of-book events cluster: most of the intensity of trades and cancellations is triggered by recent events, and same-side trades trigger same-side cancellations. H5: conditional on a burst of taker trades at our touch in the last tens of ms, (i) the queue ahead of us shrinks abnormally fast, (ii) our fill probability jumps and (iii) the fill's markout is worse than an unconditional fill — so a burst-triggered cancel (or a "do not join" rule) improves net markout, provided the burst is observable more than 3.2 ms before the fill. [inference: the paper documents the excitation structure, not a trading rule]

**Economic mechanism (why should this edge exist?)**
Order splitting makes market orders self-exciting; a run of takers on one side reveals that the efficient price is nearer that side, so resting makers there cancel "in order not to be adversely selected" (pp. 9–10) and fewer limit orders are added; when the touch is nearly empty takers rush for the last liquidity (f^M very large at extreme imbalance on the Bund).

**Required data (L1 / L2 / L3 / trades / order events)**
Paper: level-1 snapshots with microsecond timestamps + trade markers. For us: Tardis L2 increments + trades are sufficient for the 3-event (L, C, M) and 8-event (P±, L, C, M per side) classifications. Timestamp quality is the binding constraint: exchange timestamps must resolve events at ≤ 1 ms, otherwise the two fastest kernels are unidentifiable.

**Holding horizon (1ms / 10ms / 100ms / …)**
Kernel time scales 1/β: ≈ 0.18 ms, 0.67 ms and 17 ms (Bund); ≈ 0.19 ms, 0.48 ms and 25 ms (DAX). Only the slowest component (≈ 20 ms) is slower than our 3.2 ms loop [inference]. Queue autocorrelation time 15 s (Bund) / 2 s (DAX); constant-reference-price periods ≈ 100 s / 16 s.

**Expected signal (what observable predicts the edge?)**
Exponentially weighted counts of recent same-side M and C events (decays matching the kernels); touch imbalance I with the −1/2 threshold; individual queue sizes near I = 0; time since last mid change (mean-reversion of the mid: 0.65 Bund, 0.56 DAX).

**Execution dependency (queue / latency / fill probability)**
Latency: decisive — the reaction window is the kernel memory. Queue: cancellations ahead of us after a trade improve our position exactly when a fill is most toxic. Fill probability: rises in bursts, i.e. fills are concentrated in the adverse states.

**Failure modes (why might it disappear?)**
The excitation mass sits in sub-ms kernels we cannot act on; KuCoin feed timestamps too coarse or batched to separate cause from effect; crypto flow dominated by cross-venue lead–lag (exogenous to the local book) rather than local self-excitation; on small-tick books the state dependence is weak (DAX result) and spread must be added to the state.

**Evidence (paper + empirical result, with numbers)**
Eurex Bund and DAX futures, Oct 2013 – Sep 2014 (Bund: 5.4×10⁷ limit, 4.7×10⁷ cancel, 6.3×10⁶ market orders/day at the touch; spread 1.012 ticks; DAX spread 1.591). QRH-I log-likelihood ≈ 10× that of QR (2.055×10⁸ vs 2.046×10⁷ Bund), LR p < 10⁻¹⁶. Endogenous share of intensity 60–80% overall; for cancels and market orders highest when the queue is small. Kernel norms up to ≈ 0.6 on the diagonal; M → C (same side) positive. QRH-II: f for P and M events spans ≈ 3 orders of magnitude across imbalance on the Bund, weak on the DAX; intensity reproduction error 4–14% (Table 6).

**Test (the exact experiment we should run on KuCoin Futures data)**
- Contracts: one mid-cap USDT perpetual (tick ≥ 1 bp) and XBTUSDTM. Data: Tardis L2 increments + trades with exchange timestamps, training days; half for fitting, half for evaluation.
- Step 0 (feasibility gate): distribution of exchange-timestamp gaps between consecutive touch events; if > 50% of events share a timestamp with their predecessor at the available resolution, stop — the test is not identifiable on this data.
- Step 1 (structure): fit QRH-I by maximum likelihood with U = 3 exponential kernels (β grid chosen by penalised likelihood, starting from the paper's 40–60, 1500–2100, 5200–5500 s⁻¹) on constant-reference-price periods with ≥ 20 events. Statistics: LR test QRH-I vs QR; endogenous fraction e^ℓ(q); kernel norm |φ^{C,M}| and the share of it carried by kernels with 1/β ≥ 10 ms (the "actionable share" at 3.2 ms).
- Step 2 (model-free, decision-relevant): synthetic back-of-queue fills (pessimistic rule of card 1) split by a flag B = "≥ 2 taker trades at our touch price in the window [t_fill − 23.2 ms, t_fill − 3.2 ms]" (information available to us in time). Statistics: P(fill within the next 100 ms | B) vs unconditional; mean +1 s markout of flagged vs unflagged fills; share of all fills that are flagged.
- Pass/fail: H5 passes if flagged fills are worse by ≥ 0.3 bp at +1 s (day-bootstrap 95% CI excluding 0) *and* flagged fills are ≥ 10% of fills (otherwise the rule is immaterial). H5 fails if the difference is < 0.1 bp, or if the actionable share from Step 1 is < 20% (excitation exists but is too fast for us). Paper-consistency check: LR test rejects QR at p < 0.01 and e^C, e^M ≥ 50%.

---

## 6. Gould & Bonart (2015/2016) — "Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book"

**Citation.** M. D. Gould and J. Bonart (CFM–Imperial Institute of Quantitative Finance, Imperial College London), "Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book", arXiv:1512.03492v1 [q-fin.TR], 11 Dec 2015 (published Market Microstructure and Liquidity 2(2), 2016).

### 6.1 Market / data / tick context (Section 4, pp. 8–11)

- **LOBSTER (Nasdaq), all 252 trading days of 2014, 10:00–15:30**; tick π = [amount removed] for all stocks; only b(t), a(t), n_b(b(t),t), n_a(a(t),t) used (p. 8–9).
- Stock selection (p. 9): top-5 by 2014 dollar volume with max price < [amount removed] = **large-tick** (MSFT, INTC, MU, CSCO, ORCL; mean spread [amount removed], mean best queues 3,100–18,100 shares) and top-5 with min price > [amount removed] = **small-tick** (GOOG, AMZN, TSLA, PCLN, NFLX; mean spread [amount removed], mean best queues 80–204 shares) (Table 1, p. 10). Intermediate-price stocks were checked and fell into one of the two behaviours (p. 9). No fees.

### 6.2 Definition and methodology (Sections 3.3 and 5, pp. 7, 11–14)

- **Queue imbalance, eq. (7), p. 7:** `I(t) := (n_b(b_t,t) − n_a(a_t,t))/(n_b(b_t,t) + n_a(a_t,t)) ∈ [−1, 1]`.
- Sample construction (p. 11): T = set of mid-price change times; `y_i = 1` if m(t_i) > m(t_{i−1}) else 0 (eq. 9); the imbalance `I_i = I(t̃_i)` sampled at a time **uniformly at random in (t_{i−1}, t_i)** (eq. 10) — event-time sampling gave qualitatively identical results (p. 12). 100 random mid-changes per stock per day ⇒ 25,200 points per stock; **80/20 random train/test split** (20,160 / 5,040) (p. 12).
- **Logistic regression, eq. (17), p. 13:** `ŷ(I) = 1/(1 + e^{−(x0 + I x1)})`, interpreted as P(y_i = 1 | I_i). Null model ŷ ≡ 1/2 (eq. 18), whose mean squared residual is exactly 1/4 (p. 14). Binary classification assessed by out-of-sample ROC/AUC; probabilistic by mean squared residual `r_i = ŷ_i − y_i` (eq. 19). Local logistic regression with tricube kernel, nearest-neighbour bandwidth 0.65 chosen by 5-fold CV (pp. 14, 22).

### 6.3 Results [paper result]

- **Table 2 (p. 17), coefficients (SE):** large tick x1: MSFT 2.49 (0.04), INTC 2.56, MU 2.03, CSCO 2.73, ORCL 2.25; small tick x1: GOOG 0.54 (0.02), AMZN 0.85, TSLA 0.60, PCLN 0.50, NFLX 0.65. Intercepts |x0| ≤ 0.06 (significant only for CSCO, ORCL, GOOG — a weak buy-side asymmetry in a year those stocks rose, p. 26). x1 significant at 99% for all 10 (Table 3, p. 18).
- "when I is close to 1, the probability of an upward price move is about **0.8 to 0.9 for large-tick stocks, but only about 0.6 to 0.7 for small-tick stocks**" (p. 18).
- **Table 4 (p. 20), out-of-sample AUC:** MSFT 0.762, INTC 0.798, MU 0.752, CSCO 0.805, ORCL 0.770; GOOG 0.581, AMZN 0.642, TSLA 0.602, PCLN 0.583, NFLX 0.627 (in-sample within ±0.02). Summarised (p. 3) as an improvement of binary classification over the null "by about 50–60% for large tick stocks and about 10–30% for small-tick stocks".
- **Table 5 (p. 21), out-of-sample mean squared residual (null = 0.25):** large tick 0.180–0.202 (**20–30% reduction**); small tick 0.235–0.246 (**2–6% reduction**); GOOG worst at ~2% (p. 25).
- **Local logistic (Figure 6, Table 6, pp. 23–24):** essentially identical performance (differences in the third decimal). For large-tick stocks two regimes: ŷ is steep for |I| < 0.25 and much flatter outside — "a relatively small difference in the queue imbalance corresponds to a considerable change in the probability" near balance, diminishing returns at extremes (p. 22). For small-tick stocks ŷ(I≈1) ≈ 0.6 and the curves are non-monotonic (all but PCLN), not attributable to over-fitting (p. 23).
- Distribution of I (Figure 2, p. 15): broad for large-tick; strong round-number spikes at I = 0, ±1/3 for small-tick because queues are often exactly 100 or 200 shares (p. 15–16).
- **Mechanism (Section 7, pp. 25–26):** with spread = 1 tick the mid can move only by one queue depleting, so I directly governs the race between the two queues; with spread > 1 tick in-spread limit orders are a second cause of mid moves that I cannot see, and because the tick is the "cost of buying priority", small-tick queues are short, so I is noisier. Authors note performance would improve "considerably" if one only forecast when |I| ≈ 1 or when both queues are large (p. 25).

### 6.4 Limitations

- Stated: one-tick-ahead direction only, not magnitude or timing (p. 11, p. 28); I sampled at a random time within the interval — sampling right before/after a change or using deeper levels or log-ratio left for future work (p. 28); Nasdaq-only order flow (p. 11).
- **[inference]** Direction of the *next* mid change is not the same as the sign of the return over a fixed horizon relevant to a maker's markout; a strong one-tick predictor on a large-tick book is largely the mechanical "smaller queue empties first" effect, so it is already priced by anyone (Albers Table 2 shows it does not pay as a taker after fees and does not pay as a naive maker).

### 6.5 Implications for a KuCoin maker

- **Mid-caps (large relative tick, 1-tick spread) — Bund/MSFT regime [inference].** Expect AUC ≈ 0.75–0.8 for next-mid direction from level-1 imbalance alone; at |I| > 0.5 the wrong side of the book is almost certainly about to be lifted. Consequences: (i) a two-sided quote at |I| > 0.5 is a near-certain adverse fill on the thin side (Albers' high-fill/negative-drift corner) — cancel the thin side; (ii) the fitted logistic slope x1 per symbol is a normalised, literature-backed way to turn imbalance into a skew/cancel probability instead of fixed bp thresholds (satisfies the normalisation rule); (iii) the two-regime shape means most of the information is in |I| < 0.25 — a threshold at 0.5 throws it away.
- **BTC (small relative tick, multi-tick spread) — GOOG regime [inference].** Level-1 imbalance gives AUC ≈ 0.58–0.64 and only a 2–6% Brier improvement; do not build a BTC cancel/skew rule on level-1 imbalance alone — use depth-aggregated imbalance and the spread state (Lehalle p. 5; Wu p. 19). This is consistent with our own finding that RS1/OBI-type signals added ≈ 0.2 bp on BTC.
- **Fill-time predictability is what hurts [inference].** Gould & Bonart sample I at a random time; Albers sample it at the fill. The mechanical fact "we were filled ⇒ a taker hit our side ⇒ I moved against us" means the *post-fill* one-tick direction is even more predictable (adverse) than these AUCs suggest for a maker. The practical upshot is the same as Albers': the profit is in the exceptions (reversals), which by construction are the ~15–35% of cases where the large-tick logistic model is wrong.
- **Out-of-sample discipline [paper result].** Their in-sample vs out-of-sample AUC/Brier agreement within 0.02 is the benchmark a signal this simple should meet on our OOS days; a bigger gap on KuCoin would indicate regime non-stationarity rather than over-fitting.

### 6.6 Hypothesis card — Gould & Bonart (2015/2016)

**Strategy hypothesis (what is the edge?)**
The level-1 queue imbalance predicts the direction of the next mid-price change, strongly when the spread is pinned at one tick and weakly otherwise. H6: on KuCoin mid-caps (tick ≥ 1 bp) out-of-sample AUC ≥ 0.70; on BTC (tick ≈ 0.01 bp) ≤ 0.65. The tradable use is defensive: skew or cancel the thin-side quote; the paper itself tests no strategy. [inference: thresholds mapped from the paper's two groups]

**Economic mechanism (why should this edge exist?)**
With a one-tick spread the mid can move only when one touch queue empties, so the shorter queue wins the race and I measures the race directly; with a wider spread, in-spread limit orders are a second cause of mid moves that I does not see, and because priority is cheap to buy by price, touch queues are short and I is noisy (pp. 25–26).

**Required data (L1 / L2 / L3 / trades / order events)**
L1 only: best bid/ask prices and sizes through time (the paper uses exactly four series). Tardis L2 increments more than suffice; trades are not needed.

**Holding horizon (1ms / 10ms / 100ms / …)**
Until the next mid-price change — an event horizon, not a clock horizon. On large-tick names this is seconds to minutes; on small-tick names (and BTC) milliseconds to seconds [inference]. The prediction says nothing about magnitude or timing.

**Expected signal (what observable predicts the edge?)**
I = (n_b − n_a)/(n_b + n_a) at the touch, through ŷ(I) = 1/(1 + e^{−(x0 + x1 I)}); most of the information is in |I| < 0.25 for large-tick names (local-logistic regime change); extra power when both queues are large and when |I| ≈ 1.

**Execution dependency (queue / latency / fill probability)**
None in the paper (pure prediction). For a maker: the same I that predicts the move also sets fill probability (Albers) — the side the signal favours is the long queue where we will not be filled, the side it warns about is where we will. Latency: I is public and instantaneous; acting on it within 3.2 ms competes with everyone.

**Failure modes (why might it disappear?)**
Spread > 1 tick (documented drop to AUC ≈ 0.6); thin or round-lot queues (I takes few values, spikes at 0, ±1/3); information in deeper levels dominating (small tick); the signal being fully mechanical and already priced — Albers shows it pays neither as a taker after fees nor as a naive maker; spoofable touch sizes on crypto venues.

**Evidence (paper + empirical result, with numbers)**
Nasdaq (LOBSTER), all of 2014, 25,200 samples per stock, 80/20 split. Large-tick (MSFT, INTC, MU, CSCO, ORCL): x1 = 2.03–2.73, out-of-sample AUC 0.752–0.805, mean squared residual 0.180–0.202 vs 0.25 null (20–30% better), P(up | I ≈ 1) ≈ 0.8–0.9. Small-tick (GOOG, AMZN, TSLA, PCLN, NFLX): x1 = 0.50–0.85, AUC 0.581–0.642, residual 0.235–0.246 (2–6% better), P(up | I ≈ 1) ≈ 0.6–0.7. In-sample and out-of-sample AUC differ by ≤ 0.02. Local logistic regression adds nothing material.

**Test (the exact experiment we should run on KuCoin Futures data)**
- Contracts: three mid-cap USDT perpetuals with tick ≥ 1 bp (ideally one with ~1-tick and one with ~2-tick typical spread) and XBTUSDTM; USDC twins where traded. Data: Tardis L2 increments (touch only), training days.
- Procedure (the paper's, unchanged): for each day list mid-change times; draw 100 of them at random; for each, sample I at a uniformly random time in the preceding constant-mid interval; label y = 1 if the change is up. Pool days; random 80/20 split; fit eq. (17) by maximum likelihood on the 80%.
- Statistics on the 20%: AUC; mean squared residual; fitted x1 with standard error; in-sample minus out-of-sample AUC; the same restricted to intervals where the spread was exactly 1 tick; and, as an actionability check, the same with I sampled 3.2 ms before the mid change instead of at a random time.
- Pass/fail: H6 (mid-cap) passes if out-of-sample AUC ≥ 0.70 and mean squared residual ≤ 0.21 with |AUC_in − AUC_out| ≤ 0.02; fails if AUC < 0.65. H6 (BTC) is confirmed if AUC ≤ 0.65 and falsified if ≥ 0.70 (BTC would then behave like a large-tick book despite its tick, as Albers' Binance description suggests it might). A symbol whose x1 is within the 2.0–2.7 band is "large-tick-like" for the purposes of cards 1–5.
- Economic follow-up (links to card 1): split the T1 synthetic fills by |I| at posting (< 0.25, 0.25–0.5, > 0.5) and side (with / against I); the paper predicts fills against a strong I are frequent and adverse, fills with it rare.

---

## 7. Cross-paper synthesis — eight decision-relevant findings

1. **Naive two-sided quoting at the touch loses money even with a rebate; the rebate size is roughly the whole game.** Albers (Binance BTC perp, 233k live min-size orders): unconditional maker markout OUR_FEE gross / −0.3 bp net at OUR_FEE rebate; naive MM −0.44 bp per round trip net of OUR_FEE rebates, Sharpe −109; imbalance-conditioned posting and a cancel-at-zero rule do not fix it (−0.47/−0.49 bp) [paper results]. At our OUR_FEE (USDT) the same numbers become ≈ −0.1 bp per fill and ≈ −0.04 bp per round trip — neutral, not positive, before size and latency penalties; at OUR_FEE (USDC) ≈ +0.4 bp per fill and ≈ +0.96 bp per round trip, on books too thin for the Binance number to transfer; a taker exit at OUR_FEE is never covered (their imbalance taker grosses ≈ +1 bp per round trip against 3.6 bp of our fees) [inference]. Volume-first quoting on a BTC-like book therefore has an expected cost near zero *only if* KuCoin adverse selection equals Binance's; this must be measured on KuCoin before U15 goes live.
2. **Post-fill return is a function of queue position at fill, not of the imbalance you posted into.** Albers Table 1: front-decile fills −0.06 to −0.56 bp at 1 s, back-quartile fills −0.68 to −1.16 bp; in a large queue the front/back gap is 0.7–0.9 bp; in a small queue position barely matters [paper result]. Every front-decile cell beats OUR_FEE, so with our rebate front-of-queue fills are net positive in every configuration and back-of-queue fills in large queues are not [inference]. Moallemi–Yuan give the same conclusion in ticks on NASDAQ large-tick names: front-vs-average-queue value 0.21–0.26 ticks (BAC), touch-vs-back 0.03–0.36 ticks across 9 names, adverse selection 0.53–0.89 ticks > half-spread, so the 0.3-tick rebate is what keeps back-of-queue orders positive [paper results]. **Our backtests assume queue-front matching — the assumption Albers call untenable (p. 6) — so on mid-caps (tick ≥ 1 bp, long touch queues) they are biased upward by an amount comparable to the rebate itself: OUR_FEE–0.9 bp on Albers' numbers, 0.2–0.3 ticks (≥ 0.2–0.3 bp at a ≥ 1 bp tick) on Moallemi–Yuan's [inference].** Quantifying that bias (card 1, T1) comes before any other conclusion drawn from those backtests.
3. **Fill probability is easy to predict and that is the trap.** Albers' OLS on (Q^near, Q^opp, imb) has R² = 0.946; fill probability ranges 30–90% and is highest exactly where the post-fill drift is worst (small near queue, large opposite queue) [paper result]. Optimising quoting on fill probability alone "risks optimizing for a pyrrhic victory" (p. 36). Our fill-rate KPIs should always be paired with the 1-s/5-s markout grid by (QP_T, Q^near, Q^opp).
4. **The only structurally profitable maker fill is front-of-queue in a large same-side queue with favourable imbalance, and you cannot get there by joining it.** You must post when the queue is small (adverse imbalance) and be right that it reverses (Albers pp. 24–25). Their 173-feature logistic reversal model reaches +0.71 bp/round trip (Sharpe 12, 654 fills/day, holding 268 s) only at thresholds that discard >95% of orders, and the authors say it is not scalable [paper result]. Reversal features that mattered: recent return oscillation (negative autocovariance) over 15 s, a sharp 100 ms drop to a level with little liquidity but depth just below, high trade intensity, short top-of-book survival, many small same-direction trades.
5. **Latency matters for the cancel, not the post, and its value scales with how predictive the imbalance is.** Lehalle–Mounjid: latency cost (value lost by a controller that sees the book only every τ events) increases in τ and in α (imbalance-to-price sensitivity) [paper result, model units]; optimal control cancels at strongly negative imbalance and re-inserts, which is the behaviour visible in the fills of HF prop traders (filled at near-zero imbalance with the price rising into the fill) vs institutional brokers (filled at imbalance ≈ −0.5 with the price still falling after) [paper result]. For us the event-to-order path is ≈ 3.2 ms (2.2 ms data + ≈ 1 ms order): on mid-caps with tens of ms between touch events that is ≈ full-information (τ ≈ 1); on BTC with sub-ms event spacing, an imbalance cancel signal is largely eroded by our own latency [inference]. Wu et al.'s kernels make the same point from the other side: two of the three excitation time scales (≈ 0.2 ms and ≈ 0.5–0.7 ms) are faster than our loop; only the ≈ 20 ms component is actionable. Measure inter-event times per symbol before building cancel logic.
6. **Imbalance is a strong one-tick predictor only when the spread is one tick — i.e. on mid-caps, not on BTC.** Gould–Bonart: out-of-sample AUC 0.75–0.81 and Brier improvement 20–30% for large-tick Nasdaq names vs AUC 0.58–0.64 and 2–6% for small-tick names; P(up | I≈1) ≈ 0.8–0.9 vs 0.6–0.7; most information sits in |I| < 0.25 [paper results]. Wu et al. on Eurex: imbalance moves price-change and market-order intensities by ~3 orders of magnitude on the Bund (1-tick spread) with a hard threshold at I = −1/2, but only weakly on the DAX (1.6-tick spread) [paper result]. A fitted per-symbol logistic slope x1 is the normalised way to express this; fixed bp thresholds are not.
7. **Order flow at the touch is 60–80% self/cross-excited and trades excite same-side cancellations.** Wu et al. QRH-I: endogenous share 60–80% overall, highest for cancels and market orders when the queue is small; kernel matrix shows market orders exciting cancellations because takers reveal the efficient price and makers pull quotes to avoid adverse selection [paper result]. Huang et al.: market-order intensity decays exponentially in same-side queue size, cancellation is concave and saturates (priority value), Poisson/linear-cancel models over-estimate execution probability, and purely book-driven dynamics produce only 5 bp of the 14 bp 10-min volatility [paper results]. Our backtest fill model and any simulator must be queue-reactive with Hawkes clustering and exogenous shocks, or they will over-fill us in calm states and under-represent the adverse bursts — the same failure class as the 2026-09-12 matching bug.
8. **Most of this can be tested on the data we have; exact queue position cannot.** Four of the six papers used aggregated books, not order IDs: Huang (5-level book), Wu (level 1), Gould–Bonart (four L1 series), Lehalle–Mounjid (L1 + labelled trades) [paper results] — so their estimators run on Tardis L2 increments + trades as is. Moallemi–Yuan's primitives (γ/µ, trade-size law at 2 ms aggregation, jump sizes, λ) are also L2-computable; only the cancellation law is degraded. The one thing L2 cannot give is the Albers quantity that matters most — queue position at fill. Historically it can only be bracketed (front vs back, card 1 T1); exactly, it needs either the live min-size experiment (own order events — which is how Albers obtained it) or L3, which KuCoin is one of five venues to publish (Albers fn. 11) [paper result]. All tests in the cards use literature-specified, normalised estimators (AES units, ticks, imbalance in [−1, 1], logistic slope); none requires guessing a parameter [inference].

---

## 8. Reading-order and reuse notes

- For the fill/markout experiment design copy Albers Section 2 exactly (two modes, cancel-iff-not-at-touch, min size, one week), then Table 1 and Table 2.
- For a parametric queue-value model copy Moallemi–Yuan Section 4 calibration and solve (6)–(7) numerically (Volterra, trapezoid on a q-grid); validate against the Section 5 artificial-order backtest.
- For a cancel/re-insert controller copy Lehalle–Mounjid Section 3 with (IMB) intensities *replaced by Huang-style estimated λ(Q^Same, Q^Opp)* and α from a per-symbol regression of forward mid move on imbalance; then compute Latency(τ) with τ = our reaction time / measured inter-event time.
- For the simulator use Wu et al. QRH-I (U = 3 exponentials, β ≈ 40–60, ~1500–2100, ~5200–5500 s⁻¹) on top of Huang Model IIb intensities, with Huang's θ/θ_reinit for price moves.
- For imbalance-to-probability use Gould–Bonart eq. (17) per symbol with an 80/20 split and require in/out-of-sample AUC agreement within ~0.02.

---

## 9. Which hypothesis falsifiable on KuCoin Futures does each paper give us?

All tests: KuCoin USDT/USDC perpetuals, Tardis L2 increments + trades unless stated, training days only (the 9-day final exam stays untouched), day-block bootstrap 95% confidence intervals, synthetic orders delayed by 3.2 ms, fees OUR_FEE (USDT) / OUR_FEE (USDC) maker and OUR_FEE taker. "Back-of-queue rule" = liquidity ahead equals displayed size at arrival and is reduced only by trades at that price. Thresholds are mine [inference], anchored on the paper numbers quoted beside them.

| # | Paper | Falsifiable hypothesis on KuCoin Futures | Statistic | Confirmed if | Falsified if | Paper anchor |
|---|-------|------------------------------------------|-----------|--------------|--------------|--------------|
| 1 | Albers et al. 2025 | **H1 (queue position sets the sign of a maker fill).** For min-size touch orders, fills obtained at the front of the queue have +1 s markout above OUR_FEE while fills obtained at the back are lower by ≥ 0.3 bp; hence our queue-front backtests overstate maker PnL, and naive two-sided touch quoting nets ≈ 0 on USDT. | Mean +1 s / +5 s markout (bp, pre-rebate) of synthetic periodic-mode orders under the front rule and the back rule; live: Table 1 grid from own order events. | markout(front) − markout(back) ≥ 0.3 bp, CI excludes 0; and back-rule markout ≤ OUR_FEE on USDT (naive quoting not profitable). | Difference < 0.1 bp (queue position immaterial on that symbol), or back-rule markout > OUR_FEE with CI (naive quoting is net positive — the paper's central claim does not hold on KuCoin at our rebate). | Front −0.06 / −0.30 bp vs back −0.78 / −1.16 bp in large queues; unconditional OUR_FEE; naive round trip −0.44 bp net of OUR_FEE rebates. |
| 2 | Moallemi & Yuan 2017 | **H2 (queue priority is worth a material fraction of a tick on large-tick contracts).** On a mid-cap with tick ≥ 1 bp and a 1-tick spread, the value of a front-of-queue order exceeds that of a back-of-queue order by ≥ 0.1 tick, and the back-of-queue value is positive only because of the rebate. | V_front − V_back and V_back in ticks (value = signed fill price − mid 60 s later, + rebate, 0 if unfilled), from 1,000 artificial orders/day and from the calibrated α(q)δ − β(q). | Gap ≥ 0.1 tick with CI excluding 0; model within 0.05 tick of simulation; V_back − rebate < 0 ≤ V_back. | Gap < 0.05 tick, or V_back > 0 even with the rebate removed (adverse selection smaller than the half-spread — contrary to all nine names in the paper). | BAC front-vs-average 0.21–0.26 ticks; touch-vs-back 0.03–0.36 ticks; adverse selection 0.57–0.85 ticks > 0.5; rebate OUR_FEE ticks. |
| 3 | Lehalle & Mounjid 2016/18 | **H3 (imbalance-driven cancel/re-insert beats always-stay, and latency in book events erodes it).** With τ = 3.2 ms ÷ inter-event time, the rule adds value on a mid-cap (τ ≈ 1) and not on BTC (τ ≫ 1). | Per submitted order: signed (mid after 50 trades − fill price) + rebate × fill, for NC vs OC(θ) at 0 ms and 3.2 ms delay, back-of-queue re-entry; latency cost = OC(0) − OC(3.2 ms). | Mid-cap: OC(3.2 ms) − NC ≥ +0.2 bp with CI excluding 0 on held-out days and latency cost ≤ 50% of the zero-latency gain. BTC: gain at 0 ms, lost at 3.2 ms. | Mid-cap gain < 0.1 bp or CI includes 0 (loss of priority outweighs avoided adverse fills — as Albers found for a crude rule); or BTC shows no latency erosion. | Brokers filled at imbalance ≈ −0.5, HFP ≈ −0.33; latency cost increasing in τ and α (Figure 11, model units only). |
| 4 | Huang, Lehalle & Rosenbaum 2015 | **H4 (order flow is queue-reactive, so queue-front and Poisson fill models overstate execution).** On a mid-cap with average spread < 2.5 ticks, touch market-order intensity decreases with same-side queue size, cancellation is concave, and a queue-reactive Monte Carlo predicts back-of-queue fill frequency within 5 points while the queue-front assumption is off by ≥ 10 points. | Estimated λ^L, λ^C, λ^M by AES-normalised queue size; total-variation distance between model invariant law and empirical queue distribution; mean absolute error of fill probability over a 5 × 5 queue-size grid. | Negative log-slope of λ^M in q; TV ≤ 0.10; MAE(QR) ≤ 0.05 and MAE(queue-front) ≥ 0.10. | λ^M flat or increasing in q; TV > 0.20; or queue-front within 0.05 of realised (current assumption harmless). | λ^M exponentially decreasing; λ^C concave to ≈ 25 AES; Poisson model "clearly overestimates" execution probability; mechanical vol 5 bp vs 14 bp. |
| 5 | Wu, Rambaldi, Muzy & Bacry 2019 | **H5 (trades excite same-side cancellations and further trades; fills that follow a taker burst are more toxic, and part of that is visible in time).** | LR test QRH-I vs QR; endogenous fractions e^C, e^M; share of the M→C kernel norm at 1/β ≥ 10 ms; +1 s markout of back-rule fills flagged by "≥ 2 same-side trades in [t − 23.2 ms, t − 3.2 ms]" vs unflagged. | QR rejected at p < 0.01, e^C and e^M ≥ 50%; flagged fills worse by ≥ 0.3 bp (CI excludes 0) and ≥ 10% of fills. | Markout difference < 0.1 bp, or actionable kernel share < 20% (clustering exists but is faster than 3.2 ms), or timestamps too coarse to identify (test void, not failed). | Endogenous share 60–80%; M→C excitation positive; kernels at ≈ 0.2 ms, ≈ 0.5–0.7 ms, ≈ 17–25 ms; f spans ≈ 3 decades in imbalance on the Bund. |
| 6 | Gould & Bonart 2015/16 | **H6 (touch imbalance predicts the next mid move strongly iff the spread is one tick).** Mid-caps (tick ≥ 1 bp): out-of-sample AUC ≥ 0.70; BTC (tick ≈ 0.01 bp): ≤ 0.65. | Out-of-sample AUC, mean squared residual and x1 of the logistic fit of next-mid direction on I (100 random mid changes per day, 80/20 split), also with I taken 3.2 ms before the move. | Mid-cap AUC ≥ 0.70, residual ≤ 0.21, in/out gap ≤ 0.02; BTC AUC ≤ 0.65. | Mid-cap AUC < 0.65 (large tick alone does not create the Nasdaq effect on KuCoin), or BTC AUC ≥ 0.70 (BTC behaves large-tick-like, as Albers' Binance book description would suggest). | Large-tick AUC 0.75–0.81, residual 0.18–0.20, x1 2.0–2.7; small-tick AUC 0.58–0.64, residual 0.235–0.246, x1 0.5–0.85. |

**Order of execution [inference].** H6 first (L1 only, hours of work, classifies each symbol as large-tick-like or not and therefore decides which of H1–H5 are in scope for it). Then H1/T1 and H4 Step 3 together — both run on the same synthetic-order harness and jointly answer "how wrong is queue-front matching", which gates every existing backtest result. Then H2 (same harness, 60-s valuation), H3 and H5 (cancel rules, only meaningful once the fill model is trusted). The live min-size experiment (H1/T2) is the only test that measures true queue position and should be scheduled as soon as an account is available, because none of the historical tests can replace it.

**What none of these papers gives us [inference].** No paper tests a maker at a OUR_FEE or OUR_FEE rebate, on KuCoin, with order sizes above the minimum, or on a contract with tick ≥ 1 bp in crypto; every bp figure converted to our fee schedule in this report is arithmetic on someone else's adverse-selection number, not evidence. The only profitable maker result in the set (Albers' reversal model) is, by its authors' own statement, small, non-scalable and a proof of concept.
