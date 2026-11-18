# Order-flow / quoting literature: study report (original full texts)

Date: 2026-10-01. Prepared for the research3 line. Every statement below is taken from the original full text unless explicitly tagged `[inference]` (our reasoning) or `[not verified]` (no full text obtained). Numbers copied from a paper are tagged `paper result`.

Source files (PDF + pymupdf text extraction) are in `docs\research3\papers\`:

| # | Paper | File | Full text obtained? |
|---|---|---|---|
| 1 | Avellaneda & Stoikov 2008 | `avellaneda_stoikov_2008.pdf/.txt` (publisher version, QF 8(3), from NYU author page) | Yes (8 pp). Extraction dropped Greek glyphs; symbols below were reconstructed from equation structure and are flagged where ambiguous. |
| 2 | Cont, Kukanov, Stoikov | `cont_kukanov_stoikov_2014.pdf/.txt` (arXiv 1011.6402v3, 26 pp) | Yes |
| 3 | Stoikov, micro-price | `stoikov_2018_microprice.pdf/.txt` (author's Nov-26-2017 SSRN draft, 13 pp; arXiv 1509.01064 is an unrelated materials paper) | Yes |
| 4 | Xu, Gould, Howison | `xu_gould_howison_2019.pdf/.txt` (arXiv 1907.06230v2, 32 pp) | Yes |
| 5 | Cartea, Jaimungal, Ricci | `cartea_jaimungal_ricci_2014.pdf/.txt` (May-29-2012 preprint, 36 pp; SIAM final not open) | Yes (preprint) |
| 6 | Easley, López de Prado, O'Hara (VPIN) | `easley_lopezdeprado_ohara_2012_vpin.pdf/.txt` (NYU Stern-hosted working-paper version, 71 pp incl. tables) | Yes (WP version). Critique papers: **not obtained**. |
| 7a | Ho & Stoll 1981 | — | **Not obtained.** No open copy found (SSRN/Elsevier only). Only secondary descriptions from papers 1 and 5 are used, and marked as such. |
| 7b | Glosten & Milgrom 1985 | `glosten_milgrom_1985.pdf/.txt` (JFE scan, 30 pp) | Yes (OCR text is column-scrambled in places; formulas checked against page images' logical order) |
| 7c | Kyle 1985 | `kyle_1985.pdf/.txt` (Econometrica JSTOR scan, 22 pp) | Yes |

Our operating conditions used throughout ("our conditions"): KuCoin USDT/USDC perpetuals; maker rebate OUR_FEE (USDC OUR_FEE); taker fee OUR_FEE; REST order round trip 1.9 ms (one-way ≈ 1 ms); market-data one-way ≈ 2.2 ms; backtests assume queue-front matching; data = Tardis L2 increments + trades (aggressor side present, no order IDs); mid-caps: tick ≥ 1 bp, spread 1–2 ticks (i.e. "large-tick" regime); BTC: tick ≈ 0.01 bp (extreme "small-tick" regime).

---

## 1. Avellaneda & Stoikov (2008), "High-frequency trading in a limit order book"

**Citation.** M. Avellaneda, S. Stoikov, *Quantitative Finance* 8(3), April 2008, pp. 217–224. DOI 10.1080/14697680701381228. Received 24 Apr 2006, final 3 Apr 2007.

**Market / data / tick / fee context.** No empirical data. Motivation is Nasdaq's Inet LOB (p. 217). Simulation only: mid-price arithmetic Brownian motion, one-share quotes, no fees, no rebates, no tick grid (quotes are continuous), no adverse selection (mid is a martingale by construction, "our agent has no opinion on the drift or any autocorrelation structure for the stock", p. 218). The paper explicitly says it "will focus on the inventory effect" and not on asymmetric information (p. 217).

**Mechanism.** Two-step: (1) compute an inventory-dependent reservation (indifference) price under exponential utility; (2) place bid/ask at distances from that reservation price chosen against a Poisson fill-intensity that decays with distance from the mid. The intensity is derived from econophysics facts about market-order size tails and price impact.

**Core formulas (verbatim structure; Greek symbols reconstructed, see note).**
- Mid: `dS_u = σ dW_u` (eq. 1, p. 218).
- Value function of a frozen inventory q: `v(x,s,q,t) = −exp(−γx) exp(−γqs) exp(γ²q²σ²(T−t)/2)` (eq. 3, p. 218).
- Reservation bid/ask (eqs. 6–7, p. 219): `r^a = s + (1−2q)γσ²(T−t)/2`, `r^b = s + (−1−2q)γσ²(T−t)/2`.
- Reservation (indifference) price (eq. 8, p. 219): **`r(s,q,t) = s − qγσ²(T−t)`**.
- Intensity derivation (eq. 12, p. 220), using market-order size density `f^Q(x) ∝ x^{−1−α}` (eq. 9) and log impact `Δp ∝ ln Q` (eq. 11, Potters–Bouchaud):
  `λ(δ) = P(Δp > δ) = P(K ln Q > δ) = P(Q > exp(δ/K)) = Λ ∫_{exp(δ/K)}^∞ x^{−1−α} dx = A exp(−kδ)`, "where A = Λ/α and k = αK" (as printed, p. 220).
  With power impact `Δp ∝ Q^β` (eq. 10) they get `λ(δ) = B δ^{−α/β}` (p. 220).
  `[inference]` Carrying out the printed integral gives `(Λ/α)·exp(−(α/K)δ)`, i.e. k = α/K, not αK; the printed "k = αK" is dimensionally inconsistent with eq. (12) and is a known typo. Use k = α/K if you calibrate from (α, K).
  Empirical inputs quoted by the paper (p. 220): α = 1.53 (Gopikrishnan et al. 2000, US stocks), 1.4 (Maslov–Mills 2001, Nasdaq), 1.5 (Gabaix et al. 2006, Paris); impact exponent β = 0.5 (Gabaix) or 0.76 (Weber–Rosenow). Λ "could be estimated by dividing the total volume traded over a day by the average size of market orders on that day" (p. 220).
- HJB (p. 220, unnumbered) and exact optimal distances (eqs. 18–19, p. 221):
  `s − r^b(s,q,t) = δ^b − (1/γ) ln(1 − γ λ^b(δ^b)/(∂λ^b/∂δ)(δ^b))`, and symmetrically for the ask.
- Symmetric exponential intensities (eq. 20, p. 221): `λ^a(δ) = λ^b(δ) = A e^{−kδ}`.
- Linear-approximation solution (eqs. 29–30, p. 221):
  **`r(s,t) = s − qγσ²(T−t)`**, **`δ^a + δ^b = γσ²(T−t) + (2/γ) ln(1 + γ/k)`**.
  The spread "is independent of the inventory. This follows from our assumption of exponential arrival rates" (p. 221).
- Infinite-horizon (stationary) reservation prices with discount ω are given on p. 219 (unnumbered): `r^a = s + (1/γ) ln(1 + (1−2q)γ²σ²/(2ω − γ²σ²q²))`, valid for ω > γ²σ²q²/2 (natural choice ω = γ²σ²(q_max+1)²/2).
- Appendix: geometric BM + mean/variance objective gives `R^a = s + (1−2q)(γ/2)s²(e^{σ²(T−t)} − 1)` (p. 224).

**Reported numbers (paper result).** Simulation parameters: s = 100, T = 1, σ = 2, dt = 0.005, q_0 = 0, γ = 0.1, k = 1.5, A = 140; 1000 paths (p. 222). "Symmetric" benchmark = same average spread centred on mid.

| γ | Strategy | Avg spread | Profit | Std(profit) | Final q | Std(final q) |
|---|---|---|---|---|---|---|
| 0.1 (Table 1, p. 222) | Inventory | 1.49 | [amount removed] | [amount removed] | 0.08 | 2.9 |
| 0.1 | Symmetric | 1.49 | [amount removed] | [amount removed] | 0.26 | 8.4 |
| 0.01 (Table 2) | Inventory | 1.35 | [amount removed] | [amount removed] | 0.12 | 5.1 |
| 0.01 | Symmetric | 1.35 | [amount removed] | [amount removed] | 0.09 | 8.7 |
| 1 (Table 3, p. 223) | Inventory | 3.02 | [amount removed] | [amount removed] | 0.02 | 1.7 |
| 1 | Symmetric | 3.02 | [amount removed] | [amount removed] | 0.00 | 5.1 |

Authors' reading: symmetric "obtains a slightly higher return since it is centred around the mid-price, and therefore receives a higher volume of orders", inventory strategy has "much smaller variance" (p. 222); as γ → 0 the two coincide (p. 223).

**Limitations (from the paper and `[inference]`).** No adverse selection, no fees/rebates, no tick, no queue, one-share quotes updated "at no cost" continuously; dt must be "larger than the typical tick time" (p. 222); only 1000 simulated paths; intensity form assumes constant Λ. `[inference]` The model's edge is pure spread capture on a martingale mid; every empirical paper below (2–7) says the mid is *not* a martingale conditional on the book, which is exactly what this model ignores.

**Implications for our maker (~1 ms order latency, OUR_FEE rebate, KuCoin perps).**
- `[inference]` With a rebate r the per-fill cash flow is δ + r, so eq. (30) shifts: the fee-adjusted optimal half-spread is ≈ max(0, (γσ²(T−t))/2 + (1/γ)ln(1+γ/k) − r). For BTC (tick 0.01 bp) this is a continuous problem and the model pushes quotes inside the book; for mid-caps the tick (≥ 1 bp) exceeds the whole rebate and the spread term, so the model degenerates to "join the touch or not" — its continuous δ is not the decision variable.
- `[inference]` The only robust qualitative content is the inventory skew `−qγσ²(T−t)`: skewing halves P&L std at a 5–30 % cost in mean (Tables 1–3). For a volume target ([amount removed]/3 months) the symmetric quote is the higher-volume choice; use the skew as risk control, not as alpha.
- `[inference]` k (fill decay) can be calibrated from our Tardis trades: α from the market-order size tail, K from the trade-size → impact relation. Note the k = αK vs α/K issue above. Fill intensity as a function of distance is what our queue-front backtest silently over-states.

### Card — Avellaneda & Stoikov
- **Strategy hypothesis (what is the edge?)** Spread capture around an inventory-skewed reservation price on a martingale mid; no directional alpha.
- **Economic mechanism (why should this edge exist?)** Liquidity provision compensated by the spread; inventory risk priced via exponential utility.
- **Required data (L1 / L2 / L3 / trades / order events)** L1 (mid) + trades (to calibrate A, k). No L3 needed.
- **Holding horizon (1ms / 10ms / 100ms / …)** Model horizon T (paper: 1 "day"); fills at Poisson rate — effectively seconds to minutes per round trip.
- **Expected signal (what observable predicts the edge?)** None (mid is a random walk). Inventory q is the only state.
- **Execution dependency (queue / latency / fill probability)** Entirely on λ(δ) being an accurate fill rate: queue position and latency are not modelled (quotes "continuously updated at no cost").
- **Failure modes (why might it disappear?)** Adverse selection (mid drifts against fills); tick discreteness; fill-rate misspecification; rebate not modelled.
- **Evidence (paper + empirical result, with numbers)** Simulation only (Tables 1–3): inventory skew cuts P&L std from 12.7 to 6.6 at γ=0.1 with mean 65.0 vs 68.4.
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)** Contract: one mid-cap USDT perp (e.g. SOL) + BTC. Data: Tardis L2 + trades, 5 training days (Sept) / 9 OOS days (`data/oos/ku_buy`). Statistic: (a) fit λ(δ) = A e^{−kδ} from realized fill distances (with queue model, not queue-front) and check the exponential form (log-linear R² > 0.8); (b) run symmetric vs inventory-skewed quoting with identical average spread; pass if skew reduces P&L std ≥ 30 % with mean fee-adjusted P&L not lower by more than 10 %, on OOS days, fees OUR_FEE included. Fail otherwise (then the skew parameter γ should not be used as a tuning knob).

---

## 2. Cont, Kukanov, Stoikov (2014), "The price impact of order book events"

**Citation.** R. Cont, A. Kukanov, S. Stoikov, *Journal of Financial Econometrics* 12(1), 2014, 47–88. Read version: arXiv:1011.6402v3 (13 Apr 2011, "March 2011"), 26 pp.

**Market / data / tick / fee context.** NYSE TAQ consolidated quotes + trades, April 2010 (21 trading days), 50 S&P 500 stocks chosen at random (Table 1, pp. 10–11). Timestamps rounded to the second; NBBO reconstructed across exchanges (Appendix). Tick = 1 cent; average spread across the 50 stocks 2 cents, but "mostly equal to 1 cent" (p. 15); average best-quote depth 227 shares (grand mean), ranging from 5 (CME) to 3208 (BAC). Quote updates / trades ≈ 40 : 1 (p. 8). Base timescale Δt = 10 s inside half-hour windows (10:00–15:30); robustness checked from "10 quote updates (usually less than half of a second)" to 10 minutes: "The fit of our model generally increases with Δt, but the rest of the results stays the same" (p. 8). No fees considered.

**Mechanism.** Every L1 event (limit, market, cancel) changes the best bid/ask queue by a signed amount; summing these gives order-flow imbalance (OFI). In a stylised book with constant depth D beyond the best quotes, price change is *mechanically* OFI/(2D). Empirically the relation is linear with slope β inversely proportional to depth.

**Core formulas (verbatim).**
- Event contribution (p. 4): `e_n = 1{P^B_n ≥ P^B_{n−1}} q^B_n − 1{P^B_n ≤ P^B_{n−1}} q^B_{n−1} − 1{P^A_n ≤ P^A_{n−1}} q^A_n + 1{P^A_n ≥ P^A_{n−1}} q^A_{n−1}`.
- **OFI (p. 4): `OFI_k = Σ_{n=N(t_{k−1})+1}^{N(t_k)} e_n`**; price change in ticks `ΔP_k = (P_k − P_{k−1})/δ`.
- Stylised model (eq. 1, p. 6): `ΔP = OFI/(2D) + ε`, `OFI = L^b − C^b − M^s − L^s + C^s + M^b`.
- Model (eq. 2, p. 6): **`ΔP_k = β_i OFI_k + ε_k`**; depth link (eq. 3, p. 6): **`β_i = c / AD_i^λ + ν_i`**, with `AD_i = (1/(2(N(T_i)−N(T_{i−1})−1))) Σ (q^B_n + q^A_n)`; stylised model ⇒ λ = 1, c = 1/2.
- Estimation (eqs. 4–6, pp. 8, 12): OLS per half-hour, `ΔP_k = α̂_i + β̂_i OFI_k + ε̂_k`; `log β̂_i = α̂_L − λ̂ log AD_i + ε`; then `β̂_i = α̂_M + ĉ/AD_i^{λ̂} + ε`.
- Variance decomposition (eq. 7, p. 14): `var[ΔP_k]_i = β_i² var[OFI_k]_i + var[ε_k]_i`.
- Trade-imbalance comparison (eqs. 8a–c, p. 16); scaling result (Prop. 1, eq. 9, p. 19): `(√(μπ)/σ)·OFI(T)/√VOL(T) ⇒ N(0,1)`, hence a *spurious* square-root price–volume relation (eq. 14, p. 19): `ΔP_k = θ_k √VOL_k + ε_k` with random θ_k.

**Contemporaneity (explicit in the paper).** The regression is of ΔP_k on OFI_k *over the same interval*; the model is described as "a model of the instantaneous price impact over a short time interval" (p. 7). Footnote 3 (p. 8): OFI_k "includes the contributions of price-changing order book events, leading to a possible tautology"; excluding those events "the R² declined, but remained in the 35%-60% region". Autocorrelations of OFI at 10 s "are small and quickly vanish" (Figure 1, p. 7) — i.e. lagged OFI is not offered as a predictor anywhere in the paper.

**Reported numbers (paper result).**
- Table 2 (p. 11): average R² = 65 % across 50 stocks (range 35 % CME … 79 % BAC); β̂ significant at 5 % in 97 % of the 273 half-hour subsamples; intercept significant in 6 %; adding a quadratic term OFI|OFI| raises R² only 65 % → 68 % and is insignificant in most samples (p. 9). Example β̂: BAC 0.0002 ticks/share, SLB 0.0198, CME 0.6262.
- Table 3 (p. 13): λ̂ grand mean 0.98 (CI 0.88–1.08); H0: λ = 1 not rejected for 35/50 stocks; ĉ typically 0.13–0.5 (grand mean 0.45 including outliers WIN 5.81, CME 1.27), i.e. "generally different from c = 1/2 … mid-prices are (on average) more resilient to the incoming orders than indicated by AD_i" (p. 12). Bad fits for APOL, AZO, CME (wide spreads, low depth).
- Intraday (Figure 5, p. 14): depth at the open is half its average, impact coefficient two times higher at the open than average and "five times higher at the market open compared to the market close".
- Table 4 (p. 17): OFI R² 65 % vs trade imbalance R² 32 %; with both regressors the TI coefficient is significant in only 31 % of subsamples and its t-stat falls by a factor of four (p. 16).
- Table 5 (p. 22): price–volume exponent Ĥ "generally below 1/2"; |OFI| dominates VOL^H in joint regression.

**Limitations.** Second-resolution TAQ, no order IDs, 10-s aggregation; contemporaneous only; L1 only in the main text (Appendix B3 multi-level extension found little gain — contradicted by paper 4); 1-cent tick US equities in April 2010; depth proxy AD is crude (authors say so, p. 12).

**Implications for our maker.**
- `[inference]` OFI/β is a *normaliser*, not an alpha: β_i ≈ c/AD_i means "one tick of expected mid move per ≈ 2·AD/…" shares of net flow. For our normalization red line (all parameters normalised), expressing flow thresholds in units of current depth (OFI/AD) is the paper-backed way to make a flow signal stationary across coins and hours (vs fixed bp thresholds, which the U8-v2 post-mortem blamed).
- `[inference]` With 2.2 ms data latency and ~1 ms order latency, whatever contemporaneous OFI we observe has already moved the mid by βOFI; our order to react arrives ≥ 3 ms later. The paper gives no evidence that OFI predicts the *next* interval at 10 s (ACF small). Any predictive use must be established at the ms–100 ms scale, which this paper does not test.
- `[inference]` The direct maker use is queue-depletion risk: OFI on our side over the last Δt tells us how fast the level we sit at is being consumed; combined with depth this is a "time-to-depletion" estimate. That is contemporaneous and legitimate.
- `[inference]` Mid-caps with 1–2 tick spreads resemble BAC/AMD (large-tick, R² 64–79 %); BTC at 0.01-bp tick resembles CME/AZO (small-tick, R² 35–47 %, bad depth fits). Expect the OFI model to work for mid-caps and poorly for BTC.
- `[inference]` The square-root "volume moves prices" relation is a statistical artefact per Prop. 1; do not build volume-based signals when OFI is available.

### Card — Cont, Kukanov, Stoikov
- **Strategy hypothesis (what is the edge?)** Net L1 order flow (not trades) drives contemporaneous mid changes linearly; slope ∝ 1/depth.
- **Economic mechanism (why should this edge exist?)** Mechanical queue depletion/replenishment at the best quotes; depth sets the price response per unit flow.
- **Required data (L1 / L2 / L3 / trades / order events)** L1 (best bid/ask price and size, every update) is enough; trades optional. Tardis L2 increments suffice.
- **Holding horizon (1ms / 10ms / 100ms / …)** Contemporaneous over Δt = 10 s (robust from ~0.5 s to 10 min); no forecast horizon claimed.
- **Expected signal (what observable predicts the edge?)** OFI_k (contemporaneous) and depth AD_i (for scaling); intraday depth pattern.
- **Execution dependency (queue / latency / fill probability)** None in the paper; for a maker the relevant dependency is queue depletion speed at our level.
- **Failure modes (why might it disappear?)** Small-tick / wide-spread / thin books (CME, AZO, APOL: R² 35–47 %, depth fit fails); hidden liquidity; regression tautology with price-changing events (R² falls to 35–60 % when removed).
- **Evidence (paper + empirical result, with numbers)** 50 stocks, April 2010: R² 65 %, β significant in 97 % of samples; λ̂ ≈ 1 (35/50 not rejected); TI R² 32 % and driven out by OFI.
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)** Contract: 3 mid-cap USDT perps + BTC. Data: Tardis L2 (L1 slice) at 1 s and 100 ms grids, 5 train + 9 OOS days. Statistic 1 (replication): per-hour OLS of ΔP (ticks) on OFI; pass if median R² ≥ 0.5 for mid-caps and β̂·AD is stable (CV of β̂·AD across hours < 0.5). Statistic 2 (predictiveness, the actual question): regress ΔP over (t+3 ms, t+Δ] on OFI over (t−Δ, t] for Δ ∈ {100 ms, 1 s}; pass only if OOS R² > 0.02 and sign accuracy > 52 % against a shuffled-label placebo on all 9 OOS days. Expect Statistic 1 to pass and Statistic 2 to fail; if 2 passes, OFI becomes a candidate skew input.

---

## 3. Stoikov (2018), "The micro-price: a high-frequency estimator of future prices"

**Citation.** S. Stoikov, *Quantitative Finance* 18(12), 2018, 1959–1966, DOI 10.1080/14697688.2018.1489139. Read version: author's draft dated November 26, 2017 (SSRN 2970694), Cornell Financial Engineering Manhattan, 13 pp. Code/data at github.com/sstoikov/microprice (BAC and CVX March 2011 CSVs + notebook).

**Market / data / tick / fee context.** Bid/ask quotes for BAC and CVX, March 2011, "timestamp is rounded to the nearest second and each row has the bid price, ask price, bid size and ask size" (p. 8). BAC: "large tick stock", spread 1 tick most of the time; CVX: "small tick stock", wider spread distribution (Figure 2, p. 9). Level-I only by design (p. 2). No fees.

**Mechanism.** Define the fair price as the limit of expected future mid-prices conditional on the current (imbalance, spread) state; by construction it is a martingale. Estimate via a discrete-time Markov chain on (imbalance, spread) with mid-changes as absorbing events.

**Core formulas (verbatim).**
- Mid `M = (P^a + P^b)/2` (eq. 1, p. 2); weighted mid `W = I P^a + (1−I) P^b` (eq. 2) with imbalance **`I = Q^b/(Q^b + Q^a)`** (eq. 3).
- **Micro-price: `P^{micro} = M + g(I, S)`** (eq. 4, p. 3), `S = P^a − P^b`.
- General definition (p. 4): `P^i_t = E[M_{τ_i} | F_t]`, τ_i = times of the i-th mid change; **`P^{micro}_t = lim_{i→∞} P^i_t`**.
- Assumption 1: F_t generated by the 3-dim Markov process (M_t, I_t, S_t) (p. 4). Assumption 2: expected mid increments independent of the mid level (p. 5).
- Theorem 2.1 (eqs. 5–6, p. 5): `P^i_t = M_t + Σ_{k=1}^i g_k(I_t, S_t)`, `g_1(I,S) = E[M_{τ_1} − M_t | I_t = I, S_t = S]`, `g_{i+1}(I,S) = E[g_i(I_{τ_1}, S_{τ_1}) | I_t = I, S_t = S]`.
- Finite-state implementation (pp. 6–7): imbalance in n bins, spread in m tick-states, mid-changes K = (−0.01, −0.005, 0.005, 0.01)^T; `R^1_{xk} = P(M_{t+1}−M_t = k | X_t = x)`, `Q_{xy} = P(M_{t+1}−M_t = 0 ∧ X_{t+1} = y | X_t = x)`, `R^2_{xy} = P(M_{t+1}−M_t ≠ 0 ∧ X_{t+1} = y | X_t = x)`;
  **`G^1 = (1 − Q)^{−1} R^1 K`**, **`B = (1 − Q)^{−1} R^2`**, `P^i_t = M_t + Σ_{k=0}^i B^k G^1` (eq. 7 region, p. 7).
- Theorem 3.1 (p. 8): if `B* = lim B^k` and `B* G^1 = 0`, the limit converges and `P^{micro}_t = M_t + G^1 + Σ_{j=2}^{nm} (λ_j/(1−λ_j)) B_j G^1`.
- Estimation procedure (p. 9): symmetrise the data (each tuple (I_t,S_t,I_{t+1},S_{t+1},dM) paired with (1−I_t,S_t,1−I_{t+1},S_{t+1},−dM)) — "ensures that B* G^1 = 0"; estimate Q, R², R¹; compute G¹, B, and `G* = P^{micro} − M = G^1 + Σ_{i≥1} B^i G^1` ("In practice, this sum converges very fast").
- Appendix A: if I is independent of future moves, micro-price = mid. Appendix B: if I is a Brownian motion on [0,1] absorbed at the boundaries with the stated reset rule, `g_1 = I_t − 1/2` and all higher g_i = 0, so micro-price = weighted mid (pp. 12–13).

**Reported results (paper result; all qualitative/figures, no R² or bp numbers are reported).**
- Figure 3 (p. 10): for both BAC and CVX, G* lies "between the mid-price (a horizontal line) and the weighted mid-price"; "The micro-price adjustment is less than half a spread"; "as the spread widens, the slope of the micro-price as a function of imbalance lessens, i.e. imbalances are less informative."
- Figure 4 (BAC, p. 10): at 1-minute horizon the micro-price "is a better predictor of the weighted mid-price than the mid-price" (bid-ask bounce in the mid for large-tick stocks); at 5 minutes mid and weighted-mid predictions coincide but "error bars are now much larger".
- Figure 5 (CVX, p. 11): at 30 seconds "the micro-price provides a good prediction"; longer horizons "not useful" (error bars).
- Weighted-mid counter-example (p. 2): P^b = 10.00 (Q^b = 9), P^a = 10.02 (Q^a = 27) gives W = 10.005; a 1-lot sell at 10.01 moves W *up* to 10.009 — "The impact of a new sell order should surely be to update the 'fair' price downward."

**Limitations.** 1-second timestamps (no sub-second dynamics), 1 month, 2 stocks, Level-I only, discretisation choices (n, m) not reported in the text, no out-of-sample test, no statistical significance reported, horizon-independence makes validation "an inherent difficulty" (p. 10). `[inference]` Convergence relies on symmetrisation, which also erases any genuine buy/sell asymmetry.

**Implications for our maker.**
- `[inference]` Our mid-caps (spread 1–2 ticks, tick ≥ 1 bp) are the BAC regime: the whole game is whether the next mid move is up or down, and the paper says imbalance is most informative exactly when the spread is 1 tick. Centring quotes on P^{micro} rather than M is the cheapest, most defensible fair-value change; it needs only L1 and is a lookup table (nm states).
- `[inference]` Because G* < S/2, the micro-price never says "cross the spread"; for a maker it says which side of the touch to keep and which to pull. That maps directly to a pull/skew rule with a threshold in units of ticks — normalised by construction.
- `[inference]` Latency: our data is 2.2 ms old and the state (I, S) changes every few ms on liquid coins; the paper's 1-s data cannot tell us whether G* survives a 3 ms reaction delay. This must be measured (see Test).
- `[inference]` For BTC (tick 0.01 bp, spread many ticks) the paper's own Figure 3 says imbalance is far less informative when the spread is wide; expect small G*/S.

### Card — Stoikov micro-price
- **Strategy hypothesis (what is the edge?)** The martingale fair value conditional on (imbalance, spread) differs from the mid; quoting around it avoids adverse selection and captures the predictable next move.
- **Economic mechanism (why should this edge exist?)** Queue imbalance at the touch predicts which queue depletes first (large-tick); horizon-free by taking the limit of expected mids.
- **Required data (L1 / L2 / L3 / trades / order events)** L1 only (best prices and sizes). Tardis L2 suffices.
- **Holding horizon (1ms / 10ms / 100ms / …)** Paper validates at 30 s (CVX) and 1–5 min (BAC); the estimator itself is horizon-free.
- **Expected signal (what observable predicts the edge?)** `G*(I, S) = P^{micro} − M`, a table over imbalance × spread states; slope decreases with spread.
- **Execution dependency (queue / latency / fill probability)** For a maker: whether the signal survives our 2.2 ms + 1 ms delay and whether our queue position lets us be filled on the benign side before the move.
- **Failure modes (why might it disappear?)** Symmetrisation hides asymmetry; regime shifts change the table; wide spreads (BTC) → weak signal; the state changes faster than we can act.
- **Evidence (paper + empirical result, with numbers)** BAC/CVX March 2011: G* between mid and weighted mid, < S/2, visually matches 30 s–1 min realized moves (Figures 3–5). No numbers.
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)** Contract: 3 mid-caps (ETH/SOL/XRP USDT perps) + BTC. Data: Tardis L2 L1 slice at event resolution; imbalance in 10 bins, spread in {1,2,3+} ticks. Fit G* on 5 September training days with symmetrisation; on the 9 OOS days compute realized `M_{t+h} − M_t` for h ∈ {5 ms, 50 ms, 500 ms, 5 s} conditional on state. Pass if (a) OOS Spearman correlation between G*(state) and mean realized move ≥ 0.8 at h = 500 ms and 5 s, (b) the correlation at h = 5 ms *measured from t + 3.2 ms* (our delay) is still ≥ 0.5, (c) a shuffled-state placebo gives < 0.2. Then run the quoting rule "pull the side that G* moves against when |G*| > 0.25 tick" and require markout improvement ≥ 0.2 bp per fill OOS with fees.

---

## 4. Xu, Gould, Howison (2019), "Multi-level order-flow imbalance in a limit order book"

**Citation.** K. Xu, M. D. Gould, S. D. Howison, Mathematical Institute, University of Oxford; arXiv:1907.06230v2, 26 Oct 2019 (dated Oct 29, 2019), 32 pp.

**Market / data / tick / fee context.** LOBSTER (Nasdaq, nanosecond timestamps, full order-event data), calendar year 2016, 6 stocks: AMZN, TSLA, NFLX (small-tick) and ORCL, CSCO, MU (large-tick); tick [amount removed], lot 1 share (p. 10). Mean spread ranges "about 37 ticks for AMZN to about 1 tick for MU" (p. 13). For large-tick stocks "the majority of order-flow activity" is at the best quotes; for small-tick "more than half of all order flow occurs beyond the level-1 bid- and ask-prices" (Table 2, p. 13). Windows ΔT = 30 min, Δt = 10 s; 252 × 11 = 2772 regressions per stock (p. 13). Hidden liquidity excluded from flow (p. 10). No fees.

**Mechanism.** Extend OFI to a vector over the first M populated levels per side; the contemporaneous mid change is regressed on the vector. Because level flows are strongly correlated, OLS is unstable; ridge regression with CV-chosen penalty gives stable, significant coefficients at all levels and lower out-of-sample RMSE.

**Core formulas (verbatim).**
- OFI event (eqs. 2–5, pp. 6): `e_n = ΔW(τ_n) − ΔV(τ_n)`, `ΔW = r_1(τ_n)` if `b_1↑`, `r_1(τ_n) − r_1(τ_{n−1})` if `b_1 =`, `−r_1(τ_{n−1})` if `b_1↓`; ΔV symmetric on the ask; `OFI(t_{k−1}, t_k) = Σ e_n`.
- MLOFI (eq. 9 ff., p. 8): same rule applied at the level-m populated price on each side: `ΔW^m(τ_n)` and `ΔV^m(τ_n)`; `MLOFI_m(t_{k−1},t_k) = Σ [ΔW^m − ΔV^m]`. (Only populated levels are counted, so level m+1 need not be one tick from level m, footnote 3, p. 8.)
- Regression (eq. 16, p. 15): **`ΔP(t_{i,k−1}, t_{i,k}) = α + Σ_{m=1}^M β_m MLOFI_m(t_{i,k−1}, t_{i,k}) + ε`**, M = 10.
- Ridge (eq. 18, p. 18): **`C(β, λ) = ||y − Xβ||²₂ + λ||β||²₂`**, λ chosen by 5-fold CV over 50 log-spaced values in [10⁻⁵, 10⁵] (p. 19).

**Reported numbers (paper result).**
- OFI OLS (Table 3, p. 14): β̂ (ticks per share): AMZN 11.00, TSLA 5.82, NFLX 3.11, ORCL 0.63, CSCO 0.49, MU 0.56; α ≈ 0; β significant in essentially all samples.
- MLOFI OLS: level coefficients "relatively weak" p-values (Table 6, p. 15–16); level-1 significance "much less strong" than in the univariate fit — attributed to multicollinearity.
- Collinearity (Figure 1, p. 17): correlations between MLOFI components "above 0.7 for all pairs" for large-tick stocks; > 0.5 even between levels 1 and 10 for small-tick; eigenvalue ratios λ_i/λ_1 ≈ 0 for i ≥ 2 (Figure 2).
- Ridge λ̂ (Table 7, p. 19): AMZN 139.0, TSLA 54.3, NFLX 33.9, ORCL 3.2, CSCO 1.3, MU 2.0.
- Ridge coefficients (Table 8, p. 20): AMZN β_1…β_10 = 2.17, 1.99, 1.85, 1.44, 1.21, 1.09, 1.01, 0.92, 0.89, 1.01 (decreasing); MU = 0.04, 0.04, 0.06, 0.08, 0.08, 0.09, 0.08, 0.08, 0.07, 0.07 (flat/slightly increasing). Table 9: ridge coefficients significant in 63–98 % of samples.
- Adjusted R² at M = 10 (p. 23): AMZN/TSLA ≈ 0.65 (OLS) / 0.6 (ridge); NFLX ≈ 0.9 / 0.85; ORCL/CSCO/MU "very close to 1"; M = 1 values in the 0.35–0.8 range as in Cont et al.
- Out-of-sample RMSE (Table 10, p. 26; ticks): OFI 9.72 / 5.35 / 2.03 / 0.25 / 0.19 / 0.22 (AMZN…MU); MLOFI ridge 8.05 / 4.53 / 1.41 / 0.08 / 0.05 / 0.08. **Improvement of ridge MLOFI over OFI: 17 % / 15 % / 31 % / 68 % / 74 % / 64 %**; OLS MLOFI: 12 / 7 / 27 / 64 / 68 / 59 %. OLS over-fits for AMZN and TSLA beyond M ≈ 5 (out-of-sample RMSE rises, p. 24).
- Intraday: β_1 smaller later in the day for CSCO and MU; negligible elsewhere (p. 13).

**Limitations (paper).** Same contemporaneous design as Cont et al.; Nasdaq only (misses other venues); for small-tick stocks the same MLOFI vector maps to different outputs (orders inside the spread at different depths), which "may reduce the predictive power" (pp. 27–28); economic significance argued, not demonstrated with a strategy (p. 28).

**Implications for our maker.**
- `[inference]` Tardis L2 increments give populated-level sizes, so MLOFI is computable without order IDs; hidden orders do not exist on KuCoin perps, so one source of noise in the paper is absent.
- `[inference]` Mid-caps (1–2 tick spreads) are the MU/CSCO regime where ridge MLOFI cuts contemporaneous RMSE by ~2/3 and explains nearly all variance — meaning that on mid-caps a mid move is almost entirely "read off" the book's flow. That is a statement about *explaining*, not forecasting; for a maker it means deeper-level flow (levels 2–5) is a legitimate early-warning input for pulling touch quotes, since flow deep in the book precedes best-queue depletion mechanically (their Section 6.3 gives exactly this mechanism).
- `[inference]` BTC (spread ≫ 1 tick) is the AMZN regime: MLOFI gains are modest (15–17 %) and OLS over-fits; use ridge or fewer levels.
- `[inference]` Ridge with CV-chosen λ is the paper's own remedy for collinearity; any multi-level flow feature we fit must be regularised, and coefficients must not be interpreted level-by-level under OLS.

### Card — Xu, Gould, Howison
- **Strategy hypothesis (what is the edge?)** Net flow at deeper levels adds explanatory power for the contemporaneous mid move beyond L1 OFI, especially in large-tick books.
- **Economic mechanism (why should this edge exist?)** (i) Informed traders hide intent as deep limit orders (information leakage), (ii) cancellations behind the best quote enlarge the size of a mid move when the best queue empties.
- **Required data (L1 / L2 / L3 / trades / order events)** L2 (populated level sizes per side, ≥ 5–10 levels) per event; no order IDs. Tardis L2 increments suffice.
- **Holding horizon (1ms / 10ms / 100ms / …)** Contemporaneous over 10 s (robust 5–40 s); no forecast claim.
- **Expected signal (what observable predicts the edge?)** MLOFI vector (M = 10), fitted with ridge; for large-tick books coefficients are flat across levels.
- **Execution dependency (queue / latency / fill probability)** For a maker: deep-level outflow precedes best-queue depletion; the usable lead time is the (unmeasured) delay between deep cancels and touch depletion minus our 3.2 ms.
- **Failure modes (why might it disappear?)** Multicollinearity (OLS unstable/over-fit); small-tick ambiguity (same vector, different outputs); regime drift of λ; Nasdaq-only flow.
- **Evidence (paper + empirical result, with numbers)** 6 Nasdaq stocks, 2016: ridge MLOFI OOS RMSE −64…−74 % (large-tick), −15…−31 % (small-tick) vs OFI; adjusted R² ≈ 1 for large-tick at M = 10.
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)** Contract: same 3 mid-caps + BTC. Data: Tardis L2, 10 levels, Δt = 1 s and 100 ms. Replication statistic: ridge (5-fold CV λ) OOS RMSE of MLOFI(M=10) vs OFI; pass if reduction ≥ 40 % on mid-caps (large-tick) and ≥ 10 % on BTC. Predictive statistic: does MLOFI over (t−Δ, t] predict *depletion of our touch level* within (t+3.2 ms, t+Δ]? Logistic model; pass if OOS AUC ≥ 0.65 vs 0.5 for shuffled labels on all 9 OOS days. Only the second statistic can justify a live pull rule.

---

## 5. Cartea, Jaimungal, Ricci (2014), "Buy low, sell high: a high frequency trading perspective"

**Citation.** Á. Cartea, S. Jaimungal, J. Ricci, *SIAM Journal on Financial Mathematics* 5(1), 2014, 415–444 (SIGEST reprint in SIAM Review 2018). Read version: preprint dated May 29, 2012 (UCL / U. Toronto), 36 pp. The final SIAM text was not open; numbers below are from the preprint and may differ slightly from the journal version.

**Market / data / tick / fee context.** Theory + simulation. Empirical illustrations only: NASDAQ IBM LOB snapshot 21 June 2011 (Figure 1, p. 6) and IBM market-order intensities over 3 minutes on 1 Feb 2008 (Figure 2, p. 8; activity "revert[s] to around 5 events per second"). No fees in the model except a terminal liquidation cost of 1 bp or 10 bp per share (p. 20); rebates mentioned only in footnote 4 (p. 5). Simulation: 5-minute horizon, 5000 paths, starting mid [amount removed], exponential fill probabilities (p. 20).

**Mechanism.** Market orders arrive with self-exciting (Hawkes-like) intensities; a fraction ρ of them are "influential" and (i) raise both buy and sell intensities (more on their own side), (ii) temporarily change the fill-probability shape κ of the book, (iii) push the short-term drift α of the mid (buys up, sells down). A maker solving the HJB with a running inventory penalty posts half-spreads = risk-neutral term + alpha/adverse-selection term + inventory term. Makers that ignore α are adversely selected and lose.

**Core formulas (verbatim).**
- Mid (eq. 1, p. 6): **`dS_t = (υ + α_t) dt + σ dW_t`**, υ set to 0.
- Intensities (eq. 2, p. 9): **`dλ⁻_t = β(θ − λ⁻_t)dt + η dM̄⁻_t + ν dM̄⁺_t + η̃ dZ⁻_t + ν̃ dZ⁺_t`**, `dλ⁺_t = β(θ − λ⁺_t)dt + η dM̄⁺_t + ν dM̄⁻_t + η̃ dZ⁺_t + ν̃ dZ⁻_t`, with `β > ρ(η + ν)` (ergodicity, Lemma 1, p. 10); typically ν < η.
- Fill rates (Assumption 2, p. 10): **`Λ±_t = λ±_t h±(δ; κ_t)`**, h non-increasing, `h = 1 for δ ≤ 0`; examples `e^{−κδ}` and `(1 + (κδ)^a)^{−1}` (p. 11). κ dynamics (eq. 3, p. 11) mirror eq. 2 with (β_κ, θ_κ, η_κ, ν_κ).
- Short-term alpha (eq. 4, p. 13): **`dα_t = −ζ α_t dt + σ_α dB_t + ε⁺ dM̄⁺_t − ε⁻ dM̄⁻_t + ε̃⁺ dZ⁺_t − ε̃⁻ dZ⁻_t`**.
- Cash (eq. 5, p. 14): `dX_t = (S_t + δ⁺_{t−}) dN⁺_t − (S_t − δ⁻_{t−}) dN⁻_t`; value function (eq. 6, p. 14): **`Φ = sup E[X_T + q_T S_T − φ ∫_t^T q_s² ds | F_t]`**.
- HJB (eq. 7, p. 15) with generator L (eq. 8) and shift operators (eqs. 9a–h).
- Feedback control (Prop. 2, eqs. 11–13, p. 16): **`δ±* = δ±_0 + α δ±_α + ε δ±_ε + φ δ±_φ + o(ς)`**, `B(δ_0; κ) = h′/(2h′ + δ_0 h″)`, and the risk-neutral half-spread solves **`δ±_0 h′±(δ±_0; κ) + h±(δ±_0; κ) = 0`** (eq. 13) — "λ± plays no role in how the limit orders are calculated" (p. 17); for exponential h this gives δ_0 = 1/κ `[inference from eq. 13]`.
- Corollary 4 (eq. 16, p. 18): **`δ±* = δ±_0 + B(δ±_0; κ±) [ ±S±_λ( E[∫_t^T α_u du] ) + φ( ±S±_λ b_φ + (1 ∓ 2q)(T − t) ) ]`**.
- Simplified case (eqs. 17a–b, p. 19): `E[∫_t^T α_u du] = (ερ/ζ)(λ⁺_t − λ⁻_t){(1 − e^{−β̂(T−t)})/β̂ − (e^{−ζ(T−t)} − e^{−β̂(T−t)})/(β̂ − ζ)} + α_t (1 − e^{−ζ(T−t)})/ζ`, `b_φ = 2h(λ⁺_t − λ⁻_t){(T−t)/β̂ − (1 − e^{−β̂(T−t)})/β̂²}`, `β̂ = β − ρ(ν − η)`. Both terms are proportional to **`λ⁺_t − λ⁻_t`**, the buy–sell intensity imbalance.

**Reported numbers (paper result; simulation, PnL in $ per 5-minute run, mean (std), 5000 paths).** Parameters: β = 60, θ = 1, η = 40, ν = 10, β_κ = 10, θ_κ = 50, η_κ = 10, ν_κ = 25, σ = 0.01, ζ = 2, σ_α = 0.01, ρ = 0.7, ε± exponential with mean ε (p. 21).

| Case | φ | Bench (correct ρ, α) | ρ = 1 | ρ = 0 | Bench, α ≡ 0 | ρ = 1, α ≡ 0 | ρ = 0, α ≡ 0 |
|---|---|---|---|---|---|---|---|
| ε = 0.04, 1 bp (Table 1) | 1e-5 | 14.16 (6.84) | 12.97 (7.31) | 9.96 (5.88) | −3.82 (2.85) | −3.86 (2.85) | −4.35 (2.99) |
| | 2e-5 | 13.42 (5.35) | 12.36 (5.64) | 9.68 (4.75) | −1.68 (2.09) | −1.79 (2.08) | −2.82 (2.19) |
| | 4e-5 | 12.27 (4.23) | 11.34 (4.41) | 9.19 (3.86) | 0.07 (1.50) | −0.06 (1.49) | −1.27 (1.60) |
| ε = 0.04, 10 bp | 1e-5 | 13.39 (6.68) | 12.18 (7.16) | 9.25 (5.80) | −4.32 (3.01) | −4.35 (3.00) | −4.84 (3.14) |
| ε = 0.02, 1 bp (Table 2) | 1e-5 | 8.79 (2.81) | 8.18 (2.92) | 7.30 (2.58) | 1.65 (1.47) | 1.61 (1.47) | 1.21 (1.54) |
| | 4e-5 | 7.27 (1.71) | 6.82 (1.77) | 6.39 (1.62) | 3.00 (0.81) | 2.93 (0.80) | 2.28 (0.85) |
| ε = 0.04, ρ = 0.3, 1 bp (Table 3) | 1e-5 | 4.89 (1.39) | 3.65 (1.41) | 3.79 (1.33) | 2.61 (1.24) | 2.63 (1.24) | 2.59 (1.25) |

Authors' conclusions: "HFTs who are not able to execute market making strategies based on predictable trends in the midprice will be driven out of the market" when ε = 0.04 (p. 25); when ε = 0.02 "HFTs are able to subsist even if they do not use predictors of short-term-alpha" (p. 26). For no-alpha makers, raising φ *increases* mean PnL because "the limit orders are posted deeper in the LOB and this makes it more difficult for other traders to pick off their quotes" (p. 26); for alpha-using makers, raising φ lowers both mean and std.

**Limitations.** No empirical estimation of ε, ρ, ζ (calibration only illustrated for intensities); fill model is a smooth h(δ) with no queue; quotes are one unit, repriced continuously; no fees/rebates/ticks; PnL scale ($ per 5 min at [amount removed]) is not comparable to bp; the paper's "alpha" is by construction the true data-generating drift (the benchmark knows the model).

**Implications for our maker.**
- `[inference]` This is the paper that states our situation most directly: a rebate-funded maker that quotes without a short-term-alpha estimate is the "α ≡ 0" row. Whether it is the ε = 0.04 (loss) or ε = 0.02 (survive) world is an empirical number on KuCoin: the mean jump in the short-term drift after an influential trade, relative to half-spread + OUR_FEE.
- `[inference]` The alpha term in eq. (17a) is proportional to (λ⁺ − λ⁻): a Hawkes-intensity imbalance estimated from *trades only* (we have aggressor side) is the paper's signal. It is causal (uses past trades) — unlike papers 2 and 4 — so it is directly testable as a predictor with our latency.
- `[inference]` The φ result gives a fallback: if no alpha survives our latency, posting deeper (higher φ) reduces pick-off; but on mid-caps "deeper" means the second tick, which on a 1-tick-spread book means not quoting at the touch at all — and then volume collapses, conflicting with the [amount removed]/3-month target. On BTC (0.01-bp tick) "deeper" is continuous and usable.
- `[inference]` The ρ = 1 vs ρ = 0 comparison says over-reacting to every trade (ρ = 1) costs less than ignoring trades (ρ = 0) when alpha is used (12.97 vs 9.96); i.e., a crude "every trade moves alpha" model retains most of the benefit.

### Card — Cartea, Jaimungal, Ricci
- **Strategy hypothesis (what is the edge?)** Makers profit only if they quote around a short-term-alpha estimate driven by clustered, one-sided market-order flow; otherwise they are picked off.
- **Economic mechanism (why should this edge exist?)** Self-exciting one-sided trade clusters carry information (Easley–O'Hara sense) and temporarily shift the mid drift; makers who see the cluster early skew (adverse-selection buffer + directional first leg).
- **Required data (L1 / L2 / L3 / trades / order events)** Trades with aggressor side (for λ±, α jumps) + L1/L2 for fill-shape κ. Tardis trades suffice for the signal; no L3.
- **Holding horizon (1ms / 10ms / 100ms / …)** Alpha mean-reverts at rate ζ = 2 (half-life ≈ 0.35 s in their units) and intensities at β = 60; effective horizon sub-second to seconds.
- **Expected signal (what observable predicts the edge?)** `λ⁺_t − λ⁻_t` (Hawkes buy–sell intensity imbalance) and the filtered drift α_t; sign predicts next mid move.
- **Execution dependency (queue / latency / fill probability)** Fill probability h(δ; κ) and the ability to cancel/re-post within the alpha half-life; the paper itself says latency decides who provides "liquidity at a loss due to their orders arriving 'too late'" (p. 20).
- **Failure modes (why might it disappear?)** Alpha too small relative to costs (ε = 0.02 world: nobody needs it); mis-estimated ρ/ζ; our 3.2 ms delay eats the front of the cluster; on 1-tick books there is no "deeper" to post.
- **Evidence (paper + empirical result, with numbers)** Simulation: with ε = 0.04, alpha-users +14.16 vs non-users −3.82 (φ = 1e-5); with ε = 0.02 non-users still +1.65.
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)** Contract: 3 mid-caps + BTC. Data: Tardis trades (side, size, time) + L1. Step 1: fit a bivariate exponential-kernel Hawkes (β, η, ν, θ) per coin per day on training days; check β > ρ(η+ν) and report branching ratio. Step 2 (the falsifiable one): regress the mid change over (t+3.2 ms, t+h] on (λ̂⁺_t − λ̂⁻_t) for h ∈ {100 ms, 1 s, 10 s}; pass if OOS R² ≥ 0.01 and sign accuracy ≥ 53 % on ≥ 7 of 9 OOS days against a time-shuffled placebo. Step 3: measure ε empirically as the mean 1-s markout after trades classified as "influential" (trade followed by ≥ 2 same-side trades within 100 ms) minus that after other trades; compare to (half-spread + OUR_FEE). If ε_hat > half-spread + OUR_FEE on mid-caps, the "driven out" regime holds and touch-quoting without alpha fails by construction.

---

## 6. Easley, López de Prado, O'Hara (2012), "Flow toxicity and liquidity in a high-frequency world" (VPIN)

**Citation.** D. Easley, M. M. López de Prado, M. O'Hara, *Review of Financial Studies* 25(5), 2012, 1457–1493. Read version: working paper hosted by NYU Stern (SSRN 1695596 lineage), 71 pp with tables/figures. Note: "VPIN is a trademark of Tudor Investment Corp. The authors have applied for a patent on VPIN" (title-page footnote).

**Market / data / tick / fee context.** E-mini S&P 500 futures (CME) and WTI crude (NYMEX), 1-minute bars, Jan 1 2008 – Aug 15 2011 (p. 21); most-active expiry rolled forward. No order-book data; trades only, with bulk volume classification (BVC) because "in a high frequency setting, trade classification is much more difficult" (p. 15); May 2010 E-mini: 2,650,391 quote changes from adds/cancels vs 789,676 from trades per average day (p. 15). No fees.

**Mechanism.** In the PIN model, informed traders arrive at rate μ on information days (probability α), uninformed at rate ε per side; the maker's spread is the expected loss to informed traders. VPIN replaces MLE with a direct estimator: sample in volume time (equal-volume buckets), sign volume probabilistically from price changes, and set toxicity = mean absolute buy–sell imbalance per bucket / bucket volume over a rolling window of n buckets. High VPIN → makers withdraw → volatility.

**Core formulas (verbatim).**
- Expected value (eq. 1, p. 9): `E[S_i|t] = P_n(t) S*_i + P_b(t) S̲_i + P_g(t) S̄_i`.
- Bid / ask (eqs. 2–3, p. 10): `B(t) = E[S_i|t] − μP_b(t)/(ε + μP_b(t)) · (E[S_i|t] − S̲_i)`, `A(t) = E[S_i|t] + μP_g(t)/(ε + μP_g(t)) · (S̄_i − E[S_i|t])`.
- Spread (eq. 4) and, with δ = 1/2, **`Σ = αμ/(αμ + 2ε) · (S̄_i − S̲_i)`** (eq. 5, p. 10).
- **`PIN = αμ/(αμ + 2ε)`** (eq. 6, p. 11) — "the key determinant of spreads".
- Bulk volume classification (eq. 7, p. 16): **`V^B_τ = Σ_{i=t(τ−1)+1}^{t(τ)} V_i · Z((P_i − P_{i−1})/σ_ΔP)`**, `V^S_τ = V − V^B_τ`, Z = standard normal CDF, σ_ΔP = std of bar-to-bar price changes; volume in a bar with no price change is split 50/50.
- Order imbalance `OI_τ = |V^B_τ − V^S_τ|` (p. 17); scale invariance (eq. 8).
- **`VPIN = αμ/(αμ + 2ε) ≈ Σ_{τ=1}^n |V^S_τ − V^B_τ| / (nV)`** (eq. 9, p. 19), using `E|V^S − V^B| ≈ αμ` and `E[V^S + V^B] = αμ + 2ε` from Easley–Engle–O'Hara–Wu (2008).
- Bucket construction (p. 14): "group sequential trades into equal volume buckets of an exogenously defined size V … If the last trade needed to complete a bucket is for a size greater than required, the excess size is given to the next bucket"; each reported trade treated as unit-size trades (p. 18). Default V = 1/50 of average daily volume, n = 50 (≈ one day); rolling update per bucket (p. 19).
- Persistence statistic (eq. 10, p. 34): max |P_l/P_m − 1| over bucket pairs while VPIN stays in one 5 %-tile.

**Reported numbers (paper result).**
- Table 2 (E-mini, 44,665 obs): mean VPIN 0.2251, std 0.0576, AR(1) 0.9958; WTI mean 0.2191, AR(1) 0.9932.
- Flash crash (p. 22, Figure 4): "The three methods concur in signaling an extreme level for the VPIN flow toxicity metric at least two hours before the crash (see the CDF(VPIN) dashed line crossing the 0.9 threshold)"; VPIN reached its sample maximum on May 6 2010 (p. 25). March 14 2011 (Fukushima): CDF(VPIN) at 0.97 by 3 pm during a light-volume night session (p. 26). WTI May 5 2011: CDF(VPIN) > 0.9 from 9:53 am, WTI lost > 8 % (p. 27).
- Robustness: 1,000 alternative start points → cross-sectional std of VPIN ≈ 0.015 vs level ≈ 0.23 (p. 23); CDF before/after the crash "nearly identical" (Table 3, p. 25).
- Predictive: correlation ρ(ln VPIN_{τ−1}, |P_τ/P_{τ−1} − 1|) = **0.400** on 44,537 observations for the (50 buckets/day, 250-bucket window) setting (p. 29). Bottom-quartile VPIN → next-bucket |return| in 0–0.25 % "more than 90% of time" (p. 31). Upper quartile of VPIN "contains over 84% of all absolute returns greater than 0.75%" (p. 31); probability VPIN was in the upper quartile one bucket before a ≥ 0.75 % move is 80–90 % across parameter choices (Figure 12). Persistence: for (50,250), 51.84 % of entries into an upper-quartile 5 %-tile see an intermediate |return| > 0.75 % before leaving it; for (10,350) 78.57 % (Table 5, p. 35).
- Counter-example acknowledged (p. 32): Nymex natural gas 8 June 2011 8.1 % drop and recovery at low VPIN — "Not all volatility is due to toxicity."

**Limitations (from the paper).** BVC "will misclassify some volume" (p. 17); VPIN is a rolling average with AR(1) ≈ 0.996; conditional results are unconditional on volatility; correlation "is a narrow criterion" (p. 29); relevance is argued for makers "who must wait for the order flow to come to them" (p. 27).

**Known critiques — `[not verified]`: full texts not obtained.** From the literature as I recall it (unverified here): Andersen & Bondarenko (2014, *J. Financial Markets*, "VPIN and the Flash Crash") argue that VPIN's predictive content is driven by the trade-classification and bucket construction, that VPIN did not reach unusual levels before the crash when computed with actual trade signs, and that it is dominated by simple volume/volatility measures; Easley et al. replied in the same journal. Treat as hypotheses to check, not as findings of this report.

**Implications for our maker.**
- `[inference]` We have aggressor side on every Tardis trade, so we can compute the *actual* signed imbalance per volume bucket — the central objection to VPIN (BVC signing) does not apply; what remains is the question whether volume-bucket toxicity predicts maker losses beyond what realised volatility already predicts.
- `[inference]` The flash-crash lead time of hours is far from our ms decisions; the relevant use is a regime gate: reduce size or widen when CDF(VPIN) is high, exactly as the authors suggest ("real-time risk management tool", p. 5). This is cheap and does not require alpha.
- `[inference]` The PIN spread formula Σ = PIN·(S̄ − S̲) is the same statement as Glosten–Milgrom (paper 7b): the spread the maker needs equals the informed share of flow times the information size. With a OUR_FEE rebate the maker can quote at a spread OUR_FEE narrower than PIN·ΔS; on a 1-tick book that is a binary "quote or not" decision, driven by PIN.

### Card — VPIN
- **Strategy hypothesis (what is the edge?)** Toxicity (share of informed, one-sided volume) is measurable in volume time and predicts maker losses/volatility; gate quoting on it.
- **Economic mechanism (why should this edge exist?)** Adverse selection: informed flow is one-sided; makers hit by it withdraw, liquidity thins, volatility rises.
- **Required data (L1 / L2 / L3 / trades / order events)** Trades with size (and side, if available; BVC otherwise). No book data needed.
- **Holding horizon (1ms / 10ms / 100ms / …)** One volume bucket (paper: 1/50 of a day) to hours; regime scale.
- **Expected signal (what observable predicts the edge?)** VPIN / CDF(VPIN) percentile; persistence in the upper quartile.
- **Execution dependency (queue / latency / fill probability)** None; it is a gate, not a quote.
- **Failure modes (why might it disappear?)** Signal dominated by volume/volatility; classification noise; slow (AR(1) ≈ 0.996) so it lags fast events; false positives cost volume.
- **Evidence (paper + empirical result, with numbers)** E-mini 2008–2011: ρ = 0.40 with next-bucket |return|; upper quartile precedes 84 % of |returns| > 0.75 %; extreme reading ≥ 2 h before the 2010 flash crash.
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)** Contract: BTC and 3 mid-caps. Data: Tardis trades (with side). Buckets V = ADV/50, n = 50, computed with true signs *and* with BVC. Statistic 1: Spearman ρ(VPIN_{τ−1}, |r_τ|) OOS; pass if ≥ 0.25 and, crucially, still ≥ 0.10 after partialling out trailing realised volatility (else it is just volatility). Statistic 2 (maker-relevant): fee-inclusive markout PnL of touch fills in a queue-modelled backtest, split by VPIN quartile; pass if top-quartile markout is worse than bottom-quartile by ≥ 0.3 bp per fill on ≥ 7 of 9 OOS days and the gate "no quotes when CDF(VPIN) > 0.9" raises net PnL without cutting volume by more than 15 %.

---

## 7. Classics

### 7a. Ho & Stoll (1981), "Optimal dealer pricing under transactions and return uncertainty"

**Citation.** T. Ho, H. R. Stoll, *Journal of Financial Economics* 9(1), March 1981, 47–73 (DOI 10.1016/0304-405X(81)90020-9).

**Full text NOT obtained.** No open copy exists on author pages, arXiv, CORE, Semantic Scholar (status CLOSED) or Unpaywall; only Elsevier/SSRN paywalled copies. Per the brief, no abstract-based claims are made. What can be said from the full texts read here (secondary, attributed):
- Avellaneda & Stoikov (2008, p. 217): the model "analyses the optimal prices for a monopolistic dealer in a single stock. In their model, the authors specify a 'true' price for the asset, and derive optimal bid and ask quotes around this price, to account for the effect of the inventory"; and (p. 220) "This type of optimal dealer problem was first studied by Ho and Stoll (1981). One of the key steps in their analysis is to use the dynamic programming principle to show that the function u solves the following Hamilton–Jacobi–Bellman equation" (the HJB reproduced in Section 1 above).
- Cartea–Jaimungal–Ricci (2012 preprint, p. 3): "Early work on optimal postings by a securities dealer is that of Ho and Stoll (1981)."
- `[inference]` Everything in Section 1 (reservation price linear in inventory, spread independent of inventory to first order) is the Avellaneda–Stoikov re-derivation of the Ho–Stoll structure; the implication for a rebate-funded maker is therefore the same as Section 1's: inventory skew is a variance tool, not an edge. A verbatim Ho–Stoll formula cannot be quoted here.

### Card — Ho & Stoll (full text not obtained; card limited to what papers 1 and 5 state about it)
- **Strategy hypothesis (what is the edge?)** Not assessable from the original. Per Avellaneda–Stoikov's description: a monopolistic dealer quotes around a 'true' price with an inventory adjustment — spread capture, no directional edge.
- **Economic mechanism (why should this edge exist?)** Compensation for bearing inventory (return) risk and transaction-timing uncertainty (secondary description only).
- **Required data (L1 / L2 / L3 / trades / order events)** L1 + own fills/inventory (as in Card 1).
- **Holding horizon (1ms / 10ms / 100ms / …)** Not stated in any text read; dealer horizon (finite T) per Avellaneda–Stoikov's account.
- **Expected signal (what observable predicts the edge?)** None; inventory is the only state.
- **Execution dependency (queue / latency / fill probability)** Fill arrival rates as a function of quotes (the HJB structure reproduced in Section 1).
- **Failure modes (why might it disappear?)** Same as Card 1: adverse selection is outside the model.
- **Evidence (paper + empirical result, with numbers)** None quoted — original not read. Avellaneda–Stoikov cite Ho & Macris (1984) as finding the inventory effect "significant in an empirical study of AMEX Options" (their p. 217; that paper was also not read).
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)** No separate test; covered by the Avellaneda–Stoikov test (symmetric vs inventory-skewed quoting, pass if P&L std falls ≥ 30 % at ≤ 10 % mean cost on the 9 OOS days).

### 7b. Glosten & Milgrom (1985), "Bid, ask and transaction prices in a specialist market with heterogeneously informed traders"

**Citation.** L. R. Glosten, P. R. Milgrom, *Journal of Financial Economics* 14(1), March 1985, 71–100.

**Context.** Pure theory; a competitive risk-neutral specialist facing sequential, anonymous arrivals of informed and liquidity traders; zero expected profit per trade, no inventory or order-processing costs (p. 72–73). No fees, no tick.

**Mechanism.** The specialist's ask is what he will believe the asset is worth *if* the next trader buys; the bid is what he will believe if the next trader sells. Because buying is more likely when the trader knows good news, ask > E[V] > bid: the spread exists purely as an adverse-selection premium.

**The one formula.** Zero-profit (reservation) quotes, Proposition 1 (p. 81): **`A_t = E[V | S_t, Z_t > A_t]`, `B_t = E[V | S_t, Z_t < B_t]`**, hence `A_t ≥ E_t[V] ≥ B_t`, strict "if adverse selection is possible". Equivalently (eq. 4′, p. 80, when the specialist knows only public information H_t): `A_t = inf{a : a ≥ E[V | H_t, Z_t > a]}`, `B_t = sup{b : b ≤ E[V | H_t, Z_t < b]}`. Here `Z_t = ρ_t E[V | F_t]` is the arriving trader's reservation value (eq. 1, p. 78), buy if Z_t > A, sell if Z_t < B.

**Other results.** Proposition 2 (p. 82): transaction prices `p_k = E[V | S_k]` form a martingale relative to the specialist's and public information — "the ask price is what the revised expectation of V will be if the specialist sells, and the bid is what the revised expectation will be if the specialist buys" (p. 80). Proposition 3: a bound on E[(average spread)² × volume] in terms of the variance of V (p. 74). Proposition 4: specialist's and insiders' expectations converge. Proposition 5: spread widens when insiders' information improves, insiders become more numerous, or liquidity traders' demand becomes more elastic (p. 74). Market shutdown: "if the insiders are too numerous or their information is too good … there will be no bid and ask prices at which trading can occur and the specialist can break even" (p. 74).

**Limitations.** No inventory, no competition among liquidity suppliers on a book, unit trades, no explicit closed-form spread without distributional assumptions ("one cannot make any headway on computing the mean spread from adverse selection without making strong assumptions about the unobservable arrival pattern of insiders", p. 74).

**Implication for a rebate-funded maker.** `[inference]` With rebate r per fill, the zero-profit touch-quoting condition becomes `ask − E[V | buy hits our ask] + r ≥ 0`, i.e. the realised *markout after our fills* must not exceed half-spread + r. On a 1-tick mid-cap book the maker cannot set the ask; the only decision is whether `E[markout | fill] < tick/2 + OUR_FEE`. This makes the conditional markout after fills the single statistic that decides the business, and it is exactly the statistic our queue-front backtest mis-estimates: GM's ask is conditional on *who* hits it, and queue position changes the mix of who hits us (front-of-queue fills happen before the informed cluster completes; back-of-queue fills happen after). The measured markout must be conditional on realistic queue position.

### Card — Glosten & Milgrom
- **Strategy hypothesis (what is the edge?)** None (equilibrium result): the spread equals expected adverse-selection loss; a maker earns nothing in expectation without a cost/rebate wedge.
- **Economic mechanism (why should this edge exist?)** Bayesian updating on the direction of the next trade; informed traders trade in the direction of their information.
- **Required data (L1 / L2 / L3 / trades / order events)** Trades with side + our fills (for markout); L1 for the quotes.
- **Holding horizon (1ms / 10ms / 100ms / …)** Until information is impounded (Prop. 4); empirically the markout horizon (100 ms – minutes).
- **Expected signal (what observable predicts the edge?)** The direction of the arriving trade itself; nothing before it.
- **Execution dependency (queue / latency / fill probability)** Which trades reach us (queue position) determines E[V | fill].
- **Failure modes (why might it disappear?)** If informed share rises, spread must widen to break even; on a fixed-tick book the maker can only withdraw ("market shuts down").
- **Evidence (paper + empirical result, with numbers)** Theory only.
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)** Contract: 3 mid-caps + BTC. Data: Tardis L2 + trades; simulate our touch fills with a queue-position model (not queue-front) and compute fee-inclusive markout `E[M_{t+h} − fill price | fill]` for h ∈ {100 ms, 1 s, 10 s, 60 s}, separately for front-third vs back-third queue positions. Pass (business viable) if mean markout + OUR_FEE + half-spread > 0 at h = 10 s for back-third fills on ≥ 7 of 9 OOS days; also report the queue-front vs realistic gap, which quantifies how much our current backtest assumption flatters us.

### 7c. Kyle (1985), "Continuous auctions and insider trading"

**Citation.** A. S. Kyle, *Econometrica* 53(6), November 1985, 1315–1335.

**Context.** Theory; one risk-neutral insider who knows the liquidation value v ~ N(p_0, Σ_0), noise traders u ~ N(0, σ_u²), competitive risk-neutral market makers who see only aggregate order flow x + u and set price = E[v | x + u] (zero profit, "Bertrand auction between at least two risk neutral bidders", p. 1318). Single auction, sequential auctions, and the continuous limit.

**Mechanism.** The insider trades a linear fraction of his information; makers price linearly in net order flow with slope λ (inverse depth). Noise trading provides camouflage, so depth is proportional to noise trading and inversely proportional to the amount of private information.

**The one formula.** Theorem 1 (p. 1319): unique linear equilibrium `X(v) = β(v − p_0)`, **`P(x + u) = p_0 + λ(x + u)`**, with **`β = (σ_u²/Σ_0)^{1/2}`, `λ = (1/2)(Σ_0/σ_u²)^{1/2}`**. "The quantity 1/λ measures the 'depth' of the market, i.e. the order flow necessary to induce prices to rise or fall by one dollar. This measure of market liquidity is proportional to a ratio of the amount of noise trading to the amount of private information" (p. 1319). Posterior variance Σ_1 = Σ_0/2 ("one-half of the insider's private information is incorporated into prices", p. 1319); insider's unconditional expected profit `E(π) = ½(Σ_0 σ_u²)^{1/2}` (p. 1320; OCR garbled, reconstructed — the text states profits are "proportional to the standard deviations of both v and u"). Continuous auction (Theorem 3, eq. 4.8, p. 1327): **`λ(t) = (Σ_0/σ_u²)^{1/2}`**, constant over time; depth constant; insider profits "exactly double" the single-auction value (p. 1330). Liquidity decomposed into tightness, depth (1/λ), resiliency (pp. 1330–1331).

**Limitations.** Normal-linear, one insider, no spread (single clearing price), makers earn exactly zero; "Modelling how market makers can earn the positive frictional profits necessary to attract them into the business of market making … takes us away from our main objective" (p. 1318).

**Implication for a rebate-funded maker.** `[inference]` Kyle's λ is the theoretical counterpart of Cont et al.'s β (price change per unit net flow) and of Glosten–Milgrom's spread: the maker's expected loss per unit of net flow that hits him is λ × (that flow). Since λ ∝ (Σ_0/σ_u²)^{1/2}, the maker's viability at a given rebate depends on the ratio of information variance to noise-trade variance *on this venue and this coin*; the rebate is a fixed subsidy per fill that must exceed λ × E[net flow against us while we rest]. Kyle also says the maker earns zero *only* because makers compete to zero; the rebate is exactly the "positive frictional profit" Kyle leaves out, and competing makers on KuCoin will compete it away to the extent they are as fast and as informed. Measuring λ per coin per hour (regression of Δmid on signed volume) gives an hourly "cost of resting" in bp to set against OUR_FEE.

### Card — Kyle
- **Strategy hypothesis (what is the edge?)** None (equilibrium): price impact per unit flow λ is set by information vs noise; makers break even.
- **Economic mechanism (why should this edge exist?)** Makers price the expected information content of net order flow; noise traders subsidise the insider.
- **Required data (L1 / L2 / L3 / trades / order events)** Trades with side (signed volume) + mid.
- **Holding horizon (1ms / 10ms / 100ms / …)** Impact is permanent in the model; empirically the horizon over which E[v | flow] is realised (seconds–minutes).
- **Expected signal (what observable predicts the edge?)** Net signed flow x + u (contemporaneous impact), i.e. the same object as OFI/trade imbalance.
- **Execution dependency (queue / latency / fill probability)** None in the model; for us, which flow we absorb.
- **Failure modes (why might it disappear?)** If informed variance rises or noise volume falls, λ rises and the fixed rebate no longer covers losses.
- **Evidence (paper + empirical result, with numbers)** Theory only.
- **Test (the exact experiment we should run on KuCoin Futures data: contract type, data needed, statistic, pass/fail threshold)** Contract: BTC + 3 mid-caps. Data: Tardis trades. Estimate λ per hour by OLS of Δmid (bp) over 10 s on net signed volume (in units of hourly volume); compute the "cost of resting" `λ̂ × E|net flow over the typical time-to-fill|` in bp; pass (rebate model viable) if median cost < OUR_FEE + half-spread on mid-caps across the 9 OOS days; fail if not. Also check whether λ̂·(hourly volume) is stable (normalisation check, ties to paper 2's β·AD).

---

## Which falsifiable hypothesis on KuCoin Futures does each paper give us?

All tests use: 5 September training days for fitting, the 9 purchased OOS days (09-02 onward, `data/oos/ku_buy`) untouched for parameters; fees OUR_FEE maker (OUR_FEE USDC), OUR_FEE taker; signals evaluated from t + 3.2 ms (2.2 ms data + 1 ms order) onward; fills from a queue-position model, not queue-front; placebo = shuffled labels/states; pass requires the criterion on ≥ 7 of 9 OOS days.

1. **Avellaneda–Stoikov.** H1: realized fill intensity vs distance from mid on KuCoin is exponential, `λ(δ) = A e^{−kδ}`, with k calibratable from the trade-size tail α and impact K. H2: inventory skew `−qγσ²(T−t)` reduces P&L std ≥ 30 % at ≤ 10 % mean cost versus symmetric quoting at equal average spread. Falsified if the log-linear fit R² < 0.8 (H1) or the std reduction fails (H2). Decision value: whether γ is worth tuning at all, and whether symmetric quoting is the right default for the volume target.
2. **Cont–Kukanov–Stoikov.** H1 (replication): per-hour `ΔP = β OFI` has median R² ≥ 0.5 on mid-caps with `β·AD` stable (CV < 0.5) — establishes depth-normalised flow as a stationary unit. H2 (the real question): lagged OFI (100 ms / 1 s) predicts the next interval's mid change with OOS R² > 0.02 and sign accuracy > 52 %. Expected: H1 pass, H2 fail (paper: OFI ACF small at 10 s). If H2 fails, OFI is a normaliser and a queue-depletion warning only.
3. **Stoikov micro-price.** H: the (imbalance × spread) table G* fitted in-sample predicts OOS conditional mean mid moves (Spearman ≥ 0.8 at 500 ms and 5 s) *and* keeps ≥ 0.5 when the move is measured from t + 3.2 ms; a pull/skew rule at |G*| > 0.25 tick improves fee-inclusive markout by ≥ 0.2 bp per fill. Falsified if the delayed correlation collapses (signal dies inside our latency) or the rule does not improve markout.
4. **Xu–Gould–Howison.** H1 (replication): ridge MLOFI (M = 10) reduces OOS contemporaneous RMSE by ≥ 40 % vs OFI on mid-caps, ≥ 10 % on BTC. H2 (maker-relevant): deep-level MLOFI over the last Δ predicts depletion of our touch level within (t + 3.2 ms, t + Δ] with OOS AUC ≥ 0.65. Only H2 justifies a live pull rule.
5. **Cartea–Jaimungal–Ricci.** H1: the Hawkes intensity imbalance `λ̂⁺ − λ̂⁻` from trades predicts the mid change over (t + 3.2 ms, t + h] with OOS R² ≥ 0.01 and sign accuracy ≥ 53 % (h = 100 ms – 10 s). H2 (regime): the empirical alpha jump ε̂ after "influential" trades (mean 1-s markout after a trade followed by ≥ 2 same-side trades in 100 ms, minus baseline) exceeds half-spread + OUR_FEE on mid-caps. If H2 holds and H1 fails, we are in the paper's "driven out" row and touch-quoting without alpha is unviable by construction; if H2 fails (small ε), the rebate maker "subsists" per Table 2.
6. **VPIN.** H: with true trade signs, VPIN percentile predicts next-bucket |return| (Spearman ≥ 0.25, and ≥ 0.10 after partialling out trailing realised volatility) and top-quartile VPIN buckets show ≥ 0.3 bp worse fee-inclusive markout per fill than bottom-quartile; a CDF(VPIN) > 0.9 gate raises net PnL with ≤ 15 % volume loss. Falsified if the volatility-partialled correlation vanishes (then VPIN is just volatility) or the gate costs volume without PnL gain.
7. **Ho–Stoll.** Full text not obtained; no independent hypothesis beyond item 1 (the AS model is the Ho–Stoll structure). Nothing to test separately.
8. **Glosten–Milgrom.** H (the business-defining one): fee-inclusive markout of our touch fills at 10 s, computed with a queue-position model and split by queue position, satisfies `E[markout | fill] + half-spread + OUR_FEE > 0` for back-third fills on mid-caps. Falsified if back-of-queue fills are net negative after rebate — which would also quantify how much the queue-front assumption flatters the current backtests.
9. **Kyle.** H: hourly Kyle λ̂ (Δmid on net signed volume) implies a "cost of resting" `λ̂ × E|net flow over time-to-fill|` below OUR_FEE + half-spread on mid-caps, and `λ̂ × hourly volume` is stable across hours (a normalisation check matching item 2's β·AD). Falsified if the cost exceeds the rebate + half-spread in the median hour.
