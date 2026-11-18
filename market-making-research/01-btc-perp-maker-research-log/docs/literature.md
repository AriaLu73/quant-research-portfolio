# 文献登记(Literature Registry)— 做市策略研究

> 规则:论文只负责 Hypothesis Generation;本地 L2 数据负责 Empirical Validation。
> 必须区分 PAPER RESULT / OUR BACKTEST RESULT / OUR OOS RESULT。本文件只记录 PAPER RESULT。

| id | title | authors | year | venue | URL / DOI | hypothesis | factor / mechanism | data requirement | expected effect | MM relevance |
|---|---|---|---|---|---|---|---|---|---|---|
| L01 | High-frequency trading in a limit order book | Avellaneda, Stoikov | 2008 | Quantitative Finance 8(3) | https://doi.org/10.1080/14697680701381228 | 做市商在库存风险厌恶下的最优报价 = 保留价 ± 半价差;到达强度 A·exp(−kδ) | 保留价 r = s − q·γ·σ²·(T−t);半价差 = γσ²(T−t)+ (2/γ)ln(1+γ/k) | mid、σ、成交到达强度 | 库存偏斜降低库存方差,牺牲少量价差 | Baseline(AS) |
| L02 | Dealing with the inventory risk: a solution to the market making problem | Guéant, Lehalle, Fernandez-Tapia | 2013 | Math. Fin. Econ. 7 | https://arxiv.org/abs/1105.3115 | 无限期、库存上限 Q 的 AS 问题有闭式渐近解 | δ*_bid/ask = (1/γ)ln(1+γ/k) + (2q∓1)/2·sqrt(γσ²/(2kA)·(1+γ/k)^(1+k/γ)) | σ、A、k 标定 | 报价随库存线性偏斜 | Baseline(GLFT) |
| L03 | The price impact of order book events | Cont, Kukanov, Stoikov | 2014 | J. Financial Econometrics 12(1) | https://arxiv.org/abs/1011.6402 | 短期价格变动 ≈ 线性于顶档订单流失衡 OFI | OFI_n = Σ e_k,e = 1{Pb≥Pb'}qb − 1{Pb≤Pb'}qb' − 1{Pa≤Pa'}qa + 1{Pa≥Pa'}qa' | L1 事件序列 | 几秒内 R² 高;价格冲击系数 ∝ 1/深度 | Fair value / toxicity |
| L04 | Multi-level order-flow imbalance in a limit order book | Xu, Gould, Howison | 2018 | Market Microstructure & Liquidity | https://arxiv.org/abs/1907.06230 | 深档 OFI 增加对 mid 变动的样本外解释力 | MLOFI 向量(前 M 档) | L2 多档 | 每加一档 OOS R² 单调改善 | Fair value |
| L05 | Queue imbalance as a one-tick-ahead price predictor in a limit order book | Gould, Bonart | 2016 | Market Microstructure & Liquidity | https://arxiv.org/abs/1512.03492 | 大 tick 标的下 L1 队列失衡强预测下一次 mid 变动方向 | I = (qb−qa)/(qb+qa) | L1 量 | 大 tick 下 logistic 分类显著优于空模型 | Fair value / side |
| L06 | The micro-price: a high-frequency estimator of future prices | Stoikov | 2018 | Quantitative Finance 18(12) | https://ssrn.com/abstract=2970694 | 以失衡与价差为状态的期望 mid 极限 = 鞅公允价 | microprice = mid + g(I, spread) | L1 | 优于 mid 与加权 mid 的短期预测 | Fair value |
| L07 | A model for queue position valuation in a limit order book | Moallemi, Yuan | 2017 | working paper (Columbia) | https://moallemi.com/ciamac/papers/queue-value-2016.pdf | 队列位置价值 = 静态项(价差 − 随位置递增的逆向选择)+ 动态项(期权价值);大 tick 下队列价值与价差同量级 | queue_ahead / 队列相对位置 | L2 + 成交 | 队首成交逆向选择显著小于队尾 | Queue / cancel / hold |
| L08 | Limit order strategic placement with adverse selection risk and the role of latency | Lehalle, Mounjid | 2018 | Market Microstructure & Liquidity | https://arxiv.org/abs/1610.00261 | 限价单成交概率与失衡强相关;失衡逆向时应撤单;延迟侵蚀该价值 | 失衡驱动的撤/挂控制 | L1 + 延迟 | 失衡预测的价值随延迟衰减 | Cancel / side |
| L09 | Simulating and analyzing order book data: the queue-reactive model | Huang, Lehalle, Rosenbaum | 2015 | JASA 110(509) | https://arxiv.org/abs/1312.0563 | 到达/撤单强度依赖队列大小状态;小队列被耗尽概率高 | 队列耗尽率、补充率 | L1/L2 队列量 | 队列小 → 撤单/耗尽加速 | Queue depletion / fill prob |
| L10 | The market maker's dilemma: navigating the fill probability vs. post-fill returns trade-off | Albers, Cucuringu, Howison, Shestopaloff | 2025 | arXiv 2502.18625 (Binance BTC 永续实盘) | https://arxiv.org/abs/2502.18625 | 成交概率与成交后收益负相关;队首 1s markout −0.06bp,队尾 −0.78~−1.16bp;顺失衡 maker 只有队首才不亏 | queue position、近侧/对侧队列量 | L2 + 实盘成交 | 逆向失衡侧成交率>80% 但 markout 最差 | Adverse selection / queue |
| L11 | Flow toxicity and liquidity in a high-frequency world | Easley, López de Prado, O'Hara | 2012 | RFS 25(5) | https://doi.org/10.1093/rfs/hhs053 | 成交量同步桶的买卖失衡 = 知情概率;高 VPIN 时提供流动性亏损 | VPIN | 逐笔成交 | 高毒性 → 扩价差/缩量/停挂 | Toxicity |
| L12 | Hawkes model for price and trades high-frequency dynamics | Bacry, Muzy | 2014 | Quantitative Finance 14(7) | https://arxiv.org/abs/1301.1135 | 成交与价格跳变自激/互激聚簇 | 成交强度、成交聚簇(短窗计数) | 逐笔成交 | 被吃后同向再吃概率上升 | Toxicity / refill timing |
| L13 | Optimal quoting under adverse selection and price reading | Barzykin, Bergault, Guéant, Lemmel | 2025 | arXiv 2508.20225 | https://arxiv.org/abs/2508.20225 | 知情流存在时最优报价按 alpha 信号与库存偏斜 | 信号加权公允价 + 库存偏斜 | 信号 + 库存 | 毒性方向加陡偏斜 | Skew |
| L14 | Explainable patterns in cryptocurrency microstructure | Bieganowski, Ślepaczuk | 2026 | arXiv 2602.00776 (Binance 永续 2022–2025) | https://arxiv.org/abs/2602.00776 | 簿/流特征对短期收益的预测跨资产稳定;maker 固定深度回测可验证 | OFI、价差、逆向选择相关特征 | 1s 簿 + 成交 | 跨资产一致 | Factor 普适性 |
| L15 | Trading in the sunshine or in the shade: market impact and adverse selection on Hyperliquid | Barone, Lillo | 2026 | arXiv 2606.15715 | https://arxiv.org/abs/2606.15715 | 永续市场隐藏元订单执行期间同向流动性提供者承受额外逆向选择 | 持续同向主动流(元订单探测) | 逐笔成交 | 同向流持续 → 被动成交更毒 | Toxicity |
| L16 | Optimal adaptive market making in perpetual futures markets | Zeng, Liu | 2026 | arXiv 2607.11888 | https://arxiv.org/abs/2607.11888 | 做市利润 = 价差收入 − 逆向选择 − 库存成本 − 对冲摩擦 − 资金费;撤单延迟依赖队列位置 | 自适应价差、库存分布 | 理论 | 存在盈利/亏损相变区 | Framework |
| L17 | Algorithmic and High-Frequency Trading | Cartea, Jaimungal, Penalva | 2015 | Cambridge UP | ISBN 9781107091146 | 短期 alpha 信号进入做市报价;逆向选择下的最优挂撤 | 带 alpha 的 HJB 做市 | — | 报价随信号平移 | Fair value / skew |
| L18 | Optimal high-frequency trading with limit and market orders | Guilbaud, Pham | 2013 | Quantitative Finance 13(1) | https://arxiv.org/abs/1106.5040 | 限价+市价联合控制;大 tick 下只在盘口或盘口内一档报价 | 库存超限市价减仓 | — | 尾部库存用 taker 回中性 | Inventory |

