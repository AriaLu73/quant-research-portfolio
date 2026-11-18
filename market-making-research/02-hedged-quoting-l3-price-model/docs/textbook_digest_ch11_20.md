# Study digest — 做市实习生培训教材 ch11–ch20

Source: `ME_实习生教材\ch11.py … ch20.py` (chapter text embedded as Python strings; all dated 2026-09-29) plus companion code in `data_ch11 … data_ch20`. Textbook chapter numbers/figures are reproduced as stated in the chapters. Nothing below is my opinion unless explicitly tagged **[inference]**.

Chapter list: 11 风险控制 · 12 策略回测框架 · 13 回测指标计算 · 14 参数优化（网格、随机与贝叶斯搜索） · 15 模拟交易系统 · 16 实盘交易系统架构 · 17 资金费率套利做市 · OUR_FEE 跨交易所价差套利 · 19 波动率自适应做市 · 20 机器学习做市

A cross-chapter topical index (latency, queue, adverse selection, inventory, hedging, altcoins, fees, volatility, ML, validation) is at the end, followed by the relevance ranking requested.

---

## Chapter 11 — 风险控制 (Risk control)

Source note in file header: rules and numbers taken from `modules/risk/pre_trade.py`, `in_trade.py`, `state.py` and `config/live/risk_swap.yaml` (2026-09-29). Companion code: `data_ch11/drawdown.py`.

### 11.1 Core claims, rules, numbers

**Three-tier risk structure (11.1)**
| Tier | When | Action | Code |
|---|---|---|---|
| 事前 pre-trade PT-01 … PT-12 | synchronously before every order | any failing rule → order never leaves the engine | `modules/risk/pre_trade.py` |
| 事中 in-trade IT-01 … IT-07 | continuous while positions are held | graded alerts; severe → switch system to reduce-only etc. | `modules/risk/in_trade.py` |
| 事后 post-trade | after fills | archive, reconciliation, daily report | `modules/risk/post_trade.py` |

Escalation ladder (never "trigger → flatten everything" in one step): BLOCK_ORDER (reject that one order) → REDUCE_ONLY (no new opens, only reduce_only orders pass) → HALT_STRATEGY → FREEZE_SYMBOL (e.g. reconciliation mismatch) → 一键平仓 one-click flatten (halt → reduce-only → market close; triggered by a human in the Web console, or automatically at the top drawdown tier if configured).
Alerts go on separate channels by level; P0/P1 pop up in the Web console. All thresholds live in `config/live/risk_swap.yaml` (swap) / `risk_spot.yaml` (spot), per exchange, hot-updatable from Web. "本章引用的数值都以配置文件为准."

**Position limits (11.2)** — the common advice "total position ≤ 30% of net assets" is replaced by separate rules:
| Rule | Purpose | KuCoin swap config |
|---|---|---|
| PT-01 single-order notional cap | fat-finger / wrong parameter, extra zeros | per exchange |
| PT-04 per-symbol position cap | max notional per symbol | per exchange |
| PT-05 concentration | single symbol / category share of equity | single symbol 20%; majors 60%, altcoins 15% |
| PT-09 leverage cap | | default 5× |
| PT-10 margin adequacy | available funds ÷ new margin after order | ≥ 2.0 |
| PT-12 margin mode | isolated or cross only | KuCoin: isolated only |

Rule: strategy's inventory cap (ch. 9) is a **soft cap** (dynamic in σ; pulled back via skew, ladder, active reduce). Risk PT-04 is the **hard cap**: a fixed number in config, "must be simple, static" so that if the strategy's dynamic calc has a bug (e.g. σ computed as 0 → cap = ∞) the hard cap still holds. **Soft cap should always be clearly smaller than hard cap**; touching the hard cap means the strategy's inventory management is broken.

**Stop-loss: market making has no "per-trade" stop (11.3)**. Hundreds/thousands of fills per day alternate sides and leave one net position; "this trade's entry price" is meaningless. Stops live in three places:
| Object | Mechanism | Ref |
|---|---|---|
| Inventory | inventory ratio over hard line → actively reduce with **price-capped IOC** | ch. 9 (in strategy) |
| Strategy | N consecutive losses → auto pause (cooling period) | PT-08: **5 consecutive losses → pause 30 min** |
| Position survival | margin ratio alerts in four tiers; mark price too close to liquidation | IT-02: **3.5 / 2.5 / 2.0 / 1.5**; IT-03: **within 12% of liquidation price** |
- PT-08's cooling period is system-enforced, "不靠人的自律".
- All PnL/liquidation judgments use **mark price**, not last trade (ch. 9).
- IT-06 alerts when a held symbol's 1-minute move exceeds threshold (**swap: 3%**).

**Intraday drawdown (11.4)**
| Rule | Calculation | On trigger |
|---|---|---|
| IT-01 intraday drawdown, 3 tiers | drawdown from **the day's equity peak** | 1.5%: alert; 3%: global reduce-only; 5%: P0 popup and, per config, auto one-click flatten |
| PT-06 max daily loss | today's loss, absolute and percentage thresholds, whichever first | percentage threshold 3%: no new opens for the rest of the day |
Both reset at UTC day roll. Basis is the day's **peak**, not the open. Worked example (drawdown.py): equity [amount removed] → [amount removed] → 102,000 → 100,400 → 99,000. Relative-to-open drawdown: 0, −1%, −2%, −0.4%, +1%. Relative-to-peak: 0, 0, 0, **1.57%**, 2.94%. "上午赚了 2%，下午跌回来、还倒亏 1%": open-basis only triggers a 1% line at the end; peak-basis fires tier 1 while still in profit.
Why tiers: a single-shot market flatten pays the most taker fee and slippage at the worst moment (violent market, thin book). Tiers give: alert → block new opens and let inventory bleed off passively → only at the last tier flatten regardless of cost.

**Operational risk (11.5)** — "做市策略出大事，很多时候不是因为行情，而是因为系统做了不该做的事":
| Risk | Rule | Config |
|---|---|---|
| Obviously wrong price (bad param / bad market data) | PT-03: limit price deviates from mark price beyond threshold → reject | **0.5%** |
| Wrong quantity/amount | PT-01 single cap; PT-02 exchange spec check (min qty, step) | per exchange |
| Order loop | PT-07: order-count cap per 10 s and per day | per config |
| Exchange API mass failure | circuit breaker: failure rate > 5% in 10 s → read-only for 60 s | 10 s / 5% / 60 s |
| Local vs exchange position mismatch | IT-07: reconciliation deviation > tolerance → freeze symbol opens | tolerance 0.0001 |
| Market data outage/lag | adapter heartbeat, reconnect, book-gap rebuild (ch. 6); strategy cancels when data stale (ch. 8) | — |
| Human error | Web console has **no manual open** function; humans can only stop / reduce-only / flatten | by design |

**Check order for pre-trade (11.6)** — state first, then the order itself, then the account:
1. Strategy in PT-08 pause? Symbol frozen (IT-07)? System in reduce-only? → non-reduce_only orders rejected outright.
2. The order itself: PT-01 notional, PT-02 spec, PT-03 price deviation.
3. Position after this order: PT-04 symbol cap, PT-05 concentration.
4. Account/strategy state: PT-06 daily loss, PT-07 frequency, PT-08 consecutive losses.
5. Swap-only: PT-09 leverage, PT-10 margin adequacy, PT-11 funding rate, PT-12 margin mode.
In-trade monitoring (drawdown, margin ratio, liquidation distance, volatility, reconciliation) is an **asynchronous line, not on the order path**, so it does not slow quoting.
"风控不是限制赚钱，是让你活得够久": every trigger is a post-mortem event; "一个经常碰到风控线的策略，本身就是不合格的."

Reference answers to 思考题 1–3: (50,000−48,400)/50,000 = 3.2% → tier 2 (alert + global reduce-only). PT-04: 78k + 3k = 81k > 80k → reject even though the sell reduces → add reduce_only=True. PT-03: 600/100,000 = 0.6% > 0.5% → reject.

### 11.2 Citations / external resources
None (all references are to internal code paths and configs).

### 11.3 Pitfalls / warnings
- **reduce_only near the hard cap**: PT-04 tests "current position + this order's notional" unless the order carries reduce_only; a plain resting order that is directionally reducing can be blocked as an add near the cap. Strategy must set reduce_only=True on the inventory-reducing side when near the hard cap (also guarantees it never flips the position).
- **Drawdown thresholds must not be guessed** ("阈值不能拍脑袋"): tables like "conservative 0.5% / moderate 1% / aggressive 2%" are meaningless — 1% is 10σ for a strategy with 0.1% daily PnL vol (never fires), but fires several times a month for 0.8% daily vol. Thresholds must be tied to the strategy's normal daily PnL volatility (some multiple), i.e. **normalised**; that volatility is measured from backtest and small-capital live.
- **Risk code has bugs too.** Real fixes cited: a drawdown jump from tier 1 straight to tier 3 popped the window but skipped "block new opens" (fixed: reaching tier ≥ 2 always sets the flag); the day-roll task was written but never called, so counters never reset. Risk rules need unit tests specifically for **boundaries and jumps**: exactly-at-threshold, multi-tier jump, around day roll, missing market data.
- Exercise 3 asks whether a curve can trigger 1.5% on open-basis but not 3% on peak-basis (implied: peak-basis drawdown ≥ open-basis drawdown always) **[inference]**.

### 11.4 Topic-specific content
- Inventory control: soft (strategy, σ-dynamic) vs hard (risk, static) cap; price-capped IOC to reduce; reduce_only flag.
- Volatility adaptation: IT-06 1-minute 3% alert; drawdown/daily-loss thresholds should scale with PnL vol.
- Fee economics: single-shot flatten = max taker fee + slippage; tiers avoid it.
- Latency: in-trade monitoring is off the order path (no added quoting latency).
- Validation: risk rules need edge-case unit tests; thresholds measured from backtest + small live.
- Funding: PT-11 (detailed in ch. 17).

---

## Chapter 12 — 策略回测框架 (Backtest framework)

