# Revised inventory management backtest: XBTUSDTM (user 2026-11-09: "btcusdt也跑一下")

Same setup as the XBTUSDCM run (`04_exit_mgmt_backtest_report.md`): P1 original g3 catalog, Δt = 2000 ms, l3sim exact queueing, post-only, 1.8 ms latency, October's 9 test days. Order size per side is XBTUSDTM's V_LO = 24 contracts (0.024 BTC ≈ [amount removed]). Maker rebate is OUR_FEE. Control and variants A / B run in the same replay without sharing fills.
Script `exit_mgmt_backtest.py --sym=XBTUSDTM`; data in `out/P1_dt2000_XBTUSDTM/exit_mgmt/` (`daily_summary.csv`). Units are USDT; bp is relative to fill notional.
Note: XBTUSDTM at 2000 ms had never been replayed in l3sim before, so the control has no earlier result to reconcile against. The first launch did not pass the contract argument and re-ran XBTUSDCM by mistake. It was stopped and relaunched. All 9 days of XBTUSDCM summaries match the original table exactly, so they were not affected.

## 9-day totals

| Group | Volume | Pre-rebate | Rebate | Total PnL | Pre-rebate bp | Total bp | Total positive days | Max inventory | Worst hour (pre-rebate) | Exit-order fills | Fell back to original inventory mgmt after 60 s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Control | [amount removed] | [amount removed] | [amount removed] | [amount removed] | −2.04 | −1.34 | 2/9 | 1,696 contracts (≈ [amount removed]) | [amount removed] | — | — |
| Variant A | [amount removed] | [amount removed] | [amount removed] | [amount removed] | −1.47 | −0.77 | 0/9 | 253 contracts (≈ [amount removed]) | [amount removed] | 268,705 contracts | 35,931 contracts (12%) |
| Variant B | [amount removed] | [amount removed] | [amount removed] | [amount removed] | −1.42 | −0.72 | 0/9 | 286 contracts (≈ [amount removed]) | [amount removed] | 246,067 contracts | 37,165 contracts (13%) |

## Daily (USDT: pre-rebate / rebate / total)

| Day | Hours replayed | Control | Variant A | Variant B |
|---|---|---|---|---|
| 10-01 | 11 | −510.0 / +163.6 / −346.4 | −623.5 / +287.1 / −336.4 | −483.2 / +235.1 / −248.1 |
| 10-02 | 22 | −2,259.3 / +437.8 / −1,821.5 | −1,728.6 / +777.2 / −951.4 | −1,351.5 / +636.2 / −715.4 |
| 10-13 | 14 | −233.0 / +128.2 / −104.8 | −389.0 / +215.2 / −173.9 | −319.8 / +182.7 / −137.1 |
| 10-14 | 17 | −84.1 / +262.9 / +178.8 | −977.3 / +468.4 / −508.9 | −748.0 / +382.8 / −365.2 |
| 10-15 | 19 | +72.6 / +315.9 / +388.5 | −1,186.3 / +557.3 / −629.0 | −944.2 / +454.0 / −490.2 |
| 10-16 | 24 | −762.1 / +280.6 / −481.5 | −1,065.7 / +486.9 / −578.8 | −907.5 / +408.4 / −499.1 |
| 10-17 | 24 | −257.3 / +79.4 / −178.0 | −216.5 / +121.9 / −94.6 | −191.8 / +109.0 / −82.7 |
| 10-18 | 24 | −766.4 / +178.1 / −588.2 | −566.7 / +300.5 / −266.2 | −442.3 / +248.9 / −193.4 |
| 10-19 | 22 | −1,307.4 / +243.1 / −1,064.3 | −884.1 / +418.8 / −465.3 | −725.4 / +347.8 / −377.6 |

## Side by side with XBTUSDCM (9-day total PnL)

| Contract | Rebate | Control | Variant A | Variant B | Variant pre-rebate bp | Variant total bp | Variant positive days |
|---|---|---|---|---|---|---|---|
| XBTUSDCM | OUR_FEE | [amount removed] | +240.9 | +241.4 | −0.56 / −0.52 | +0.64 / +0.68 | 9/9 |
| XBTUSDTM | OUR_FEE | [amount removed] | −4,004.6 | −3,108.7 | −1.47 / −1.42 | −0.77 / −0.72 | 0/9 |

## How to read this

1. **On XBTUSDTM the variants lose money every day.** Variant B loses [amount removed] less over 9 days than the control. Variant A loses about the same as the control.
2. **Why it works on USDC but not USDT:** after the change every fill becomes a round trip, and the aggressive exit gives the spread away. That costs −1.42 to −1.47 bp per trip on XBTUSDTM, against −0.52 to −0.56 on XBTUSDCM. Two rebates add OUR_FEE on USDT but 2.4 bp on USDC. On USDT the rebates don't cover the cost; on USDC they leave about OUR_FEE.
3. **Risk drops a lot:** max inventory goes from 1,696 contracts to 253–286, and the worst hour from −877 to −203/−238. The variants are less exposed to one-sided moves on the bad days (10-02: −1,822 → −715; 10-19: −1,064 → −378). But they also lose the control's two positive days (10-14, 10-15 at +179 / +389), which become losses.
4. **12–13% of the volume falls back to the original inventory management after 60 s** (3% on XBTUSDCM). XBTUSDTM exit orders are harder to fill (narrow spread, longer queues).
5. **Variant B is better than A:** pulling the catalog quote on the closing side cuts volume by 17%, but loses [amount removed] less before rebates and OUR_FEE USDT less in total.

## Limitations

The catalog is still estimated under the front-of-queue assumption; l3sim assumes our orders don't change other participants' behavior; 5 of the 9 days have incomplete data; the "highest fill-probability" exit pricing rule is my interpretation.
