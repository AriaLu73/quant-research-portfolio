# Strategy Report — mm_v4(Queue-front state-gated touch maker)

> 口径:PAPER RESULT / OUR SIM(快速模拟器,ESTIMATED 队列)/ OUR BACKTEST(项目引擎 engine/backtest)/ OUR OOS(冻结后随机 5×1h)。本报告数字除注明外均为 OUR BACKTEST / OUR OOS。

## 1. Strategy Version
- Strategy ID / Version:mm_v4;代码 `strategies/research/mm_state_maker.py`(mode=gated),sha256 52536fab…;版本记录 `strategies/research/versions/mm_v4.json`。
- 日期:2026-09-13;交易所 KuCoin 永续 XBTUSDTM(系统符号 BTC-USDT);tick 0.1、lot 0.001。
- 状态:**OOS_TESTING → NOT_PASSED**(5 切片 1/5 正)。

## 2. Data
- Tardis 原始 L2 增量 + 逐笔成交,6 天(2025-10-01、2026-01-01、2026-04-01、2026-06-01、2026-07-01、2026-08-01),Data Audit 见 data_readiness.md(144 小时数据集,142 可用)。
- 训练/研究池:前 3 天(24 个 1h 切片,UTC 01/04/…/22 时);OOS 池:后 3 天 70 个可用小时,冻结后以 seed=20260913 抽 5 个。

## 3. Literature(见 literature.md)
L05 Gould-Bonart(队列失衡)、L04 Xu-Gould-Howison(多档 OFI)、L07 Moallemi-Yuan(队列位置价值)、L10 Albers et al. 2025(成交概率 vs 成交后收益;队首 vs 队尾)、L09 Huang-Lehalle-Rosenbaum(队列反应:小队列易耗尽)、L08 Lehalle-Mounjid(失衡驱动撤单、延迟侵蚀)、L01/L02 AS/GLFT 基线。

## 4. Factors 与 Configuration
| 因子 | 公式 | 用途 | 参数 |
|---|---|---|---|
| imb5 | (Σbq1..5 − Σaq1..5)/(Σ) | 开仓/减仓侧 post/pull 门控(对齐:本侧有利为正) | imb_post 0.3 / imb_pull −0.3(滞回) |
| 本侧顶档公开量 q | 引擎视图顶档量(不含己方) | 只在薄/新档(q ≤ q_max)挂单抢队首;宽限后 q < q_pull 撤单 | q_max_btc 0.1、q_pull_btc 0.25、q_pull_grace_ms 500 |
| 订单龄 | ts − 挂单时间 | 宽限期内不执行 q_pull | 500ms |
| 库存 | pos / clip | 上限 max_clips;减仓侧同门控;持仓 > hold_max_s 解除门控 | max_clips 3、hold_max_s 120 |
- Fair Value:mid(1 tick 市场,报价恒在盘口,失衡只用于 post/pull 决策,不平移价格)。
- Spread Model:无(贴盘口);Bid/Ask Logic:上表;Size:[金额已抹]/手固定;Cancel:pull 线以下 / 档位消失 / 宽限后档位太薄 / 库存规则;Inventory:上限 3 手,减仓侧门控 + 120s 超时解除。
- Execution/Fee/Latency/Queue 假设(项目配置 config/backtest/glft_kucoin_colo.yaml):post_only;maker 我方费率(我方费率档 返费)、taker 2bp(未用);下单延迟 1.5ms±0.5、行情 1ms(colo);L3 队列重建,队尾入队,撤单归因 0.5(ESTIMATED);部分成交。

## 5. Baseline vs Optimized(训练面板 24×1h)
| | GLFT 基线 | mm_v4 | 增量 |
|---|---|---|---|
| Net PnL | [金额已抹](−0.561bp) | [金额已抹](+0.063bp) | [金额已抹] / +0.62bp |
| 正切片 | 0/24 | 11/24 | |
| Hourly Sharpe(√n) | −7.38 | +0.30 | +7.7 |
| Fills / Fill rate | 53,175 / 0.90 | 3,910 / 0.15 | |
| Adverse selection(−5s markout,bp) | 1.07 | 0.78 | −0.29 |
| Realized spread(bp) | −0.28 | −0.19 | |
| Inventory mean/max(BTC) | 0.157 / 0.584 | 0.065 / 0.425 | |
| Max DD(单切片,$) | 933 | 80 | |