Header: minimal teaching event loop in `data_ch12/mini_engine.py`, `demo.py`; engine details from `engine/backtest/` and `config/backtest/`. Also `run_backtest.bat` (runs `engine.backtest.runner` with scenario `glft_kucoin_colo_ku_panel_p8_b05`, exchange kucoin, product swap_usdt, symbol BTC-USDT; output under `data\backtest_results\glft_kucoin_colo_ku_panel_p8_b05_<tag>\`).

### 12.1 Core claims, rules, numbers

**Why K-line frameworks (backtrader etc.) are unusable for MM (12.1)**: MM backtest needs tick-level order book (per level qty and changes), queueing (who is ahead of you at a price), latency (order and cancel take ms to reach the exchange), maker/taker separate fees with maker rebate. K-line frameworks give OHLC, "price touches your price = fill", instant orders, one fee rate. "用日线收盘价「做市」……和真实做市没有任何关系." hftbacktest is named as a good open-source reference (tick replay, queue and latency simulation); the firm uses its own engine.

**Engine design (12.2)** — `engine/backtest/`. Principle: **backtest and live share one code path** (strategy, sandbox, pre-trade risk, order tracker, PnL accounting identical); only two ends swapped:
| | Live | Backtest |
|---|---|---|
| Market data | exchange adapter (WebSocket) | data_feed: replay parquet |
| Orders | order gateway → exchange | BrokerSim |
| Time | system clock | simulation clock advanced only by data timestamps; **reading system time forbidden** |
Modules: data_feed (multi-stream — depth deltas, trades, funding — merged by nanosecond timestamp via min-heap; same-ns stable sort by (exchange, seq); integrity check at start) · clock (strictly monotone) · orderbook_rebuilder (L3 per-order exact queue, or L2 aggregated with approximate queue) · latency (two-way: market-data latency and order latency; fixed, normal, or fitted from live logs) · matching (price-time priority; orders enter an "in-flight queue", arrive after latency; resting, cancels, partial fills) · broker_sim (maker/taker fees separately, funding settled at settlement times, liquidation sim) · runner (modes: single, grid, walk_forward, live_replay — replays a live period to check fidelity).

**Event-driven minimal loop (12.3)**: heap (O(log n) vs O(n log n) full sort; a year of ticks is 10⁸+ events); same-timestamp events carry an incrementing seq so results are deterministic; clock only advanced by events, assert on time going backwards. Demo: strategy posts bid 100.0 at t=0; trades at t=0 (buy 100.1), t=3 (sell 100.0), t=9 (sell 100.0). Latency 0 ms → resting at 0, filled at 3. Latency 5 ms → resting at 5, filled at 9. "几毫秒的差别就能决定你接到的是好单还是毒单，所以回测必须模拟延迟."

**When does a resting order fill (12.4)** — three simultaneous conditions:
| Case | Test | Implementation |
|---|---|---|
| Price crossed | opposite best crosses your price, or an aggressive trade prints through your price — "真实交易所里，它一定先和你成交" | matching `sweep_crossed` and `on_trade` crossing branch |
| Queue reaches you | trade price == your price: the quantity ahead must be consumed first | orderbook_rebuilder keeps per-price queue and your position |
| Latency | order enters queue only after order latency; cancel also takes latency | matching in-flight queue |
Queue ambiguity under L2: a level going 5→3 doesn't say whether the cancelled 2 was ahead of or behind you. Parameter **queue_cancel_bias**: 1 = all cancels ahead of you (optimistic), 0.5 = uniform (neutral), 0 = all behind (pessimistic). Changing only this can move a strategy's fill volume "好几倍" on the same data → run optimistic and neutral (pessimistic if needed) and **report a range**; where truth lies is calibrated from small-capital live fills (ch. 15; engine `calibration` and `live_replay`).
Reference answer: level 8→5 with 6 ahead of you: bias 1 → 3 ahead; bias 0 → 6 ahead.

**Bugs actually fixed in the engine (12.5)** — all ran cleanly and looked normal before the fix; first four biased results optimistic, last made backtest ≠ live:
| Problem | Symptom | Fix |
|---|---|---|
| Matching only recognised "trade price == my price" | market sweeping through the order didn't fill: order became a dead "bid above market ask"; subsequent post-only orders rejected as self-cross; and the most-losing fills (being swept through a level) were exactly the ones omitted | added crossing fills (sweep_crossed, on_trade crossing branch). **All prior results voided and rerun** |
| Cancel arriving before order | order sent then cancelled immediately; cancel reached matching first and was silently dropped; order arrived as an orphan and kept filling | record "early cancel", cancel on arrival |
| Risk used system clock | thousands of sim-seconds take ms of real time; 10 s frequency window never expires; **99% of MM orders blocked by PT-07** | risk time source injectable; sim clock in backtest |
| Fee unit error | maker rebate OUR_FEE (OUR_FEE) once written as 0.0007 — rebate OUR_FEE× too big | write units in config, annotate bp next to value |
| Backtest and live accept different parameter names | docs and live accept `time_in_force="post_only"`; backtest runner only `tif="post_only"`. Strategy written per docs silently degraded to plain limit orders; ch. 8 teaching strategy over one hour: **23% of fills were taker** | teaching strategy passes both names; unified engine fix awaiting review |

"回测是用来找 bug 的": if results are surprisingly good, code is probably wrong. First read **fills.parquet**, not the equity curve. Checklist:
- fills at prices better than the market at that time (impossible fills)?
- fills before the order's latency arrival? fills after a cancel?
- post-only orders filled as taker?
- own volume share of market volume plausible? ([amount removed]/order strategy taking tens of % of market volume = bug)
- markout distribution at 5 s, 10 s after fill (ch. 7, 13)?

**Other traps (12.6)**: look-ahead (using data visible only after current clock — e.g. external-exchange data without observation delay; using a trade before the book update in the same ms; engine's cross-exchange feed only returns data with observation time ≤ current clock) · treating slippage as random noise (MM cost is adverse selection and queueing — systematic; model crossing, queue, latency, not random slippage) · fees (maker negative, taker positive, separate; units) · testing one regime only (range vs trend, quiet vs violent can invert; cover periods and split train/validation/OOS, ch. 14) · extreme markets (flash crash, liquidity drought; engine has `stress_test` scenarios).

**Running a backtest (12.7)**: `set HFT_ENV=backtest` then `.venv\Scripts\python -m engine.backtest.runner --scenario glft_kucoin_colo_ku_panel_p8_b05 --exchange kucoin --product swap_usdt --symbols BTC-USDT --strategy <file.py> --run-tag <name>`. Scenario files in `config/backtest/` define data slice, book rebuild mode, latency, fees, queue_cancel_bias; this scenario = one hour of KuCoin BTC perp, neutral queue (0.5). Output to `data/backtest_results/<scenario>_<tag>/`: fills.parquet, equity_curve.parquet, report.html/report.json. Real run of ch. 8 strategy found 23% taker fills on first run (the tif issue), all maker after fix.

### 12.2 Citations / external resources
- **hftbacktest** (open-source MM backtest framework; named as reference for tick replay, queue and latency simulation). No URL given.
- backtrader (named as an example of a K-line framework, unsuitable).

### 12.3 Pitfalls / warnings
- **Data granularity bounds fidelity**: KuCoin's official historical depth data is ~100 ms snapshots of 50 levels; between snapshots orders come and go, a level gets swept and refilled — queue competition cannot be reproduced. MM results on such data have an explicit fidelity ceiling; MM research needs tick-by-tick incremental data.
- **Company rule: backtest and validation use KuCoin data only** — other venues' books, flow, participant structure differ.
- Full-day backtests: one hour of data can take 10+ min, a full day 1–2 hours; **day-level backtests need mentor approval**, don't run several at once; long jobs must be launched via `scripts/detach.py` (ch. 4).
- Do not add random slippage to an MM backtest; do not use K-line frameworks; do not read system time inside the engine.

### 12.4 Topic-specific content
- Latency: two-way latency model (market-data and order), fixed/normal/empirical; in-flight queue; cancel latency; demo shows fill timing shifts with 5 ms; backtests "按 5ms"-class assumptions are scenario settings.
- Queue position: L3 exact vs L2 approximate; queue_cancel_bias 0/0.5/1; report as range; calibrate from live.
- Adverse selection: swept-through fills are the most losing and were the ones omitted by the bug; markout at 5/10 s in the fill check.
- Fee economics: maker rebate OUR_FEE = OUR_FEE; unit bugs; maker/taker separate.
- Validation: same code path live/backtest; fills.parquet checklist; live_replay mode; range reporting; KuCoin-only data; stress_test scenarios.

---

## Chapter 13 — 回测指标计算 (Backtest metrics)

Header: demo `data_ch13/metrics_demo.py` (run with `PYTHONPATH=`); report fields from `engine/backtest/runner.py` and `modules/analytics/metrics.py`.

### 13.1 Core claims, rules, numbers

**Order of reading metrics (13.1)**: (1) confirm results are credible — ch. 12.5 fill checklist; `risk_blocked_by_rule` (how many orders blocked by which rule; in the ch. 12 validation run some were blocked by PT-07); (2) MM-specific metrics; (3) generic metrics with their error bars; (4) charts with PnL decomposed. "一个撮合有 bug 的回测，后面所有指标都是在认真地计算一个错误的结果."

**MM-specific `mm` block in the report (13.2)**:
| Field | Meaning | How to read |
|---|---|---|
| volume_notional | total traded notional (流水) | core of exchange assessment; ÷ hours → hourly |
| hourly_volume | per-hour notional | stable or concentrated in a few hours? |
| capture_rate | our notional ÷ market notional same period | tens of % for a [amount removed]-per-order strategy = bug |
| maker_ratio | share of maker fills | post-only-only strategy must be 1.0 |
| fee_net | total fees; positive = paid, negative = net rebate received | maker strategy should be negative |
| spread_pnl | pre-fee PnL = total PnL + fees | spread + adverse selection + inventory, excluding fees/rebate |
| burn_bp | −spread_pnl ÷ volume × 10,000 | **pre-fee loss in bp per [amount removed] traded — "做市最重要的单一指标"** |
| pnl_total | total PnL | = −burn × volume + rebate |
| inventory_peak_qty / inventory_end_qty | | with ch. 10 inventory metrics |

Formula: **净收益（bp / 流水）= 返佣（bp）− burn_bp**. OUR_FEE_TIER maker rebate = **OUR_FEE**, so an all-maker strategy needs **burn_bp < 0.7**: per [amount removed] traded, spread + adverse selection + inventory pre-fee loss must be under [amount removed]. Business objective (ch. 1) "在万 U 耗损可控的前提下最大化流水" quantified: **万 U 耗损 = burn_bp − 返佣** (negative = profit). Why not return-on-capital: MM "principal" is ill-defined (order size and inventory cap set margin used, not account balance); per[amount removed]-bp is capital-independent and directly comparable to rebate tiers.

**Markout (13.3)** — `MarkoutTracker` in `modules.strategy.microstructure`; per fill, sign +1 buy / −1 sell:
- eff = sign × (mid at fill − fill price) — spread captured (~half tick when quoting at touch)
- adv = sign × (mid at h seconds − mid at fill) — negative = adversely selected
- fee = rebate positive, fee negative
- net = eff + adv + fee
Demo (horizons=(5.0,)): buy f1 at 100000.0 mid 100000.05 fee_bp 0.7; sell f2 at 100000.1 mid 100000.05; mid 5 s later 99990.05 ([amount removed] = −1 bp). Output: f1 eff +0.005 adv −1.000 fee OUR_FEE net **−0.295 bp**; f2 eff +0.005 adv +1.000 fee OUR_FEE net **+1.705 bp**. "eff 只有 0.005 bp——1 tick 市场里价差几乎可以忽略."
Aggregation: multiple horizons (1 s, 5 s, 30 s average adv — adverse selection usually happens fast then plateaus; the curve shape tells how quickly toxic fills are toxic); group by conditions (L1 imbalance at fill, spread state, fill type — swept through a level vs partial queue fill) → most direct improvement lead; markout is MM's win-rate/profit-factor: share of net > 0 = win rate; but **mean net decides profitability**.

**Sharpe (13.4)**: mean excess return / std × √periods-per-year. Crypto is 365 days (not 252); `modules/analytics/metrics.py` annualises by 365×24×60 minutes. Risk-free rate default 0 for hours–days backtests. Frequency must match (minute returns × √minutes/year; daily × √365). Lo (2002) standard error, for daily returns and annualised Sharpe 3.0:
| Days | 7 | 30 | 180 | 730 |
|---|---|---|---|---|
| SE of annualised Sharpe 3.0 | ±7.3 | ±3.5 | ±1.4 | ±0.7 |
Code: `sharpe_se(sr_annual, n) = sqrt((1 + (sr_annual/√365)²/2)/n) × √365`. 30-day Sharpe 3.0 ± 3.5 → true value could be 0 or 6. "Sharpe < 1 discard, > 2 optimise" thresholds only valid with long samples; for short backtests look at per[amount removed] return and its stability across hours/days.

**Max drawdown (13.5)**: `metrics.max_drawdown`, same algorithm as ch. 11 intraday but no daily reset; also look at recovery time.

**Win rate / profit factor / expectancy (13.6)**: expectancy = p×win − (1−p)×loss. A: 80%, +1, −5 → **−0.2**; B: 30%, +10, −1 → **+2.3**. MM strategies tend to look like A (many tiny wins of half tick + rebate; a few large losses in one-sided moves). Mean net (expectancy) matters far more than win rate; look at the **loss tail** (worst 1% of fills — size and timing). Report's win_rate / profit_factor are from FIFO-paired closes; hundreds of pairs a day differing by one tick make them look great and mean little.

**Charts (13.7)** — decompose cumulative PnL:
| Curve | Source | Healthy |
|---|---|---|
| cumulative rebate | per-fill fee (maker positive) | rises steadily with volume |
| cumulative eff + adv | spread & adverse selection | flatter is better; persistent decline = toxic fills eat the rebate |
| inventory PnL | total − the two above | oscillates around 0; large steps = inventory lost control in a trend |
| equity & drawdown | equity_curve.parquet | |
| inventory ratio, hourly volume | rebuilt from fills.parquet | inventory not pinned at cap; volume stable |
"「稳步上升的楼梯」可能只是返佣": a strategy whose rising equity is rebate-up minus spread/adverse-down is fully dependent on the rebate tier — tier drops, curve turns.

**Question list for every backtest (13.8)**: fill checklist passed? blocked orders by rule? maker_ratio and capture_rate plausible? net bp per [amount removed] and its decomposition into rebate/eff/adv/inventory? stable across hours/days and OOS (ch. 14)? holds under neutral/pessimistic queue assumption (ch. 12 range)? inventory half-life, ratio distribution, time at cap (ch. 10)? max drawdown as multiple of daily PnL σ; timing of worst 1% fills? sample length and metric error bars? "回测指标再好，也只是对历史的一种模拟。它能帮你排除坏策略，但不能证明一个策略是好的——那要靠小资金实盘，并用实盘成交去校准回测（第 15、24 章）."

Reference answers: volume [amount removed], spread_pnl [amount removed] all maker at OUR_FEE → burn_bp = 480/8,000,000×10,000 = **0.6 bp**; rebate = OUR_FEE×OUR_FEE = [amount removed]; total = **[amount removed]** (0.1 bp). Sell at 100,000.1, mid 100,000.05, mid 5 s later 100,002.05 → eff ≈ +0.005 bp, adv ≈ −0.2 bp, net ≈ **+0.505 bp**. 30-day Sharpe 2.0 → SE ≈ **3.5**, true value in roughly −5…9, "几乎什么都说明不了".

### 13.2 Citations / external resources
- **Lo, A. W. (2002)** — Sharpe ratio standard error approximation (cited as "Lo（2002）"; no title/venue given). Formula used: SE(SR) ≈ √((1 + SR²/2)/n) at the sampling frequency.

### 13.3 Pitfalls / warnings
- Sample too short → Sharpe meaningless (table above).
- **Percentage denominators may be fake**: some scenarios set initial capital very large (e.g. [amount removed]) so PT-05 concentration doesn't block the strategy; total_return, max_drawdown percentages are diluted. Look at drawdown in **dollars** and as a multiple of daily PnL σ (normalisation, as in ch. 11). "高频做市最大回撤应小于 2%" is meaningless without capital, leverage, order size.
- Win rate can be 80% and losing; FIFO pairing inflates win_rate/profit_factor.
- A single rising equity curve hides rebate dependence.
- Post-only strategy with maker_ratio ≠ 1.0 is a must-investigate signal.

### 13.4 Topic-specific content
- Adverse selection measurement: MarkoutTracker eff/adv/fee/net, horizons 1/5/30 s, grouping by imbalance/spread/fill type, loss tail.
- Fee economics: net bp = 0.7 − burn_bp; rebate-only equity curves; rebate tier sensitivity.
- Inventory: inventory PnL as residual curve; peak/end qty; time at cap.
- Validation: order of reading; credibility first; range over queue assumptions; OOS; small-capital live calibration.

---

## Chapter 14 — 参数优化：网格、随机与贝叶斯搜索 (Parameter optimisation)

Header: `data_ch14/overfit_demo.py` (stdlib), `bayes_demo.py` (needs scikit-optimize).

### 14.1 Core claims, rules, numbers

**Before optimising (14.1)** — the big risk is not failing to find the optimum but finding a lucky-looking one:
| Do first | Why | Example |
|---|---|---|
| Normalise | parameters in bp, multiples of σ, fraction of book depth keep meaning across regimes → optimum drifts less | "half-spread 3 bp" → "half-spread = 1.2 × σ × √(order lifetime)" |
| Start from theory | theory-based start beats blind wide search | microprice ↔ k = 1 (ch. 8); inventory cap from σ (ch. 9) |
| Fewer parameters | each parameter multiplies search and overfitting | quantities measurable from data (σ, fill arrival rate) must not be free search parameters |
Typically 2–3 parameters remain. Goal: **the most stable parameters, not the best**.

**Objective (14.2)**: not Sharpe (short-sample error, ch. 13). Primary: net bp per [amount removed] (rebate − burn_bp) or the business objective (max volume subject to 万 U 耗损 cap). Aggregate over multiple slices (e.g. 8 one-hour slices): mean, **worst slice**, **share positive**; params good on only 1–2 slices are untrustworthy. Constraints: maker ratio, time at inventory cap, risk-block count must be in range; violators eliminated regardless of return.

**Data split (14.3)** — by time, never shuffled:
| Part | Use | Rule |
|---|---|---|
| Train | search | reusable |
| Validation | choose among candidates / decide to continue | the more it's used the more it becomes training |
| OOS | final test | opened **only after parameters are frozen**, looked at once; pass criteria written down beforehand |
Firm's usual flow: train/validate on several one-hour slices; after freezing, **randomly** draw one-hour slices from never-used dates for OOS with pre-written criteria (e.g. sum of net over those slices > 0). Runner `walk_forward` mode: windows, first half select, second half validate, roll; **defaults to selecting on total_return — for MM replace with the 14.2 metric** (percentage denominator issue, ch. 13). Log every tried combination, including failures.

**Three methods (14.4)**:
- Grid: all combinations; runner `grid` mode (incrementing random seeds per combo for reproducibility); for 1–2 params with known ranges.
- Random: Bergstra & Bengio (2012) — when few parameters matter, random covers the important dimensions more densely for the same budget. Parameters spanning orders of magnitude (γ 0.001–1) sampled **log-uniform**; fix and record the seed; Python `random` and numpy both Mersenne Twister — "谈不上谁精度更高", seed and distribution matter.
- Bayesian (surrogate, typically Gaussian process; explore/exploit): fewer evaluations when each is expensive. Demo: true surface 0.3 − 0.4(h−1)² + N(0, 0.2), max 0.30 at h = 1.0; gp_minimize with Real(0.2, 1.8), n_calls=30, n_initial_points=10, noise="gaussian", random_state=42 → reports h = 1.176, best value **0.768** vs true max 0.30.
| | Grid | Random | Bayesian |
|---|---|---|---|
| Suited | 1–2 params | 3–6 params, exploration | expensive evals, continuous params |
| Pros | simple, fully reproducible | efficient in high dim, parallel | fewer evaluations |
| Cons | explodes with dims | ignores past results | chases noise; own hyper-params |
Compute budget: one one-hour BTC slice (~1M events) ≈ **4 min** per backtest on the dev machine; 50 combos × 8 slices = 400 runs ≈ 20+ hours. Reference answer: 3 params × 8 values, 6 slices, 4 min → 512×6 = 3,072 runs = 12,288 min ≈ **205 h (8.5 days)**. Uniform sampling γ∈[0.001,1], 100 draws → ~1 in [0.001, 0.01]; log-uniform → ~33.

**Overfitting from selection (14.5)** — `overfit_demo.py`, NOISE = 0.6 bp per one-hour slice (same order as signal), N_TRAIN = N_TEST = 8 slices, 200 trials:
| Experiment | Seen on train | True / OOS |
|---|---|---|
| 50 param sets, all true return 0; pick best on train | +0.48 bp | +0.03 bp (= 0) |
| real structure (wide hill max h = 1.0, value 0.3; narrow spike at h = 0.5 height 0.5 width 0.05) then market shifts surface by +0.2; pick train peak | +0.66 bp | +0.21 bp |
| same; pick plateau centre (highest mean over ±2 grid neighbours, ±0.21) | +0.31 bp | +0.27 bp |
"什么都没有的时候，挑出来的「最好」也会很好看"; more trials → better-looking and faker best. Literature corrections need the number of trials as input: Bailey & López de Prado (2014) **deflated Sharpe ratio (紧缩夏普比率)**; Bailey et al. (2017) **probability of backtest overfitting (回测过拟合概率)** → record trial counts. Rule: plot objective vs parameter (curve/heatmap); if a small move from the optimum degrades results sharply, distrust it; prefer the centre of a "neighbourhood all about equally good" even if not the highest on train.

**Practical rules (14.6)**: include all costs (maker rebate, taker fee, funding) — narrower spread → more fills → fee structure matters more; don't judge on one metric; **never "switch to the second-best parameters" in live** after a losing week — that is optimising on live noise; any parameter change goes through train/validate/OOS; re-validate periodically rather than re-optimise frequently; if the optimum drifts every few weeks the parameterisation is wrong → go back to 14.1 and normalise.

### 14.2 Citations / external resources
- **Bergstra, J. & Bengio, Y. (2012)** — random search vs grid search (cited as "Bergstra 和 Bengio（2012）"; no title given).
- **Bailey, D. H. & López de Prado, M. (2014)** — deflated Sharpe ratio ("紧缩夏普比率").
- **Bailey et al. (2017)** — probability of backtest overfitting ("回测过拟合概率").
- scikit-optimize `gp_minimize` (library, `pip install scikit-optimize`).

### 14.3 Pitfalls / warnings
- Optimiser's "best value" is the luckiest noisy observation (0.77 vs true 0.30); set the `noise` parameter; **re-run the chosen params on new data** to estimate true performance, never quote the optimiser's number.
- Selecting on the same data used for evaluation; shuffling time-series data (adjacent periods near-identical → leakage, and future data decides past params).
- Uniform sampling across orders of magnitude.
- Compute is a real constraint: confirm large searches with the mentor, use detach.py, don't saturate the machine.
- walk_forward default objective total_return is wrong for MM.
- Changing parameters in live on the basis of live losses.

### 14.4 Topic-specific content
- Volatility adaptation / normalisation: half-spread = 1.2 × σ × √lifetime as the canonical example; drifting optimum = un-normalised parameter.
- Fee economics: all fees including funding in the objective; narrower spreads amplify fee effects.
- Inventory: time-at-cap as a hard constraint in optimisation.
- Validation: train/val/OOS by time; OOS once, criteria pre-registered; worst-slice and share-positive; record trial count; deflated Sharpe / PBO.

---

## Chapter 15 — 模拟交易系统 (Simulation systems / paper trading)

Header: content from `gateway/order_gateway.py` (paper matching), `config/simulate/`, `config/deploy_okx_sandbox.yaml`, `engine/main.py` (tif fix comment), `engine/backtest/calibration.py`, runner `live_replay` mode. No data_ch15.

### 15.1 Core claims, rules, numbers

**Five gates from code to live (15.1)**:
| Gate | Tool | Answers | Cannot answer |
|---|---|---|---|
| ① fake-market test | hand-built book + fake ctx (ch. 8) | logic: direction, rounding, units, cancel/replace | anything about the market |
| ② backtest | historical ticks + simulated matching (ch. 12) | approximate behaviour in history: fills, markout, inventory | true queue and latency (assumed only) |
| ③ paper simulator | live data + full system + paper matching | can the whole system run continuously: connections, risk, alerts, console, restarts | profitability (paper matching has no queue) |
| ④ exchange sandbox | exchange-provided sim (OKX has one) | order API, signing, error codes, order state transitions | profitability (sparse matching) |
| ⑤ small-capital live | real account, tiny size | real fills, latency, queue — and calibrate the backtest | — |
"③和④都不是用来评估策略表现的." Only backtest (with assumptions) and small-capital live (real fills) evaluate strategy performance.

**simulate environment (15.2)**: `HFT_ENV` ∈ {live, simulate, backtest}. simulate: real live WebSocket data; whole chain runs (bus, adapters, engine, Web — six processes in fixed order; risk, alerts, day-roll as live); orders never leave the machine — gateway does paper matching: immediately-fillable → filled at **mark price**, else resting on a paper order table, filled when price reaches it; post-only that would fill immediately is rejected like a real exchange; paper funds injected per config `paper_assets` (otherwise equity 0 → ratio-based risk blocks everything). Commands: `set HFT_ENV=simulate`, `.venv\Scripts\python scripts\start_all.py` (broker → adapters → engine → Web), console `http://127.0.0.1:8080` (intranet only), `--stop-all`. Uses: sandbox load / hot parameter update / cancel-on-stop; multi-day memory and latency drift; disconnect, adapter restart, exchange maintenance recovery, orphan orders; risk triggers → popups, reduce-only, one-click flatten; day-roll counter resets and daily report.

**Exchange sandbox (15.3)**: OKX has one (`simulated_trading` switch, `config/deploy_okx_sandbox.yaml`); **KuCoin futures has no sandbox** → "在 KuCoin 上，第一天就是真钱，只能从很小的仓位开始." Tests: order format conversion, signing, error codes, state transitions, rate limits. Real bug caught: on OKX sandbox the strategy sent only post-only orders but **12% of fills were taker** — strategy passed `tif="post_only"` (backtest habit) while live API only accepted `time_in_force`; post-only silently became plain limit. Fix: live accepts both names. (Ch. 12 found the mirror-image bug in backtest; both caught by "first check maker share in fills".)

**Common errors when writing your own simulated matching (15.4)**:
| Wrong | Problem | Right |
|---|---|---|
| asyncio.sleep to simulate latency | loop really waits; uses system time; a day of data takes a day | schedule the event at a future sim time (ch. 12 mini_engine) |
| matching only checks "can my aggressive order fill" | MM resting orders are mostly filled by others; this doesn't simulate MM at all | check every public trade and book change against own resting orders: crossing, queue (12.4) |
| decrementing qty on a loop variable | `for price, qty in book: qty -= x` doesn't change the book; same liquidity eaten repeatedly | mutate the book; separate public liquidity from own orders |
| adding slippage after matching | fill price already reflects consumed levels; double count | slippage is the matching result |
| time.time() in sim | time sources diverge; all windows (rate limits, cooling) wrong | sim clock (ch. 12) |

**Small-capital live = final test and backtest calibrator (15.5)**:
| Calibrate | How | Tool |
|---|---|---|
| Latency | collect send→exchange-ack time for every live order; fit empirical distribution; backtest uses it | `calibration.calibrate_latency` → latency model `empirical` mode |
| Queue / fill rate | compare live vs backtest fill rate on the same period; back out queue_cancel_bias / L2 adjustment | calibration's L2 calibration; ch. 12 range |
| Fill quality | live vs backtest markout distribution on the same period | runner `live_replay`: replay the live period with history, compare fill by fill |
Rules: record calibration date and dataset; **"没有经过校准的 L2 概率撮合，结果不能直接用来做上线决策"** — a principle hard-coded in engine design; when live ≠ backtest, suspect the backtest first (queue, latency, crossing fills), not "bad luck"; small-capital stage judges fill quality and system stability, not money — PnL at tiny size is almost all noise.

**Acceptance (15.6)** — pre-written, per gate:
| Gate | Example acceptance items |
|---|---|
| paper sim | 72 h continuous no crash, no memory growth; auto-recover after 30 s disconnect with local book re-synced; no orphan orders; risk trigger → alert and reduce-only as designed |
| exchange sandbox | maker share = 100% when only post-only; every cancel acknowledged; all reject codes normalised; rate limit → queueing, not ban |
| small-capital live | latency distribution, fill rate, markout within the calibrated backtest range; reconciliation (exchange vs local ledger) always consistent |

### 15.2 Citations / external resources
None external (OKX sandbox, internal code paths only).

### 15.3 Pitfalls / warnings
- **Paper fills cannot evaluate a strategy**: no queue (filled the moment price touches, regardless of quantity ahead), no swept-through adverse selection; volume/PnL "既可能比真实的好得多，也可能差得多，没有参考价值".
- simulate default `paper_commission` is **maker +0.02%**, not the KuCoin rebate tier — check config before reading fee numbers.
- Exchange sandbox matching is sparse; PnL there is meaningless.
- **Fabricated acceptance tables** ("fixed latency 100 ms, expected fill rate −5%, actual −4.8%") — every "actual" must point to a specific run/log/file (learning rule 1 "可观测").
- Reference answer: paper sim earning [amount removed]/day for three days proves nothing.

### 15.4 Topic-specific content
- Latency: empirical latency calibration from live acks; latency model `empirical` mode.
- Queue position: calibrate queue_cancel_bias / L2 coefficient from live fill rate.
- Adverse selection measurement: live vs backtest markout comparison via live_replay.
- Validation before live: five gates; KuCoin has no sandbox → tiny size day one with a human watching; acceptance lists; L2 probabilistic matching must be calibrated before go-live decisions.

---

## Chapter 16 — 实盘交易系统架构 (Live system architecture)

Header: content from `docs/00_系统架构总说明.md`, `modules/execution/tracker.py`, `engine/event_queues.py`, `engine/scheduler.py`; demo `data_ch16/loop_lag.py`.

### 16.1 Core claims, rules, numbers

**Where latency goes (16.1)** — "低延迟" techniques (kernel bypass, lock-free queues, cache prefetch) matter in equities/futures where matching is µs; for crypto CEXs ask first where the time goes:
| Segment | Magnitude (crypto CEX) | Optimisation |
|---|---|---|
| Network: our server → exchange | same DC / cloud region: sub-ms; cross-region: several to tens of ms | **put the server in the exchange's DC/cloud region — the biggest item** |
| Exchange gateway + matching | ms-level ("我们回测里按交易所同机房 1–2 毫秒的口径建模") | uncontrollable; measure and model faithfully |
| Own processing: decode, book update, strategy, risk, encode | should be ≪ 1 ms | don't block, no extra work, right data structures |
| Sporadic tail: disk sync, logging, GC, blocking calls | occasional ms to tens of ms | move off hot path; **watch P99, not the mean** |
Conclusion: server location and absence of tail stalls matter far more than 100 µs → 10 µs. Start from measurement: backtest report and live monitoring both expose order latency P50/P95/P99.
Project red line: whole chain **Python 3.12**, only compiled piece is market-data binary decoding (Cython); pure CPU, no GPU/FPGA. Rationale: against ms-level exchanges Python overhead is not the main issue; one language / one code base for live, backtest, research (ch. 12) is worth more. "要快，靠的是架构和不阻塞，而不是换语言."

**Architecture: 8 layers, 6 processes (16.2)**:
| Layer | | Code |
|---|---|---|
| 1 Web control plane | monitor, params, start/stop, alert popups; **fully isolated — no market-data or order path, no manual open** | web/ |
| 2 core event engine | event queues, scheduler, strategy sandbox, time sync; backtest engine here too | engine/ |
| 3 message bus | inter-process: TCP, write-ahead log (WAL), token-bucket rate limiting | core/bus/ |
| 4 business modules | cache, strategy infra, 3-tier risk, order tracking, PnL analytics | modules/ |
| 5 normalised gateway | order format conversion, per-dimension rate limiting, signing | gateway/ |
| 6 exchange adapters | one process per exchange, spot/swap dual channel | adapters/ |
| 7 compiled layer | the only Cython: market-data binary decode | src/tick_codec/ |
| 8 external | exchange APIs, storage, layered config | data/, config/ |
Runtime: six processes, fixed start order bus → adapters → engine → Web; out-of-order start is blocked; each waits for the previous to be ready; abnormal exit cascades cleanup. Multi-process (not threads): GIL prevents true parallelism; more importantly **fault isolation** (one exchange adapter crash → restart alone). Web isolated because human-operated = most error-prone and attackable; reads snapshots and sends control commands only. Bus WAL: replay unprocessed messages after crash.

**Inside a process: asyncio (16.3)**: one event loop per process (uvloop on Linux), TaskGroup for coroutine groups (one failure cancels/cleans the whole group). Single-threaded: no locks needed, but **any blocking code stalls everything**. loop_lag.py output: idle loop → message waited **0.03 ms**; with a 50 ms synchronous `time.sleep` → **50.85 ms** (repeated 3×, ~50 ms each). Hot-path rules: no synchronous network or disk writes (async or delegate); no heavy computation (research stats/plots never in the engine process); right data structures — best price O(1), never sort the whole book (ch. 6).
Real tail fixed: order tracker fsync'd on every state change; in a risk-reject storm **500 orders → 480 fsyncs** on the order critical path. Fix: ordinary changes write without sync (debounced); only **terminal states that reflect real fund changes — fill complete and cancel complete — fsync**; rejected orders whose records are lost are cleaned by startup reconciliation.
Queues & backpressure: events partitioned by (exchange, product class) with watermark monitoring; **above 85% watermark only tick trades (droppable) are dropped**; book deltas, funding, order reports, risk and control commands **never dropped** (a lost book delta corrupts the local book; a lost order report corrupts inventory).

**Order state machine (16.4)** — `modules/execution/tracker.py`:
| State | May become |
|---|---|
| CREATED | SUBMITTED, REJECTED (risk/gateway) |
| SUBMITTED | PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED |
| PARTIALLY_FILLED | PARTIALLY_FILLED, FILLED, CANCELLED |
| FILLED / CANCELLED / REJECTED | terminal |
Daily realities and handling:
| Situation | Cause | Handling |
|---|---|---|
| fill report before "accepted" | private push and REST response on different channels | key by order id, assume no order; fills drive inventory |
| duplicate report | resend after reconnect, or REST + push both | **idempotent**: unchanged state accepted silently |
| cancel when already filled | cancel in flight, fill first | cancel rejected "already filled" — normal, not an error |
| want to cancel before exchange order id known | send then immediately cancel | mark "pending cancel", send cancel when id arrives |
| report for unknown order | pre-restart orders or manual web orders | warn, hand to reconciliation, don't crash |

**Timeouts, retries, recovery (16.5)**: never blindly resend on timeout (order may be resting → two orders); use **client order id** (`clientOid`) — query status by it first, resend only if not resting; exchange dedupes on it. Disconnect: stop new orders; on reconnect reconcile first, then resume quoting. Restart: tracker restores open orders from disk, bus replays WAL, then REST pull of live open orders and positions for reconciliation; deviation > tolerance → freeze symbol (IT-07) and wait for a human. **Audit log append-only** (every state change recorded, never modified/deleted).

Reference answers: a 30 ms synchronous HTTP call delays all market data 30 ms (strategy sees a 30 ms-old book; orders rest at stale prices). Dropping a tick loses one data point; dropping a book delta makes the local book wrong thereafter. 2 s no response → don't resend; query by client order id first.

### 16.2 Citations / external resources
None external (uvloop, asyncio TaskGroup as libraries; internal docs/code).

### 16.3 Pitfalls / warnings
- "Textbook" state machine that raises on unexpected messages — a single out-of-order report crashes the order module; out-of-order happens daily. Firm: illegal transition → log ERROR, return empty, don't crash; duplicates accepted; unknown orders to reconciliation. Backtest report records `tracker_illegal_transitions`; non-zero must be investigated.
- **Two "order books"**: market book (everyone's orders, rebuilt from feed) vs own orders (from reports via tracker). E.g. a level showing 5 BTC may include your own 0.01 BTC — **subtract own orders when computing imbalance and queue position**.
- Blindly resending on timeout; blocking calls on the hot path; per-order fsync; looking at mean latency instead of P99.

### 16.4 Topic-specific content
- Latency: decomposition table; colocation is the dominant lever; own processing ≪ 1 ms; P99 tails from fsync/log/GC; backtest models exchange same-DC 1–2 ms; 50 ms blocking demo; question 5 (engine 200 µs → 50 µs when network is 8 ms — worth it?) left for discussion.
- Queue position: subtract own orders from displayed level when estimating queue.
- Inventory: fills (not acks) drive inventory; order reports never dropped.
- Validation/ops: reconciliation on reconnect and restart; append-only audit; illegal-transition counter.

---

## Chapter 17 — 资金费率套利做市 (Funding rate: mechanism, cash-and-carry, and market making)

Header: KuCoin data from a real run of `data_ch17/funding.py` on 2026-09-29 (public endpoints `https://api-futures.kucoin.com`, `/api/v1/funding-rate/{symbol}/current`, `/api/v1/contract/funding-rates?symbol=…&from=…&to=…`).

### 17.1 Core claims, rules, numbers

**Mechanism (17.1)**: KuCoin BTC-USDT perp settles every **8 h** (UTC 0/8/16). Positive rate → longs pay shorts (contract above spot); negative → shorts pay longs. Payment = position value **at the settlement instant** (mark price) × rate; close one second before → neither pay nor receive; transfer between longs and shorts, exchange takes nothing. Formula: **funding ≈ premium index + clamp(interest − premium index, −0.05%, +0.05%), bounded by floor/cap.** KuCoin daily interest parameter 0.03% → 0.01% per 8 h, so with contract ≈ spot the rate sits at **+0.01% — the neutral position, not "longs overheated"**. Read interval and bounds from the API, never hard-code.

**Real data (17.2)**, KuCoin BTC-USDT perp, run 2026-09-29:
| Item | Value |
|---|---|
| interval | 8 h (UTC 0, 8, 16) |
| floor/cap | ±0.3% |
| daily interest param | 0.03% (0.01%/period) |
| last 30 days, 90 periods | min −0.0052%, mean **+0.0035%**, max +0.0100% |
| share positive | 84% |
Mean +0.0035%/period = **0.35 bp**; ~1 bp/day; ~3.8%/year before any costs.

**For market makers (17.3)**: inventory usually held minutes, but inventory at settlement pays/receives:
| Inventory at settlement | rate +0.01% | rate +0.1% (frenzy) |
|---|---|---|
| long [amount removed] | pay [amount removed] | pay [amount removed] |
| short [amount removed] | receive [amount removed] | receive [amount removed] |
System handling: strategy base class `funding_cost(symbol, holding_hours)` estimates funding for a holding period; **PT-11**: |current funding rate| > threshold (config **0.1%**) → reject new opens, reduce only; **IT-04**: alert on abnormal/jumping funding (signals one-sided market, more volatility ahead); backtest settles funding from historical rate stream at settlement instants.
Strategy uses: before settlement push inventory toward 0 or to the receiving side — briefly increase inventory skew (ch. 9, 10) so the paying side is reduced more aggressively; when funding is abnormal tighten inventory cap (extra discount on the ch. 9 cap); non-zero target inventory when funding is persistently one-sided is a **separate decision** — a few tenths of a bp per period vs extra directional risk; must be backtested and validated on its own.

**Cash-and-carry arithmetic (17.4)** — not in the firm's business scope, computed for understanding:
| Item | Assumption | bp of notional |
|---|---|---|
| income per period | 30-day mean 0.0035% | +0.35/period |
| swap leg open + close | maker both, rebate OUR_FEE × 2 | +1.4 |
| spot leg open + close | ordinary spot fee ~OUR_FEE × 2 | −20 |
| total round-trip cost | | ≈ −18.6 |
| breakeven periods | 18.6 / 0.35 | **≈ 53 periods ≈ 18 days** |
Not counted: spot leg ties up full notional plus swap margin; a sharp rally can margin-call/liquidate the short while spot sits in another account; rate may turn negative (16% of periods in the sample); basis moves against you at close.

**Funding in backtests (17.5)**: settle at the exact instants (not smeared per second, not wrong timezone); use historical rates, not a constant (abnormal rates coincide with strategy loss periods); interval and bounds can change per contract — read from data; report lists `funding_cost` separately; if it's large in a short backtest, check whether a large inventory happened to sit at settlement.

Reference answers: rate −0.02%, short [amount removed] at settlement → **you pay** 30,000 × 0.0002 = [amount removed]. 0.00015 = 0.015% = 1.5 bp. Closed 1 s before settlement → no funding.

### 17.2 Citations / external resources
- KuCoin Futures public API: `https://api-futures.kucoin.com/api/v1/funding-rate/{symbol}/current` (fields granularity, fundingRateFloor, fundingRateCap, dailyInterestRate, value) and `/api/v1/contract/funding-rates?symbol=&from=&to=` (fundingRate). Symbols XBTUSDTM, ETHUSDTM, SOLUSDTM.

### 17.3 Pitfalls / warnings
- **Unit error ×100**: `threshold = 0.01` commented "over 0.01%" is actually 1% (API returns decimals; 0.0001 = 0.01%) — never fires in 30 days; but a true 0.01% threshold is the neutral level and fires almost every period. "费率、手续费、价差，写代码前先确认是小数、百分数还是 bp" — the recurring error of the whole textbook (also ch. 12).
- "Steady 5–10%/month" claims: 30-day real data gives ~3.8%/yr ≈ 0.3%/month pre-cost; 5–10% needs rates tens of times the mean — only in extreme regimes / small coins where spreads blow out, liquidity is poor and liquidation risk is high. Any "stable income" claim → recompute with real data, all costs and risks.
- "Open 30 min before settlement, collect and leave": everyone knows, so crowding worsens spreads/book around settlement; round-trip fees and spread (swap taker alone OUR_FEE × 2) far exceed one period's funding (< 1 bp normally).
- Hard-coding settlement interval or bounds.

### 17.4 Topic-specific content
- Inventory control: settlement-time inventory skew; tighten cap when funding abnormal; PT-11 0.1%.
- Hedging: cash-and-carry legs and their asymmetric liquidation risk (short leg vs spot in another account).
- Mid-cap/altcoin: extreme funding "通常只出现在少数极端行情和小币种上" with worse spreads/liquidity/liquidation risk; exercise compares BTC/ETH/SOL funding stability.
- Fee economics: maker rebate OUR_FEE per leg vs spot 10 bp per leg; swap taker OUR_FEE.
- Validation: separate backtest for non-zero target inventory; funding_cost line in report.

---

## Chapter 18 — 跨交易所价差套利 (Cross-exchange arbitrage)

Header: concepts, costs, risks, and the firm's decision; **no other exchange's data used** (company rule). Demo `data_ch18/xarb.py` with constructed numbers.

### 18.1 Core claims, rules, numbers

**Three forms (18.1)**:
| Form | How | Main difficulty |
|---|---|---|
| take both sides ("搬砖") | B's bid > A's ask → take A's ask and B's bid simultaneously | taker fees both sides; legs can't truly be simultaneous |
| post one side, hedge other | maker on A, on fill immediately take on B | maker fill often coincides with impending price change (adverse selection); hedge leg latency |
| external price as signal | quote only on A, use B's moves as lead–lag predictor | you see B late; competing with faster people doing the same |
MMs discuss form 3 most: if one venue leads, pull the side about to be swept on the follower venue.

**Executable spread (18.2)**: "A price − B price" is not what you earn. **Buy on A, sell on B: net = (B bid − A ask) − fee_A − fee_B.** Rules: direction right (buy hits their ask, sell hits their bid; compute both directions); by quantity — walk levels, use VWAP (ch. 2 impact cost) not best price; express in bp alongside fees. xarb.py `executable_edge_bp(book_a, book_b, qty, fee_a_bp, fee_b_bp)` returns both directions after fees, None if depth insufficient.
Outputs (constructed): the "common textbook example" A 50,000/50,010, B 50,005/50,015, fees OUR_FEE each → {A买B卖: −21.0, B买A卖: −23.0} — usually misread as "[amount removed] visible spread, −95 after fees", but A's ask (50,010) > B's bid (50,005) and B's ask > A's bid: **both directions negative before fees — no opportunity exists**. A real moment: B bid 50,040 (0.3 BTC), second 50,030 (1); A ask 50,010 (0.5), 50,012 (2); fees A OUR_FEE, B 4.0 bp → qty 0.1: +0.2; 0.3: +0.2; 1.0: **−1.4** (hits second level). Conclusion: spread must exceed the sum of both taker fees **and still exceed it at your intended size**; such moments are rare, brief, and watched by everyone.

**Latency (18.3)** — timeline: B's book changes → data travels to your server (market-data latency) → you detect and decide → two orders fly to A and B (two order latencies, different lengths) → each matches, results return. Server can be in one place: next to A means slow view of B, and vice versa; competitors have servers at both. Backtest rule: external-exchange data replayed at "exchange event time + observation delay"; strategy may read only data whose observation time ≤ current sim clock; the delay must be **measured from actual server location**, not a small guess. Otherwise: look-ahead (ch. 12).

**Execution & capital risks (18.4)**:
| Risk | What happens | Response |
|---|---|---|
| single-leg fill | A fills, B doesn't or partially → unhedged position | immediately hedge with price-capped IOC; if can't hedge, close quickly — not "wait 30 s and see" |
| price moves in flight | spread gone by the time of fill | limit orders with price caps; rather miss than chase |
| one venue's API fails | one leg can't be sent | any side abnormal → stop opening on both |
| capital/inventory drift | always buying on A, selling on B → USDT depletes on A, coin piles on B | periodic transfers — fees, on-chain confirmation wait, capital idle meanwhile |
| exchange risk | capital across venues; any one freezing withdrawals/failing | cap per-venue share |
| contract details differ | face value, tick, mark price, funding differ | normalise all quantities/prices/fees first (ch. 2, 17) |
Risk must **aggregate across exchanges**: each venue small alone, combined a large net (or, on hedge failure, double) exposure.

**Why the firm doesn't do it (18.5)**: business focus (MM, fee tier and partnerships on KuCoin; HTX adapter done and market-data tested but not launched — no dedicated team, capital/attention split); latency structure (server near KuCoin → slower on every other venue; no structural edge vs two-site players); research principle (KuCoin-only backtests/validation conflicts with needing other venues' data); research conclusion (cross-venue lead signal studied seriously and abandoned; focus on KuCoin MM quality — fewer toxic fills, inventory management, normalisation); complexity (another adapter, capital, reconciliation, aggregated risk, ops — ongoing cost). "不是说跨所套利一定不赚钱，而是说在我们的条件下，它不是投入产出最好的方向."

**Questions to answer if ever re-evaluated (18.6)**: distribution of executable spread after fees at intended size — how often > 0, how long; real latency P50/P99 to each venue and is backtest observation delay set from it; single-leg probability and loss distribution, failure handling; capital allocation/rebalancing time and cost; cross-venue risk aggregation and simultaneous halt; opportunity cost vs KuCoin MM.

Reference answers: A 30,000/30,002, B 30,010/30,012, fees OUR_FEE each → A买B卖: [amount removed] ≈ 2.67 bp − 4 bp ≈ **−1.3 bp**; other direction negative pre-fee → neither works. B bid only 0.2 BTC for a 1 BTC trade → using best bid **overstates** the spread; use 1 BTC VWAP. Driving A's decisions with B's exchange timestamps = look-ahead, badly optimistic.

### 18.2 Citations / external resources
None external.

### 18.3 Pitfalls / warnings
- Misreading textbook arbitrage examples (both directions must be computed with correct sides).
- Using best price rather than VWAP for size.
- "More exchanges = more diversification" — for arbitrage each leg is another failure point (APIs, latencies, single-leg risk, transfers).
- Waiting after a single-leg fill.
- Per-venue-only risk views.

### 18.4 Topic-specific content
- Latency and its monetisation: cross-venue timeline; observation delay in backtests; colocation as structural advantage/disadvantage; competitors at both sites.
- Adverse selection: maker fill on A often precedes the move (form 2).
- Hedging: IOC price-capped hedge; close if hedge fails; both sides halt on any anomaly; aggregated exposure.
- Fee economics: taker fees A OUR_FEE / B 4.0 bp examples; spread must exceed fee sum at size.
- Validation: KuCoin-only rule blocks cross-venue validation.

---

## Chapter 19 — 波动率自适应做市 (Volatility-adaptive market making)

Header: `data_ch19/vol_demo.py` uses ch. 7 recording `data_ch07/book.csv` (8 minutes of KuCoin BTC); `adaptive.py` stdlib.

### 19.1 Core claims, rules, numbers

**Where σ already appears (19.1)**:
| Chapter | Place | Relation |
|---|---|---|
| 3 | Avellaneda–Stoikov reservation price | inventory skew ∝ σ² |
| 7 | mid-price volatility TimeEwmaVar | time-decayed, unit bp/√s |
| 8 | half-spread parameter | typical move over order lifetime ∝ σ × √time |
| 9 | inventory cap | cap = tolerable loss / (σ × √holding time) ∝ 1/σ |
| 10 | risk penalty, GLFT skew | penalty ∝ σ²; skew coefficient c₂ grows with σ |
| 11 | in-trade IT-06 | 1-min move alert |
"波动率自适应不是一个单独的策略，而是归一化原则的具体化" — parameters as functions of σ keep their meaning across regimes (why ch. 14 optima drift less).

**Estimating σ (19.2)**: sample mid at fixed time intervals, returns in bp, std, convert to per √s.
| Estimator | Method | Notes |
|---|---|---|
| rolling std | last N samples | N must be defined by time, not by "N periods" |
| time-weighted (TimeEwmaVar) | exponential decay by real elapsed time (ch. 7) | event density doesn't change meaning; **what the project's strategies use** |
| bipower variation | product of adjacent |returns| (Barndorff-Nielsen & Shephard 2004) | robust to single jumps by design; assumes continuous price movement |
Real data (8 min KuCoin BTC, 100 ms grid; `sigma_per_sqrt_s` = std of pct_change × 1e4 / √(step s); `bipower` = √((π/2)·mean(|r_t||r_{t−1}|) / step s)):
| Interval | std (bp/√s) | bipower (bp/√s) |
|---|---|---|
| 0.1 s | 0.472 | 0.188 |
| 0.5 s | 0.466 | 0.222 |
| 1 s | 0.493 | 0.259 |
| 5 s | 0.557 | 0.492 |
| 10 s | 0.612 | 0.510 |
Two lessons: (1) σ estimate depends on sampling interval — under a pure random walk per-√s σ would be constant; rising 0.47 → 0.61 means short-horizon moves tend to continue (short-term momentum) in these 8 minutes; **sampling interval must match the decision horizon** (order lifetime of seconds, inventory holding of tens of seconds) — 8 minutes of data, the specific result doesn't generalise, the method does. (2) Estimators have preconditions: bipower at 0.1 s = 0.19 not because vol is low but because the continuity assumption fails — in a 1-tick market the mid moves in half-tick jumps and is mostly still (ch. 7: **72% of 1-second intervals have unchanged mid**), so adjacent nonzero returns are rare and the product ≈ 0; at 5–10 s the two converge. "用任何估计量之前，先想清楚它的假设在你的数据上是否成立."

**From σ to quotes (19.3)**
Multi-tick markets, continuous scaling: half-spread = base × σ/σ_ref (a ratio — that is normalisation; σ_ref = median over a longer window); inventory skew ∝ σ² (ch. 10); inventory cap ∝ 1/σ (ch. 9); **all three move together**, not only the spread.
1-tick markets, discrete actions: can't "quote wider"; σ decides per side: touch / back one level / off. `action_by_vol(sigma, sigma_ref, back=1.5, off=3.0)`: ratio < 1.5 → "touch", < 3.0 → "back", else "off".

**Smoothing: fast up, slow down (19.4)** — `FastUpSlowDown(tau_up=1.0, tau_down=30.0)`: EMA with time constant tau_up when the raw value rises, tau_down when it falls; a = 1 − exp(−Δt/τ). Demo: raw σ 0.4 for 0–10 s, 1.4 for 10–20 s, 0.4 after; σ_ref 0.4:
t=9 raw 0.4 smooth 0.40 touch · t=11 1.4→1.26 off · t=13 1.38 off · t=19 1.40 off · t=21 raw 0.4 smooth 1.34 off · t=30 1.09 back · t=45 0.82 back · t=60 0.65 back.
At 10 s σ jumps to 3.5× → within 1 s smoothed value 1.26 → stop quoting; after the raw drops at 20 s the smoothed value only reaches "back" around 30 s and is still 0.65 at 60 s. Counter-claim addressed: "widen immediately on a vol spike and you miss the move, so smooth" — for MMs the opposite: MMs don't chase moves; **first duty on a spike is self-protection; be fast to turn conservative, slow to turn aggressive**.

**Regime models (19.5)**:
| Method | Does | View |
|---|---|---|
| GARCH (Bollerslev 1986) | forecasts next-period vol from past returns/vol; volatility clustering | classic; careful with assumptions on high-frequency, 1-tick discrete prices |
| HAR (Corsi 2009) | linear combo of daily/weekly/monthly realised vol | simple, robust, a good baseline |
| HMM | hidden regimes each with own vol distribution | captures switching; state count and params estimated → overfits easily |
| K-means | cluster vol features into low/mid/high | boundaries and per-class params are arbitrary |
Criterion (as ch. 7, 14): a regime model earns its place only if it adds information **beyond the current σ estimate** that holds out of sample. Get TimeEwmaVar right first; complex models must prove themselves with data, not looks.

**Practical rules (19.6)**: multiple horizons — short window fast/noisy, long window stable/slow; for protective uses (spread, cap) take the **larger** of the two σ; combine with inventory — when σ rises, be more conservative on the inventory-increasing side and can be more aggressive on the reducing side (ch. 9), not both sides tightened; known scheduled events (data releases, exchange maintenance) → reduce risk by schedule before σ rises; "high vol but good liquidity → tighten" is a hypothesis needing data (look at fill markout in high-vol periods, ch. 7 method), not a default; strategy-internal adaptation is the first line, IT-06 the second.

Reference answers: σ 0.5 bp/√s, 4 s lifetime → 0.5×√4 = **1.0 bp**. σ 0.4 → 0.8: cap ∝ 1/σ → **½**; penalty ∝ σ² → **4×**. 5-second-return std OUR_FEE → 1.2/√5 ≈ **0.54 bp/√s**.

### 19.2 Citations / external resources
- **Barndorff-Nielsen, O. E. & Shephard, N. (2004)** — bipower variation (no title given).
- **Bollerslev, T. (1986)** — GARCH.
- **Corsi, F. (2009)** — HAR (heterogeneous autoregressive realised volatility).
- Avellaneda–Stoikov (ch. 3 reference, restated), GLFT (ch. 10 reference, restated).

### 19.3 Pitfalls / warnings
- **Capping the σ ratio at 0.5–3×**: when σ is truly 10× normal, quoting at 3× width underestimates risk at the most dangerous moment. Better: an explicit state — above some multiple, stop quoting or keep only the reducing side (the 1-tick approach).
- Bipower variation at high frequency on 1-tick data grossly underestimates σ.
- Rolling windows defined by count instead of time.
- "Cluster three regimes, multipliers 0.8/1.0/1.5, retrain daily": every number is invented; daily retraining redefines "high vol" daily.
- Smoothing symmetrically or too much (slow to protect).
- Assuming high vol + good liquidity permits tightening without data.

### 19.4 Topic-specific content
- Volatility adaptation: the whole chapter (estimation, scaling laws σ / σ² / 1/σ, discrete actions for 1-tick, asymmetric smoothing 1 s / 30 s, regime-model scepticism, larger-of-two-horizons for protection, scheduled events).
- Inventory control: σ-dependent cap and skew; side-asymmetric response.
- Adverse selection: check high-vol fill markout before tightening.
- Validation: regime models must add OOS information beyond σ; 8-minute results don't generalise.

---

## Chapter 20 — 机器学习做市 (Machine learning for market making)

Header: `data_ch20/lgb_vs_baseline.py` (lightgbm, pandas, scikit-learn) trains on the ch. 7 recording; `tree_eval.py` stdlib inference verified against LightGBM 4.7.0; `model.json` = dumped model (6 features, regression, num_leaves 15).

### 20.1 Core claims, rules, numbers

Positioning: the model is a **co-pilot** — it doesn't place orders, it supplies a signal that adjusts quotes.

**Labels (20.1)**: define by **time, not ticks** ("next 5 ticks" is ms in violent markets, seconds in quiet ones; use next 1 s / 5 s); use **mid**, not last trade (bid-ask bounce adds pure noise); regression (future mid change in bp) or 3-class up/flat/down — in a 1-tick market **72% of 1-second intervals have unchanged mid** so "flat" dominates; classification thresholds must **scale with σ** (fixed % thresholds → all "flat" when quiet, all up/down when violent) — normalisation again.

**Data split (20.2)** — more important than the model: by time, no shuffle (train → validation → test); **leave a gap ≥ one prediction horizon between splits** (a 1 s-ahead label at the end of train uses the start of validation); validation for early stopping only, so its score is no longer fair — final evaluation on test, once; features use only past data (watch rolling window direction).

**Beat the simple baseline first (20.3)** — 8-minute KuCoin BTC, 100 ms samples, target = next-1 s mid change (bp). Six features: L1 imbalance (`imb_l1`), ±5 bp depth imbalance (`imb_5bp`), past-1 s OFI normalised by mean L1 size (`ofi_1s`), past 1 s and 5 s returns (`ret_1s`, `ret_5s`), past-5 s signed aggressive trade flow (`flow_5s`). Split 60/20/20 by time, gap = 20 samples (2 s). LightGBM params: regression, num_leaves 15, learning_rate 0.05, min_data_in_leaf 50, seed 42, up to 500 rounds, early_stopping(30) on validation. IC = Spearman correlation.
| Method | Train IC | Test IC |
|---|---|---|
| L1 imbalance alone (nothing trained) | +0.320 | **+0.408** |
| Linear regression (6 features) | +0.312 | +0.399 |
| LightGBM (6 features, 20 trees after early stop) | **+0.499** | +0.361 |
Interpretation: few thousand highly autocorrelated samples → far less independent information; six features from the same book are highly correlated (ch. 7); the extra the model learns is mostly noise. Only 8 minutes — not a conclusion that "LightGBM is useless", but the rule: **any model must beat the simplest baseline out of sample before it may enter a strategy**.

**From prediction to quotes (20.4)**: same as ch. 8 imbalance — predicted up → shift both quotes up (bid more aggressive, ask more conservative); sign error is the most common bug (catch with ch. 8 fake-market tests). Multi-tick: fair = mid + k × prediction, **k calibrated from data**, not "multiply skew by 0.8 / 1.2". 1-tick: map to discrete actions — strong up → ask back one level or off (ch. 8 §8.5). Confidence thresholds ("adjust only if p > 0.6") presuppose **calibrated probabilities**; tree raw outputs usually aren't → set thresholds from data (ch. 7 method). Evaluate at fill times, not average accuracy: your fills happen when price is crossing you — harder-than-average moments; final criterion = **did fill markout improve and net bp per [amount removed] rise, out of sample** (ch. 7, 13).

**Deploying into the system (20.5)**: strategy sandbox allows only **whitelisted imports** (ch. 4, 8) — no `import lightgbm`, no `open()`. Procedure: train in research env, `model.dump_model()` → JSON; strategy walks the trees with stdlib (`tree_eval.predict(model_json, x)`: iterate trees up to best_iteration, follow `split_feature`/`threshold` with `<=`, NaN follows `default_left`, sum `leaf_value`); model JSON embedded in strategy source/params, not read at runtime; adding a generic inference module to the whitelist requires review (microstructure and signal_pipeline were approved that way). Verified: pure-Python vs LightGBM predictions max diff **1.7 × 10⁻¹⁶**; inference ≈ **12 µs** per call (20 trees) on the dev machine — acceptable versus ms exchange latency (ch. 16).

**Model updates (20.6)**: "retrain after 10 consecutive wrong predictions" — with 55% directional accuracy at 10 predictions/s, ≈ 864k predictions/day × 0.55 × 0.45¹⁰ ≈ **160 occurrences/day** by pure chance → model "corrected" hundreds of times a day chasing seconds of noise. "Retrain daily after close" chases yesterday's idiosyncrasies (and crypto has no close). Stable approach: retrain on a fixed schedule; new model must beat old model **and** the simple baseline on the same OOS window before replacing (ch. 14 flow); monitor IC, calibration curve, fill markout by day/week trends; keep the baseline as fallback (degrade to L1-imbalance rule, don't halt).

