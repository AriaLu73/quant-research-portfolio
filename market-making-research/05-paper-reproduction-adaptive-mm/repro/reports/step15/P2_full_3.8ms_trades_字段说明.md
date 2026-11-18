# P2_full_3.8ms_trades_<合约>.csv 字段说明

来源:Table 11 回测(l3sim 精确排队,固定延迟 3.8 ms)里代理 P2_full_L3.8 的全部成交,9 个测试日(2026-10-01、10-02、10-13…10-19),按时间排序,一行一笔。
三个文件:XBTUSDCM(47,309 行)、XBTUSDTM(51,771 行)、ETHUSDCM(121 行)。金额单位 = 合约计价币(USDC / USDT)。

| 字段 | 含义 | 单位 |
|---|---|---|
| ts_utc / ts_ns | 成交(或市价单结算)时刻,交易所时间 | UTC 时间 / 纳秒 |
| day | 测试日 | – |
| seg_300s | 当日第几个 300 s 段(0 起);段末清算行记的是被清算的那一段 | – |
| event | maker_fill = 挂单被动成交;market_order = P2 脉冲市价单(减仓);segment_end_liquidation = 300 s 段末市价清仓;day_end_mark_to_market = 日末残余库存按当日最后有效中价虚拟平仓(不是真实成交,只为让累计 PnL 与 Table 11 口径一致) | – |
| side | buy = 我方买入,sell = 我方卖出 | – |
| price | 成交价(挂单成交 = 我方挂单价;市价单 = 结算时对手最优价) | USDC / USDT |
| qty_contracts | 成交张数(XBTUSDTM 1 张 = 0.001 BTC;XBTUSDCM 1 张 = 0.0001 BTC;ETHUSDCM 1 张 = 0.01 ETH) | 张 |
| notional | 名义金额 = 张数 × 价格 × 每张币数 | USDC / USDT |
| cash_flow | 现金变动:卖出为正、买入为负(不含费与返佣) | USDC / USDT |
| rebate | 该笔挂单成交的 maker 返佣(USDT 我方费率 / USDC 我方费率,按训练窗参考中价折成每张固定值) | USDC / USDT |
| taker_fee | 市价单与段末清算的 taker 费 我方费率(同上折成每张固定值) | USDC / USDT |
| inventory_after_contracts | 该笔之后的库存(正 = 多头) | 张 |
| cum_pnl_excl_rebate | 累计 PnL,不含返佣,已扣 taker 费 = Σ(cash_flow − taker_fee) | USDC / USDT |
| cum_pnl_incl_rebate | 累计 PnL,含返佣 = Σ(cash_flow − taker_fee + rebate) | USDC / USDT |
| ahead0_contracts | 该挂单进簿时同价位排在前面的张数(0 = 队首) | 张 |
| ahead_at_fill_contracts | 成交时仍排在前面的张数 | 张 |
| queue_wait_ms | 从进簿到这次成交的时间 | 毫秒 |
| sweep_qty_contracts | 打到我方的那张吃单的总张数 | 张 |
| level0_ticks | 进簿时距同侧最优价的档位距离(正 = 比最优价差 N 个 tick,负 = 比当时最优价更优) | tick(BTC 合约 0.1,ETH 合约 0.01) |
| decision_ts_utc | 下这张挂单的决策时刻(进簿 = 决策 + 3.8 ms) | UTC |
| mid_at_exec / spread_ticks_at_exec | 市价单结算时的中价与点差 | USDC / USDT;tick |

核对:每个文件最后一行的 cum_pnl_incl_rebate 应与 Table 我方费率 该合约 P2_full 3.8 ms 行的 m(X_T) × 段数 一致(差异 ≤ 2%,来自 Table 11 只计回放小时内的段)。

## 各测试日回放小时(三合约相同的小时文件数;有效覆盖以 XBTUSDCM 为例,XBTUSDTM / ETHUSDCM 相差 < 0.4 h)

回放小时 = 该 UTC 日有 L3 数据的整点小时数,回测只在这些小时里报价与成交;有效覆盖 h = 扣除小时内缺口后的实际覆盖(reports/step00/gaps_<sym>.csv)。日均 / 每小时指标都按这里的小时数理解:10-01、10-02、10-13、10-14、10-15 五天数据残缺。

| 测试日 | 有数据的小时数(回放小时) | 有效覆盖 h | 覆盖率 | 数据完整? |
|---|---|---|---|---|
| 20261001 | 12 h | 10.3 h | 43% | 残缺 |
| 20261002 | 22 h | 21.1 h | 88% | 残缺 |
| 20261013 | 14 h | 13.1 h | 55% | 残缺 |
| 20261014 | 17 h | 14.9 h | 62% | 残缺 |
| 20261015 | 19 h | 18.6 h | 78% | 残缺 |
| 20261016 | 24 h | 24.0 h | 100% | 完整 |
| 20261017 | 24 h | 24.0 h | 100% | 完整 |
| 20261018 | 24 h | 24.0 h | 100% | 完整 |
| 20261019 | 22 h | 24.0 h | 100% | 完整(切点 21:41 后为 final_test 锁定,不回放) |
| 合计 | 178 h | 174.0 h | 81% | 9 天里 5 天残缺 |