## 6. Five Slice Results(OUR OOS,冻结后;seed 20260913)
| # | Start | End | Net | Gross | Fees(负=返费) | Fills | Fill rate | Inv max | MDD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-06-01T12:00 | 13:00 | [金额已抹] | [金额已抹] | −57.07 | 371 | 0.115 | 0.403 | 69.5 |
| 2 | 2026-07-01T00:00 | 01:00 | [金额已抹] | [金额已抹] | −37.48 | 174 | 0.088 | 0.513 | 43.1 |
| 3 | 2026-07-01T05:00 | 06:00 | [金额已抹] | [金额已抹] | −16.79 | 99 | 0.098 | 0.369 | 15.3 |
| 4 | 2026-08-01T00:00 | 01:00 | [金额已抹] | [金额已抹] | −3.56 | 33 | 0.214 | 0.158 | 9.3 |
| 5 | 2026-08-01T01:00 | 02:00 | [金额已抹] | [金额已抹] | −1.58 | 13 | 0.125 | 0.158 | 5.0 |
- 合计:Net [金额已抹](−0.351bp / 流水 [金额已抹]);均值 −11.7、中位 −7.8、最差 −35.4、最好 +6.3;Sharpe −1.80;Fill rate 0.128;Realized spread −0.14bp;Adverse selection(5s)0.46bp(500ms −0.42 / 30s −0.52);库存 mean/std/max 0.100/0.113/0.513 BTC;返费 [金额已抹],付费 0,滑点 0。
- 同一 5 切片 GLFT 基线:Net [金额已抹](−0.308bp),0/5 正;mm_v4 相对基线 [金额已抹],但绝对值仍为负。

## 7. Fill Economics / Markout / Adverse Selection(引擎成交拆解,数量加权)
| 分组 | 训练:BTC / mk5s / mk30s | OOS:BTC / mk5s / mk30s |
|---|---|---|
| 开仓侧成交 | 41.8 / −0.58 / −0.28 | 10.5 / −0.14 / +0.32 |
| 减仓侧成交 | 55.9 / −0.99 / −1.28 | 15.2 / −0.71 / −1.16 |
| 档位消失后延迟窗内成交("独挂") | 72.5 / −0.93 / −1.09 | 20.6 / −0.55 / −0.35 |
| 挂单龄 ≤ 0.5s | 69.9 / −0.98 / −1.08 | 19.4 / −0.64 / −0.43 |
| 成交时本侧档量 ≥ 0.6 BTC | 25.6 / −0.20 / +0.19 | 7.3 / +0.07 / +0.18 |
返费 我方费率/笔;只有"挂单 ≥2s 且所在档 ≥0.6 BTC"的成交净为正,但它们只占成交量 ~25%。

## 8. Failure Analysis
- 分类:**ADVERSE_SELECTION**(主)+ **FILL_FAILURE**(次)。
- 机制:抢薄档队首的单在 0.5s 内被扫穿(档位消失 → 延迟窗内成交)占成交量 70%,markout −1bp;减仓侧即使门控也在 −0.7~−1.0bp;能赚钱的"队首于大队列"成交太少。
- 训练面板小时胜率 46%、OOS 1/5,与快速模拟器的 63% 一致地远低于通过 5/5 所需的 ≥90%。
- 已排除的方向(均为 OUR SIM / OUR BACKTEST 结论):OFI/波动/成交强度门控(边际)、减仓侧不门控(更差)、跨所领先 OKX(20ms/100ms 都无效)、"确认增长后加入"(无改善)、持仓超时/手数/单量变体(不改变胜率)。

## 9. Final Decision
**NOT_PASSED**。不进入 docs/backup_strategies.md;版本与 OOS 集合已固定记录(strategies/research/versions/mm_v4.json、data/research/oos_slices_mm_v4.json)。

## 10. Next Hypotheses(下一轮)
1. 撤单延迟前置:在档位公开量降到 q_pull 之前按"队列消耗速度"(L09 耗尽率)预测性撤单,目标把"档位消失后延迟窗内成交"从 70% 压到 <30%(需引擎里跟踪 q 的 200ms 变化率)。
2. 减仓侧改为"只在队首于大队列"状态挂(q ≥ 0.6 且己方前方量 ≈ 0),否则持仓等待;需要评估更长持仓的库存风险(OUR SIM h300 变体 +0.72bp 但胜率不升)。
3. 换标的/换费率:同一框架在多 tick 点差标的(ETH 等)上有价差可赚;需要 ETH 的 L2 增量数据。
4. 队列模型保真:Tardis 簿更新有 20% 先于成交打印到达,引擎会把该减量按撤单归因再叠加成交推进(双计),队列前推偏乐观;建议引擎加"成交先于簿减量"的对账开关后重跑。