Reference answers: 5 s horizon at 100 ms → gap ≥ **50 samples**. 3-class model 71% accuracy where "flat" is 72% → **bad** (always-flat beats it); look at per-class performance, calibration, markout. Sandbox forbids lightgbm/file reads for safety and auditability → JSON + stdlib inference, or whitelist a reviewed module.

### 20.2 Citations / external resources
- LightGBM 4.7.0 (library; API change noted: `lgb.train(..., early_stopping_rounds=50, verbose_eval=50)` no longer valid in 4.x → `callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)]`).
- scikit-learn `LinearRegression`, pandas, numpy.
No papers cited.

### 20.3 Pitfalls / warnings
- **pandas index alignment**: a time-indexed Series and a numpy-wrapped Series correlated → silent misalignment → NaN (loud this time); the dangerous case is partial overlap producing a plausible wrong number. Convert both to same-order arrays before comparing predictions and labels (code uses `pd.Series(np.asarray(pred)).corr(pd.Series(np.asarray(y)), method="spearman")`).
- Copying old API calls; pin library versions (requirements, ch. 4).
- **Train/live feature mismatch**: research computes features in pandas batches, live computes incrementally; any difference (time vs count windows, subtracting own orders or not, NaN filling) shifts the live input distribution and performance quietly degrades → research and strategy must **share one feature implementation** (microstructure module).
- Uncalibrated probability thresholds; average accuracy as the metric; tick-count labels; last-price labels; shuffled splits; no gap; retrain-on-streak rules; daily retraining.