## 文献 → 候选因子映射

| factor_id | name | formula | source | economic_hypothesis | required_data | window | normalization | expected_horizon |
|---|---|---|---|---|---|---|---|---|
| F01 | imb1 | (bq1−aq1)/(bq1+aq1) | L05/L06 | 队列失衡预示下一 mid 变动方向;买单在 imb<0 时成交更毒 | L1 | 即时 | 无量纲 | 100ms–1s |
| F02 | imb5 | (Σbq1..5−Σaq1..5)/(Σ) | L04 | 深档失衡补充 L1 | L2 5 档 | 即时 | 无量纲 | 250ms–1s |
| F03 | depth_conc | bq1/Σbq1..5(买侧),aq 同 | L09 | 顶档集中度低 → 顶档易耗尽 | L2 | 即时 | 无量纲 | 100ms–1s |
| F04 | depth_slope | Σq5/(档距 tick 数) | L04 | 簿斜率 = 冲击弹性 | L2 | 即时 | BTC/tick | 250ms–1s |
| F05 | spread_ticks | (ba−bb)/tick | L06 | 价差>1 tick 时挂盘口内可赚价差 | L1 | 即时 | tick | — |
| F06 | ofi_w | Σe_k 窗 w∈{100ms,500ms,1s,5s} | L03 | 线性预测 mid 变动 | L1 事件 | w | ÷ 顶档均量 | 100ms–5s |
| F07 | tflow_w | Σ signed trade qty 窗 w∈{1s,5s,30s} | L12/L15 | 主动流持续 → 同向继续 | 成交 | w | ÷ 窗成交总量 或 ÷顶档均量 | 1s–30s |
| F08 | trade_int_w | 成交笔数/窗 | L12 | 爆发期逆向选择重 | 成交 | 1s/10s | 相对日中位 | 100ms–1s |
| F09 | arr_int | L1 事件数/秒 | L09 | 活跃度 | L1 | 1s | 相对日中位 | — |
| F10 | cancel_bid/ask_w | 顶档非成交减量(撤单)累计/窗 | L09/L07 | 撤单加速 = 队列即将耗尽 | L1 + 成交 | 500ms/2s | ÷ 顶档均量 | 100ms–1s |
| F11 | cancel_imb | (cancel_ask − cancel_bid)/(和) | L09 | 一侧撤单占优 → 该侧价位塌 | 同上 | 2s | 无量纲 | 250ms–1s |
| F12 | cancel_trade_ratio | 撤单量/成交量 窗 | L09 | 撤单主导 vs 成交主导的耗尽 | 同上 | 2s | 无量纲 | — |
| F13 | q_depl_rate | 1 − bq1(t)/bq1(t−w) 同价位 | L09 | 耗尽速度 | L1 | 200ms/1s | 无量纲 | 100ms–1s |
| F14 | q_ahead | 下单瞬间该档量(BTC) | L07/L10 | 队列越长成交概率越低、成交越毒 | L1 | 即时 | BTC 或 $ | — |
| F15 | q_turnover | 窗内该价成交量/顶档量 | L07 | 队列周转 | L1+成交 | 5s | 无量纲 | — |
| F16 | ret_w | mid(t)−mid(t−w) 窗 1s/5s/30s | L17 | 动量/反转 | L1 | w | bp | 100ms–1s |
| F17 | vol_w | mid 变动 std 窗 10s/60s | L01 | σ 进入价差 | L1 | w | bp | — |
| F18 | spread_chg | spread(t)−spread(t−1s) | L06 | 价差拉开 = 流动性撤离 | L1 | 1s | tick | — |
| F19 | depth_chg | Σq5(t)/Σq5(t−1s) | L09 | 深度塌陷 | L2 | 1s | 无量纲 | 100ms–1s |
| F20 | trade_cluster | 最近 100ms 内成交笔数 / 距上笔成交时间 | L12 | Hawkes 聚簇 | 成交 | 100ms | 计数 | 100ms–500ms |
| F21 | vpin | 成交量桶 |买−卖|/桶量 滚动均值 | L11 | 毒性 | 成交 | N 桶 | 无量纲 | 分钟级 |
| F22 | xlead_okx | okx_mid(t) − ku_mid(t) | 跨所 lead-lag(L17 alpha 框架) | 领先所价格差 = 可预测的 mid 变动 | OKX BBO | 即时 | bp/tick | 100ms–1s |