### 20.4 Topic-specific content
- ML/RL for MM: everything above (labels, splits, baseline comparison with actual numbers, deployment constraints, update policy). No RL content in this chapter.
- Adverse selection: evaluation at fill times; markout as the acceptance metric.
- Latency: 12 µs inference vs ms exchange latency.
- Validation: OOS baseline beating; test set once; feature parity; calibration monitoring.

---

## Cross-chapter topical index

**Latency and its monetisation**
- Ch. 12: latency changes which fills you get (5 ms demo); two-way latency model (fixed / normal / fitted from live logs); cancels also delayed; in-flight queue; scenario `glft_kucoin_colo_…` presumes colo.
- Ch. 15: calibrate latency from live send→ack times → `empirical` latency mode.
- Ch. 16: decomposition — network (colo sub-ms vs cross-region ms–tens of ms) ≫ exchange matching (ms; backtest models same-DC 1–2 ms) ≫ own processing (≪ 1 ms) ; P99 tails (fsync, logs, GC, blocking) ; 50 ms blocking demo ; Python-only red line ; "要快，靠的是架构和不阻塞".
- Ch. 18: cross-venue latency timeline; observation delay; being near KuCoin is a structural disadvantage for cross-venue signals.
- Ch. 20: 12 µs inference is negligible relative to exchange latency.
- The chapters never quantify a monetary value of latency; they frame it as fill selection (good vs toxic fills) and as a correctness requirement in backtests **[inference: no explicit "value of 1 ms" figure exists in ch. 11–20]**.

**Queue position**
- Ch. 12: L3 exact vs L2 approximate; queue_cancel_bias 0 / 0.5 / 1; fill volume can differ "好几倍"; report ranges; KuCoin 100 ms 50-level snapshots cannot reproduce queue competition.
- Ch. 15: back out bias / L2 coefficient from live fill rate; uncalibrated L2 matching cannot support go-live decisions; paper matching has no queue.
- Ch. 16: subtract own orders from displayed level when computing queue/imbalance.

**Adverse selection measurement**
- Ch. 13: MarkoutTracker eff / adv / fee / net; horizons 1/5/30 s; grouping by imbalance, spread state, fill type (swept vs partial); loss tail; decomposition curves (rebate vs eff+adv vs inventory).
- Ch. 12: swept-through fills are the most losing and the ones a naive matcher misses; markout 5/10 s in the fill checklist.
- Ch. 15: live_replay compares live vs backtest markout.
- Ch. 19/20: high-vol tightening and ML models are accepted only if fill markout improves.

**Inventory control**
- Ch. 11: soft (σ-dynamic, strategy) vs hard (static, PT-04) caps; PT-05 concentration 20% / 60% / 15%; reduce_only near caps; price-capped IOC reduction; no per-trade stop.
- Ch. 13: inventory PnL residual curve; peak/end qty; half-life, ratio distribution, time at cap.
- Ch. 14: time-at-cap as optimisation constraint.
- Ch. 17: skew inventory before funding settlement; tighten cap when funding abnormal (PT-11 0.1%).
- Ch. 19: cap ∝ 1/σ, skew ∝ σ², penalty ∝ σ²; side-asymmetric response.

**Hedging**
- Ch. 17: cash-and-carry legs (spot vs perp), asymmetric liquidation risk, breakeven ≈ 53 periods.
- Ch. 18: post-one-side/hedge-other; IOC price-capped hedge; close if hedge fails; halt both sides on any anomaly; aggregated exposure.
- No intra-venue delta hedging of MM inventory is described in ch. 11–20 **[inference]**.

**Mid-cap / altcoin market making**
- Ch. 11: PT-05 altcoin category cap 15% of equity (majors 60%).
- Ch. 17: extreme funding concentrated in small coins with poor liquidity/liquidation risk; BTC/ETH/SOL funding comparison exercise.
- Nothing else altcoin-specific in ch. 11–20 **[inference]**.

**Fee / rebate economics**
- Ch. 13: net bp = rebate (OUR_FEE OUR_FEE_TIER) − burn_bp; burn must be < 0.7; 万 U 耗损 = burn − rebate; "staircase may be just rebate"; rebate-tier sensitivity.
- Ch. 12: maker OUR_FEE = OUR_FEE unit bug; maker/taker separate; fee units annotated in bp.
- Ch. 14: include rebate, taker fee, funding; narrow spreads amplify fee effects.
- Ch. 15: paper commission default +0.02% maker ≠ KuCoin tier.
- Ch. 17: swap taker OUR_FEE; spot ~10 bp; funding 0.35 bp/period mean.
- Ch. 18: taker fee examples OUR_FEE / 4.0 / 10 bp.

**Volatility adaptation** — ch. 19 in full; ch. 11 (IT-06 3%/min; thresholds scaled to PnL σ); ch. 13 (drawdown as multiple of daily σ); ch. 14 (half-spread = 1.2 × σ × √lifetime; normalise to stop drift); ch. 20 (label thresholds scale with σ).

**ML / RL** — ch. 20 (supervised LightGBM only; no RL anywhere in ch. 11–20); ch. 19 §19.5 regime models (GARCH, HAR, HMM, K-means) with scepticism; ch. 14 Bayesian optimisation as a tool.

**Validation before live**
- Ch. 12: same code path; fills.parquet checklist; KuCoin-only data; result ranges; stress_test.
- Ch. 13: credibility → MM metrics → generic metrics with error bars → decomposition; question list.
- Ch. 14: normalise → few params → objective on multiple slices (mean/worst/share positive) → train/val/OOS by time, OOS once with pre-registered criteria → plateau not peak → record trials → never tune in live.
- Ch. 15: five gates; paper/sandbox test the system not the strategy; KuCoin has no sandbox → tiny live size day one; calibrate latency/queue/markout from live; pre-written, traceable acceptance items.
- Ch. 16: reconciliation on reconnect/restart; illegal transitions counter; append-only audit.
- Ch. 20: beat baseline OOS; test once; feature parity; monitor IC/calibration/markout.

---

## Relevance ranking for a low-latency (1.8 ms REST round trip), maker-rebate (OUR_FEE) MM strategy on KuCoin perpetuals

Ordered by how directly the chapter's content bears on designing and validating such a strategy (this ordering is my judgement; content is the chapters').

1. **Ch. 13 (metrics)** — defines the economic target exactly for this setting: all-maker net = OUR_FEE − burn_bp, burn must be < OUR_FEE; MarkoutTracker decomposition (eff ≈ 0.005 bp in a 1-tick BTC book, so P&L is adv + rebate); rebate-dependence diagnosis; what to read first in a backtest.
2. **Ch. 12 (backtest engine)** — latency and cancel latency in matching, crossing fills, queue_cancel_bias ranges, the five real engine bugs (post-only tif name, fee unit, sim clock), KuCoin-only data, fidelity ceiling of 100 ms snapshots. Essential for trusting any number produced at 1–2 ms latency assumptions.
3. **Ch. 19 (volatility adaptation)** — concrete scaling laws (spread ∝ σ, skew ∝ σ², cap ∝ 1/σ), 1-tick discrete actions (touch/back/off at 1.5×/3×), asymmetric smoothing (1 s up / 30 s down), estimator pitfalls on 1-tick data, "stop quoting rather than cap the ratio".
4. **Ch. 14 (optimisation/validation)** — normalisation before search, objective = net bp over slices with worst-slice, OOS once with pre-registered criteria, overfitting numbers, compute budget (4 min per one-hour slice).
5. **Ch. 15 (simulation gates)** — KuCoin futures has no sandbox, so the path is backtest → paper (system only) → tiny live with latency/queue/markout calibration; explicit rule that uncalibrated L2 matching can't drive go-live.
6. **Ch. 16 (architecture/latency)** — where the 1.8 ms actually sits (network + exchange ≫ own processing), P99 tails (fsync storm), never-drop order reports, client-order-id retry discipline, subtracting own orders from displayed depth.
7. **Ch. 11 (risk)** — hard caps and thresholds the strategy must live under (PT-03 0.5% price deviation, PT-04/PT-05, PT-07 frequency, PT-08 5 losses/30 min, IT-01 1.5/3/5%), reduce_only requirement near caps, normalised drawdown thresholds.
8. **Ch. 17 (funding)** — settlement-time inventory management on perps (8 h, ±0.3% cap, PT-11 at 0.1%), funding as a small directional cost (~0.35 bp/period), unit-error warnings.
9. **Ch. 20 (ML)** — relevant if a predictive signal layer is contemplated: baseline-beating rule with real IC numbers, deployment via JSON + stdlib inference (12 µs), feature parity; no RL.
10. **Ch. 18 (cross-exchange)** — least relevant: documents why cross-venue arbitrage/lead signals are out of scope under the KuCoin-only rule; only the observation-delay/look-ahead principle carries over.
