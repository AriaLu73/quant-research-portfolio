<!-- v2 定稿 2026-11-06。用户裁决：Part B 库存管理与 T=300 s 段末清算全部按 P2 字面；Part A 交易日边界 UTC 00:00；Step 16 校准 P2 的 L。 -->
Task: Exact Paper Reproduction + Extensions — Adaptive Optimal Market Making
你是一名 HFT Quant Researcher。本任务分两部分：
Part A（Step 1–11）：严格复现论文 P1。
Part B（Step 12–16）：针对 P1 的五处不足做修改实验。Part B 的库存管理与市价单全部按论文 P2，P1 只保留需求与到达概率的估计方法。
Part A 没有通过验证之前不得进入 Part B。

论文：
P1 = Chávez-Casillas, Figueroa-López, Yu, Zhang, "Adaptive Optimal Market Making Strategies with Inventory Liquidation Cost", SIAM J. Financial Math. 15(3), 2024. DOI 10.1137/23M1571058。
P2 = Guilbaud, Pham, "Optimal high frequency trading with limit and market orders", arXiv:1106.5040v1, 2011。

本地环境（已核实，直接使用，不要另找）：
* 回测引擎：scripts\research7\l3sim.py（按 L3 进簿序号精确排队；每张模拟单带 ahead0 = 进簿时同价前方量、ahead = 存活期间前方量；Latency(fixed_ms=L) 固定延迟，下单与撤单同路径；post-only 检查；引擎审计见 research_mm/reports/01_engine_audit.md）。
* 费率：research_mm/config/fees.yaml（maker 我方费率，taker 我方费率，我方费率档）。
* 延迟：research_mm/config/latency.yaml（实测 p50 1.8 ms、p99 3.8 ms；网格 {1.8, 3.8, 10, 25}；用户 2026-10-03 定回测口径：正常 1.8 ms、拥堵 50 ms）。
* 数据切分：research_mm/config/data.yaml（XBTUSDTM，train / validation / final_test 已冻结；final_test 只许运行一次，所有校准只能用 train + validation）。
* 自录 L3：data/kucoin_l3/20260922、data/kucoin_l3_btc/20260924、data/kucoin_l3_btc/20260925（XBTUSDTM 与 XBTUSDCM 的 l2 / l3 / snap / trades）。
* 品种：XBTUSDTM、XBTUSDCM、ETHUSDTM、ETHUSDCM（用户 2026-11-06 指定）。合约规格（公开合约接口 2026-11-06 查询）：XBTUSDTM tick 0.1、一张 0.001 BTC；XBTUSDCM tick 0.1、一张 0.0001 BTC；ETHUSDTM tick 0.01、一张 0.01 ETH；ETHUSDCM tick 0.01、一张 0.001 ETH。USDC 合约一张是同币种 USDT 合约的十分之一，所有以张数计的参数按合约分别定。
* 费率（《KuCoin Market Maker Program Ver. April 2026》PDF 第一页费率表，与 fees.yaml 一致）：USDT 合约 maker 我方费率 / taker 我方费率；USDC 合约 maker 我方费率（PDF 单列 "All USDC futures pairs"）/ taker 我方费率（PDF 未单列 USDC taker，按期货 我方费率档 通用档）。
* 数据覆盖：自录 L3 只有 XBTUSDTM 与 XBTUSDCM；ETHUSDTM / ETHUSDCM 只有 L2。Step 14 的排队实测只能在两个 BTC 合约上做，ETH 两个合约在报告中标"无 L3，未测"，不得用 L2 估计代替。
* 虚拟订单量 (V_{LO})：按 P1 Section 2.1 "average volume of submitted LO" 的定义，每个合约在 data.yaml 的 train 区间内，取 L3 新挂单（level3v2 open 消息）中落在盘口前 5 档的张数中位数；同时报均值、p25、p75、p99 和折合美元。取中位数而非均值是因为分布极重尾（2026-09-25 07 时一小时预览，未按前 5 档过滤：XBTUSDTM 448,062 笔，均值 704 张、中位数 178 张、p25 2 张、p99 4,774 张；XBTUSDCM 15,702 笔，均值 782、中位数 149、p99 24,476）。ETH 合约无 L3，用 L2 各档数量的正增量作为新挂单的代理，标明是代理。所有用到 (V_{LO}) 的步骤加 {0.5×, 1×, 2×} 敏感性。
* 期限 T：Part A 按 P1，T = 交易日结束；BTC 永续没有收盘，Part A 的交易日边界取 UTC 00:00（用户 2026-10-14 日终结算口径）。Part B 按 P2，T = 300 s（P2 Table 4c），见 Step 13。

通用要求：论文没有给出数值或没有指定做法的地方，一律在"工程选择登记表"里写明：论文原文位置、论文留空的内容、你的选择、选择理由。不得把自己的选择写成"与论文一致"。任何阈值、参数都要写来源：来自论文、来自配置文件、或来自本任务内的标定实验；不许凭感觉填。遇到本文件没定、论文也没定的项，停下来问用户，不自己填。

=====================================================================
Part A — 复现 P1
=====================================================================

Step 1 — 复现论文的事件定义（Section 2.1, Eq. 1–2）
论文采用离散时间决策：
[
t_k=k\Delta t,\quad \Delta t=1\text{ second}
]
首先从现有市场数据提取每秒的：

* Buy Market Order arrival indicator (1^+_{t_k})
* Sell Market Order arrival indicator (1^-_{t_k})
* Buy/Sell Market Order Volume
* Reference Midprice (S_{t_k})
* 各价位的可见订单簿深度

论文的 arrival indicator 表示一个时间区间内是否至少有一笔对应方向的 Market Order 到达，而不是该区间的 Market Order 数量。
论文假设 (t_0) 之前有足够长的 burn-in，使 (\boldsymbol e_{t_0}) 可定义（Section 2.1，Eq. 2 之后）。窗口开始之前的指标从哪一段数据取，写入工程选择登记表。
检查事件方向、时间窗口边界，以及 Order Book 数据质量。尤其确保订单簿状态和交易事件对应，不使用未来盘口信息。
先输出按秒组织的事件序列，验证 arrival frequency、joint arrival frequency 和成交量分布。
[修改 1] 事件提取代码必须以 (\Delta t) 为参数，Step 12 会用 100 ms / 250 ms / 500 ms / 2 s 重跑本步。
不要进入后续模型，直到这个事件定义验证通过。

Step 2 — 复现随机 Demand Function（Eq. 4–5, Section 3.1.2）
论文的核心模型：
[
Q^\pm_{t_{k+1}}=1^\pm_{t_{k+1}}c^\pm_{t_{k+1}}
(p^\pm_{t_{k+1}}-L^\pm_{t_k})
]
这里 (c^\pm,p^\pm) 是随机变量。
必须严格复现 Section 3.1.2 的估计方法，而不是直接假设一个成交概率函数。
对于每一个历史 1 秒区间：

1. 在中价以上（ask 侧）/ 以下（bid 侧）的各个价位 (P_\ell) 假设放置一笔虚拟 Limit Order，订单量为 (V_{LO})。
2. 使用该区间真实发生的 Market Orders，计算每个价位对应的可成交数量。
3. 按论文的定义，单次 Market Order 对虚拟订单的成交量为：

[
\min\bigl(\max(V_{MO}-V_L,0),V_{LO}\bigr)
]
其中 (V_L) 为价格严格优于 (P_\ell) 的可见挂单量（ask 侧为价格低于 (P_\ell) 的卖单量），不含 (P_\ell) 同价位的队列。按照论文假设（脚注 5），虚拟订单在其价位处具有队列优先权。[修改 3] 这一假设在 Step 14 用 L3 数据实测检验；本步按论文原样执行。

4. 按论文方法将区间内的成交需求汇总：(Q_\ell=\sum_{\text{all MO}}\min(\max(V_{MO}-V_L,0),V_{LO}))，得到各个报价位置对应的 Demand Curve。
5. 对 Demand 和价格水平做 Weighted Linear Regression，响应变量为 (Q_\ell)，自变量为 (P_\ell)，靠近 Midprice 的价位给予更高权重。
6. 从回归结果恢复随机需求参数：(\hat c^\pm) = 回归斜率的绝对值，(\hat p^\pm) = 截距/斜率换算成相对 (S_{t_k}) 的距离。写明所用坐标（价格水平或报价距离）及换算公式。

注意：

* Demand Curve 是每个窗口估计一次，不是整个交易日只拟合一条曲线。
* 不能用平均需求曲线替代随机需求参数。
* 检查论文 Section 3.1.2 的成交量汇总方式，不能擅自改变其队列和订单量假设。
* 对回归斜率、截距、参数符号和异常窗口做验证。
* 论文未完整指定的工程细节，应明确记录选择，不得伪称完全一致。本步至少包括以下四项：
  (a) 回归权重函数：论文只说"靠近 midprice 的价位权重更高"。
  (b) (V_{LO}) 的数值：论文只说"typically set to be the average volume of submitted LO"（Section 2.1），没有给 MSFT 的具体值。
  (c) (V_L) 的取法：在 (t_k) 时刻取一次，还是在每笔 MO 到达时按当时盘口取。论文未说明。
  (d) 论文公式按每笔 MO 单独以 (V_{LO}) 封顶后求和，整秒累计成交量可以超过 (V_{LO})。是否按字面执行，写明。
* 估计 ((\hat c^\pm,\hat p^\pm)) 只在该侧 (1^\pm_{t_{\ell+1}}=1) 的区间进行。原因见 Step 3 第一条。

复现 Figure 3（单个 1 秒区间的实际需求与线性拟合）和 Figure 6（某一天所有 1 秒区间的平均需求曲线，叠加以 ((\hat c,\hat p)) 日均值画出的直线）。

Step 3 — 估计随机 Demand 的 Moments（Eq. 7–8, 48）
使用每个训练窗口中估计的 ((c^\pm,p^\pm))，按论文定义计算最优报价所需的矩：
[
\mu^\pm_{c^mp^n}=E[(c^\pm)^m(p^\pm)^n\mid 1^\pm=1]
]
注意论文内部口径不一致：Eq. (8) 定义为以 (1^\pm=1) 为条件的期望，而 Eq. (48) 字面上是对训练窗口全部秒求平均、N 为全部秒数。无 MO 的秒上需求曲线全为 0，回归得 (c=0)、(p) 无定义。本复现按 Eq. (8) 执行：只对 (1^\pm=1) 的区间求平均。把这一差别写入工程选择登记表。
包括必要的：

* (\mu_c^\pm)
* (\mu_p^\pm)
* (\mu_{cp}^\pm)
* (\mu_{c^2}^\pm)
* (\mu_{c^2p}^\pm)
* (\mu_{c^2p^2}^\pm)

具体使用哪些矩，严格依据论文的递推公式 (17)–(21)，不要多造模型参数。
使用测试日前 20 个交易日的历史数据估计，禁止使用测试日期的数据进行校准。本地数据不足 20 天时，按 data.yaml 的 train 区间估计并报告差异。
复现 Table 1 的统计结构。注意论文 Table 1 的构造是：对 252 天逐日估计 (\hat\mu^\pm_{c^mp^n})，再对 252 个日估计取平均，不是 20 天训练窗口的结果。特别检查：

* Buy/Sell 两侧参数是否接近（Eq. 33）。
* Demand slope 的随机性是否显著（论文：slope 标准差约为均值的 200%）。
* (c,p) 的相关性（论文：约 20%），以及 (\mu_{cp}) 与 (\mu_c\mu_p)、(\mu_{c^2p}) 与 (\mu_{c^2}\mu_p) 的差距（Eq. 35）。
* Proposition 6 所需假设是否合理。

如果现有数据不是 MSFT 2019，则与 Table 1 比较统计性质，不要求数值相同。

Step 4 — 复现 Adaptive Arrival Probabilities（Eq. 45–47）
这是论文最重要的 Adaptive 机制。
必须精确实现论文定义的三个状态函数。
g1：最近 3 个区间的买卖单分别编码
[
g_1(e_t)=
(I_t^+,I_t^-,I_{t-1}^+,I_{t-1}^-,
I_{t-2}^+,I_{t-2}^-)
]
共 64 种可能状态。
g2：最近 3 个区间的买卖到达指标求和
[
g_2(e_t)=
(I_t^++I_t^-,\ldots,
I_{t-2}^++I_{t-2}^-)
]
共 27 种可能状态。
g3：最近 4 个区间的买卖到达指标求和
[
g_3(e_t)=
(I_t^++I_t^-,\ldots,
I_{t-3}^++I_{t-3}^-)
]
共 81 种可能状态。
随后按 Eq. (46)–(47)，在历史训练窗口中通过条件频率估计：
[
\pi^+(s)=P(I_{t+1}^+=1\mid g(e_t)=s)
]
[
\pi^-(s)=P(I_{t+1}^-=1\mid g(e_t)=s)
]
[
\pi^{11}(s)=P(I_{t+1}^+=1,I_{t+1}^-=1\mid g(e_t)=s)
]
构造完整的四种联合到达事件概率 (P(0,0),P(1,0),P(0,1),P(1,1))，对应论文 Eq. (9)。
实现并验证这些状态的转移函数 (\Gamma)，尤其确保 (g_2,g_3) 的压缩状态在新到达事件下仍可正确更新；参考论文 Assumption 4 和 Section 2.7。
输出：

* 各状态样本量。
* 各状态条件到达概率。
* 概率合法性检查。
* g1/g2/g3 的对比。
* Figure 4 类型的条件概率图（(\pi^\pm) 对 g3 的各状态）。
* Figure 5 类型的预测到达率与实际到达率移动平均对比。按论文 Remark 5：(\hat\pi^+) 用 g1 计算；(\mathcal M_k) 和 (\mathcal P_k) 是 (t_{k-250}) 到 (t_{k+250}) 的 501 点双侧窗。该图是双侧窗诊断图，含未来指标，不得用于策略。

对样本不足的状态报告问题，不要悄悄修改原论文的估计方法。

Step 5 — 实现 Bellman Recursion（Eq. 10–22）
论文的目标函数为：
[
\max E[W_T+S_TI_T-\lambda I_T^2]
]
采用二次型 Value Function：
[
V_t=W_t+S_tI_t+\alpha_tI_t^2+h_tI_t+g_t
]
终端条件（Theorem 1(i)）：(\alpha_{t_{N+1}}=-\lambda)，(h_{t_{N+1}}=g_{t_{N+1}}=0)。
先复现 Martingale Midprice Case。
必须实现：

* Eq. (11)–(12)：Inventory 和 Cash 更新。
* Eq. (14)–(16)：Value Function 和 Bellman Equation。
* Eq. (3)、(43)、(A.6)：一步前瞻量 (\alpha^0_{t_{k+1}},\alpha^{1\pm}_{t_{k+1}},\alpha^{1,1}_{t_{k+1}},h^0_{t_{k+1}},h^{1\pm}_{t_{k+1}})。它们是对下一状态取条件期望得到的，例如
  [
  \alpha^{1+}_{t_{k+1}}(s)=\sum_{\ell\in\{0,1\}}\Lambda(\Gamma(1,\ell,s))\,\frac{P(1^+=1,1^-=\ell\mid s)}{\pi^+(s)}
  ]
  不得用 (\alpha_{t_{k+1}}) 本身代入 Eq. (17)–(18)。
* Eq. (17)：(\rho^\pm,\psi^\pm,\gamma)。
* Eq. (18)：最优报价系数。
* Eq. (19)–(21)：(\alpha,h,g) 的 Backward Recursion。
* Eq. (22)：Optimal Bid/Ask Placement。
* Corollary 3 与 Theorem 4 对应的解和正确性条件。

重要：不能把论文的 Bellman Recursion 简化成经典 Avellaneda–Stoikov 公式。
必须保留：

* 随机 Demand Moments。
* 买卖订单联合到达概率。
* 状态相关的未来 Value Function。
* Inventory-dependent Quoting。

编写数学单元测试，至少包括：
* Lemma 2：对所有 (k) 和所有状态，(\alpha^0_{t_{k+1}}<\alpha_{t_k}<0)。
* (A.12)：对所有 (k) 和所有状态，(\gamma_{t_k}<0)。
* (^{(1)}A^\pm_{t_k}<0)（Corollary 3 后第 2 条）。
* 对于一个很短的时间范围，通过独立数值优化 Bellman 目标（A.5 的二次型），检验解析报价是否确实取得最优值。

Step 6 — 复现 Offline Policy Catalog（Section 2.7）
论文不是每秒重新求解整个动态规划。
利用各状态的到达概率和状态转移关系，从交易终点向前递推，为每个时间点、每个 g-state 预计算最优报价系数。
这一步必须实现 Section 2.7 的 Policy Catalog：
[
Policy[t,s]\rightarrow
\text{Optimal Quote Coefficients}
]
在线回测时：

1. 观察当前订单流历史。
2. 计算当前状态 (s=g(e_t))。
3. 查询对应时间和状态的 Policy Coefficients。
4. 根据当前 Inventory 计算 Bid/Ask。
5. 按论文的价格有效性规则转换为可执行报价。论文规则（Section 2.2 Definition 1 之后、Section 3.1.1）：若 (a_{t_k}<b_{t_k})，或 (a_{t_k}) 低于中价、(b_{t_k}) 高于中价，则把对应报价放到中价上方/下方紧邻的一个 tick。一般情况下如何取整到 tick 网格，论文未说明，写入工程选择登记表。

确保状态转移和系数递推完全一致。
分别为 g1、g2、g3 生成 Policy Catalog，并验证同一库存下不同状态的最优报价差异。

Step 7 — General Midprice Case（Section 2.3, Eq. 31）
在 Martingale Case 验证成功后，再复现非鞅价格过程下的最优报价。
按论文 Theorem 5 和 Eq. (31) 实现未来价格变化预测对报价的调整。
不要自行设计复杂 Alpha 模型。
先使用论文 Eq. (49)：
[
\hat\Delta_t=\frac{S_t-S_{t-5}}{5}
]
即最近 5 个一秒价格增量的均值。
与论文一致，仅保留当前的一步预测项，将更远未来的预期价格增量设为零（Section 3.1.3）。Eq. (31) 中 (\Delta) 的系数 ((\rho^\pm-\psi^\pm)/(2\gamma)) 按 Eq. (44) 对每个时间和每个状态预先计算进 catalog。
比较：

* Martingale Model：不使用 Price Forecast。
* General Midprice Model：使用 Eq. (49)。

确保价格预测只使用当前时刻已经观察到的价格。

Step 8 — 复现论文的回测设置（Section 3.2）
使用现有回测引擎和 Order Book。
论文原始实验配置：

* 股票：MSFT。
* 数据：2019 Nasdaq TotalView-ITCH 5.0。
* Order Book：前 20 档。
* 每日交易时间：10:00–15:30。
* 决策间隔：1 秒。
* 每侧每天 19,800 次报价决策。
* 训练窗口：前 20 个交易日。
* 测试天数：232 天（首个测试日为 2019 年第 21 个交易日 1 月 30 日）。
* Terminal Inventory Penalty：(\lambda=0.0005)。[修改 5] 该值的单位是美元/股²，来源是预印本 Capponi–Figueroa-López–Yu (2021) §5.2 对 MSFT 的"平均流动性成本"。Part A 为了复现用它跑并标注"MSFT 值，仅作复现对照"。Part B 不使用 (\lambda)，库存管理与清算成本全部按 P2（Step 13、Step 16）。
* 参考价 (S_{t_k}) = 中价（Section 3.1.3）。
* 虚拟订单量 (V_{LO})：论文未给数值，沿用 Step 2 登记的选择。

如果本地数据不匹配，沿用对应的实验逻辑并报告差异。不要强行使用 MSFT 特定参数套到其他资产。
在每个测试日：

1. 利用前 20 个交易日的数据校准 Demand Moments 和 Arrival Probabilities。
2. 对所有状态执行 Backward Recursion，构建当天的 Policy Catalog。
3. 按时间向前运行策略。
4. 每秒根据真实订单流历史和当前 Inventory 计算最优 Bid/Ask。
5. 根据该秒内真实 Market Order Flow 和 Order Book 状态模拟虚拟订单的实际成交量，成交规则与 Step 2 第 3–4 条相同（脚注 6），(V_L) 取法和 (V_{LO}) 封顶方式与 Step 2 登记的选择一致。
6. 更新 Cash 和 Inventory：(W_{t_{k+1}}-W_{t_k}=a_{t_k}\tilde Q^+_{t_{k+1}}-b_{t_k}\tilde Q^-_{t_{k+1}})，(I_{t_{k+1}}-I_{t_k}=-\tilde Q^+_{t_{k+1}}+\tilde Q^-_{t_{k+1}})。
7. 在交易终点计算策略表现。

注意区分：
拟合的随机 Demand Model 用于求最优控制，真实历史订单流用于回测成交。
不要直接用随机模型抽样出来的成交量代替论文的历史事件回放结果。
原论文假设虚拟订单在同价位具有队列优先权，应作为 Paper-Faithful Simulation 保留。
[修改 3] l3sim.py 有精确的 L3 排队模型。Part A 的论文忠实回测（脚注 5/6 队首假设）和 Step 14 的 l3sim 回测是两套成交规则，结果必须分开报告，不能混为一谈。

Step 9 — 复现 Terminal Liquidation
计算论文的理论目标：
[
J_T=W_T+S_TI_T-\lambda I_T^2
]
同时使用终点真实 LOB 深度，估计剩余 Inventory 通过 Market Order 清算后的现金流：
[
PnL_T=W_T+\bar S_T I_T
]
其中 (\bar S_T) 是考虑订单簿深度后的平均清算价格，卖出库存与买回空头应使用对应盘口方向。
验证这两种计算方式，并复现论文 Table 2 和 Table 3 的对比逻辑。[修改 5] 本步的 (W_T+\bar S_TI_T) 与 (W_T+S_TI_T) 之差（实际清算成本）按 (I_T) 分桶保存，Step 16 用它对照 P2 的清算函数 L。

Step 10 — 按论文 Table 2–7 逐组实验
严格按以下顺序运行。
Experiment A — Table 2/3
比较四种 Optimal Policies：

1. Martingale + g1
2. Martingale + g2
3. Martingale + g3
4. General Midprice + g3

同时加入论文的 Fixed-Level 1–6 报价基准（Level i：双侧始终挂在盘口第 i 个 tick 深度）。
报告理论终端目标和实际盘口清算 PnL 的 Mean、Std。
Experiment B — Table 4/5
复现 Non-Adaptive Arrival Model。
论文使用的是历史数据校准的、关于日内时间的确定性二次到达概率函数，而不是简单把 (\pi) 设为全天常数。该策略来自预印本 Capponi, Figueroa-López, Yu (2021)，本文没有给出二次函数的拟合方式；查预印本，查不到则把拟合方式写入工程选择登记表。
Table 4/5 有三列，全部复现：
1. 非鞅价格 + (\pi(1,1)\ge 0)
2. 鞅价格 + (\pi(1,1)\ge 0)
3. 非鞅价格 + (\pi(1,1)\equiv 0)
比较 Adaptive 与 Non-Adaptive 策略。
Experiment C — Table 6/7
将随机需求参数 (c,p) 替换为训练窗口估计的均值，构建 Deterministic Demand Model（此时 (\mu_{c^2}=\mu_c^2)、(\mu_{cp}=\mu_c\mu_p)、(\mu_{c^2p}=\mu_c^2\mu_p)、(\mu_{c^2p^2}=\mu_c^2\mu_p^2)）。
重新计算最优 Policy，而不是仅在成交模拟阶段替换随机需求。
Table 6/7 的四列与 Table 2/3 相同：Martingale + g1/g2/g3，General Midprice + g3。
比较 Stochastic Demand 与 Deterministic Demand 对最优报价和 PnL 的影响。
所有实验使用相同测试日期及可比的成交规则。

Step 11 — 结果验证
至少生成：

* Table 1：需求参数及其矩。
* Figure 4：状态相关的 Arrival Probabilities。
* Figure 5：预测与实际 Order Arrival 的移动平均。
* Figure 6：随机 Demand Curve 的拟合。
* Table 2/3：Adaptive Optimal Strategies。
* Table 4/5：Non-Adaptive Strategies。
* Table 6/7：Deterministic Demand Strategies。
* 工程选择登记表（全部 Step 汇总）。

另外验证：

* Inventory 和 Cash 更新公式。
* Optimal Quotes 的 Bid/Ask 方向。
* Quote 随 Inventory 变化的方向。
* Quote 随状态变化的行为。
* Probability Consistency。
* Lemma 2 与 (A.12) 在全部时间和状态上成立。
* Terminal Liquidation。
* 数据及模型的时间因果性。

如果结果和论文不一致，要区分数学实现错误、数据差异、需求估计差异和成交模型差异。
不要仅通过 PnL 正负判断复现是否正确。
Part A 通过后才能开始 Part B。

=====================================================================
Part B — 针对 P1 不足的修改实验
=====================================================================

Part B 所有实验共用：相同的交易日期（data.yaml 的 train + validation；final_test 只在全部实验定稿后运行一次）、相同的风险预算（按 P2：同一 (\gamma)，不设最大库存，(y_{\min},y_{\max}) 只作数值网格截断，P2 Table 4b / 4c）、相同的订单规模 (V_{LO})。
Part B 的库存管理全部按 P2：不使用 P1 的终端惩罚 (\lambda I_T^2)，不使用 P1 的终端条件 (\alpha_T=-\lambda)，不使用 P1 Section 2.6 / Theorem 10，不使用 P1 的交易日期限。P1 在 Part B 里只保留三样估计量：Step 2–3 的随机需求 ((c^\pm,p^\pm)) 及其经验分布、Step 4 的自适应到达概率与 g-state 转移、Step 7 的 Eq. (49) 一步预测。
每组实验必须有对照组和实验组，报数先写是哪个方案。对照组两类：P1 原版（Part A 的结果）和 P2 自己的基准（WoMO、常量贴盘口 (\alpha^c)、随机 (\alpha^r)，P2 Section 4）。笔数旁边必须同时给成交额与 $/h。

Step 12 — 决策间隔敏感性实验 [修改 1]
P1 规定 (\Delta t=1) s，对此提出疑问。比较的时间尺度：

| (\Delta t) | 状态 |
|---|---|
| 100 ms | 待检验 |
| 250 ms | 待检验 |
| 500 ms | 待检验 |
| 1 s | 论文基准 |
| 2 s | 待检验 |

每个 (\Delta t) 都必须从 Step 1 起重新走一遍：重新提取到达指标、重新估计条件到达概率 (\pi^\pm(s),\pi^{11}(s))（Step 4）、重新估计每个区间的需求参数与矩（Step 2–3）、重新做 Backward Recursion 和 Policy Catalog（Step 5–6）、重新回测（Step 8–9）。不能把 1 秒的概率模型机械换算成 100 ms 模型（例如把 (\pi) 除以 10）。
敏感性对 Part A 的 P1 策略和 Part B 的 P2 策略都做。每个 (\Delta t) 报告：Part A 的 Catalog 长度 (N=T/\Delta t)；Part B 的步数 (300\ \mathrm{s}/\Delta t)（100 ms → 3,000 步，2 s → 150 步）；(\pi(1,1)) 的量级、每区间无 MO 的比例、(c,p) 估计的有效样本量。
评价指标，逐项回答对应问题：

| 评价指标 | 想回答的问题 |
|---|---|
| 样本外净 PnL（含 fees.yaml 费率） | 哪种间隔真正赚钱？ |
| MO 到达概率的预测质量：对下一区间 (1^\pm) 的 log-loss / Brier，分 g1/g2/g3；Figure 5 型对比 | 哪种时间尺度保留了更多信息？ |
| Adverse selection：被动成交后 1 ms、10 ms、100 ms、1 s、5 s 的 markout（用户 2026-10-20 关卡口径） | 更快更新能否减少被动成交后的价格损失？ |
| Fill rate、库存波动（(\mathrm{std}(I_t))、(\max|I_t|)、持仓段时长分布） | 成交效率与库存风险如何变化？ |
| 撤单次数、队列位置损失（Step 14 的 l3sim 口径：改价撤单后重新进簿的 ahead0 与原位置的差） | 更高频率是否反而损害真实执行？ |

对 100/250/500 ms 的回测同时跑论文忠实成交（脚注 5/6）和 l3sim 两套，分开报。
输出 Table 8（五个 (\Delta t) × 五类指标 × g1/g2/g3）。

Step 13 — 库存管理全部按 P2 [修改 2]
Part B 的控制问题是 P2 的，不是 P1 的。P1 只提供执行模型的估计量（见 Part B 开头）。

1. 目标函数：P2 Eq. (3.1)–(3.2)，mean 判据 (U(x)=x)、(g(y)=y^2)：
   [
   \max E\bigl[L(X_T,Y_T,P_T,S_T)-\gamma\int_0^T Y_t^2\,dt\bigr],\qquad
   L(x,y,p,s)=x+yp-|y|\tfrac{s}{2}-\varepsilon\ \text{（P2 Section 3.1）}
   ]
   离散化：积分换成 (\gamma\sum_k Y_{t_k}^2\Delta t)。写明这是对 P2 连续时间的离散化。
2. 期限：(T=300) s（P2 Table 4c）。数据按连续不重叠的 300 s 段切分；每段起始 (X_0=0)、(Y_0=0)（P2 Table 4d），段末按 L 用市价单清算，段与段之间不延续库存。这是 P2 的字面设定。报告里必须另给两项：段内持仓段时长分布、段末被清算的库存量分布；段末清算量大说明库存没有在段内消掉。
3. 状态变量：时间 (t_k)、库存 (Y)、点差状态 (s)、P1 的 g-state。点差按 P2 Section 2.1 建成 Markov 链：在 train 区间按 P2 Eq. (2.6) 估计转移矩阵 (\rho_{ij})、按 Eq. (2.7) 估计时钟强度 (\lambda(t))（P2 用每小时分段常数），档数 (m) 取有足够样本的点差档，写明。
4. 控制：
   * 挂单 = P1 的报价距离 (L^\pm)（连续变量）。执行按 P1 的随机需求 (Q^\pm=1^\pm c^\pm(p^\pm-L^\pm))，到达概率 (\pi^\pm(g),\pi^{11}(g)) 来自 Step 4，((c,p)) 的经验分布来自 Step 2。这一处是用 P1 的执行模型替换 P2 Section 2.2 的 Cox 强度 (\lambda^{a,b}(q,s))，写入工程选择登记表。
   * 市价单 = P2 的脉冲控制 ((\tau_n,\zeta_n))，成本 (c(e,p,s)=ep+|e|\tfrac{s}{2}+\varepsilon)（P2 Eq. 2.4–2.5），taker 费按 P2 Remark 2.2 以比例费形式加入（USDT / USDC 合约都是 我方费率），(\varepsilon=0)（KuCoin 无固定费，写明）。市价单量上限 (\bar e) 写明来源。
5. 动态规划：P2 Eq. (3.5) 的拟变分不等式，离散时间写成
   [
   V_k=\max\Bigl\{\sup_{L^\pm}E[V_{k+1}\mid\cdot]-\gamma Y^2\Delta t,\ \ \sup_{e}V_k(x-c(e,p,s),\,y+e,\,p,\,s,\,g)\Bigr\},\qquad V_{N+1}=L(x,y,p,s).
   ]
   mean 判据下按 P2 Eq. (3.8) 化为 (V=x+yp+\phi(t_k,y,s,g))，只对 (\phi) 递推。终端 L 对 (y) 是 (|y|) 不是 (y^2)，P1 的二次 ansatz 不适用；(\phi) 在库存网格上数值求解（P2 Section 3.3：有限差分、(y) 网格）。挂单分支的 (\sup_{L^\pm}) 在每个网格点上数值求，期望 (E[\phi(y\mp Q)]) 用 Step 2 的 ((\hat c,\hat p)) 经验分布直接算，不只用矩。先脉冲后挂单的顺序是离散化选择，写入登记表。
   在 Step 7 的一步预测 (\hat\Delta_t) 非零时，P2 允许一般 Markov 中价（Section 2.1），把 (\hat\Delta_t\Delta t) 作为该步中价漂移加进 (E[V_{k+1}])，与 P2 Section 3.3 第 2 种情形的 (b\,dt) 对应。
6. 策略形状：按 P2 Figure 3 画 ((y,s)) 平面上的挂单区 M 与吃单区 T，分 (t) 远离 T 与接近 T 两张，再按 g-state 分面。
7. (\gamma) 的选法：P2 Section 4 的有效前沿。(\gamma) 扫描范围由本地数据的库存方差量级定，不许凭感觉填；用 NIR (=(m(X^\star_T)-m(X^c_T))/\sigma(X^\star_T)) 选，(X^c) 为 P2 的常量贴盘口基准 (\alpha^c)；报告每档 (\gamma) 的 (m,\sigma,\mathrm{IR},\mathrm{NIR})、(\max|Y|)、市价单笔数与成交额。
8. 单测与定性检查（P2 Section 4）：(\gamma) 增大时吃单区 T 扩大、(\max|Y|) 下降；T ≫ 1/λ 时远离 T 的策略近似时间不变；WoMO 基准（(\bar e=0)）由同一代码跑出；(\gamma\to 0)、(\bar e=0) 且终端改为 P1 的二次形时应退化回 Step 6 的 Catalog 报价（对拍）。

验收：用户 2026-10-21 / 11-06 的标准：持仓段 > 5 分钟的数量必须为 0，对照组同样统计。注意 300 s 段末清算会让这项自动为 0，所以第 2 条要求的两项分布必须一并报告。
输出 Table 9：{P1 原版，P2 WoMO，P2 完整} × (\gamma) 扫描各档，指标同 Step 12。

Step 14 — 脚注 5/6 队首假设的实测 [修改 3]
P1 的需求估计（脚注 5）和回测成交（脚注 6）都假设我方订单在同价位队首。用自录 L3 数据和 l3sim.py 测出在该策略下我方模拟排队到底在什么位置。

数据：data/kucoin_l3/20260922、data/kucoin_l3_btc/20260924、data/kucoin_l3_btc/20260925 的 XBTUSDTM，以及 data.yaml 的 train + validation 区间。
做法：
1. 把 Step 6 的 Policy Catalog（Part A 的 P1 策略）和 Step 13 的 P2 策略分别接到 l3sim 的 on_event 回调（接法参考 research_mm/src/adapters/sim.py 与 run_naive.py），延迟取 Latency(fixed_ms=1.8) 与 3.8 两档，每张单按引擎的 post-only 规则处理。
2. 每张模拟单记录：进簿时同价前方量 ahead0（张数，以及占该价位总量的比例）；存活期间 ahead 的轨迹；最终结局（成交 / 撤单 / 断流 lost）；成交时的 ahead；从进簿到成交的时间。
3. 报告 ahead0 的分布（分位数、按 (|L^\pm|) 分档、按 g-state 分档、按小时分档）；"进簿时 ahead0 = 0"的订单占比，这就是脚注 5/6 假设成立的比例。
4. 同一时段、同一报价序列下，比较三种成交量：(a) 脚注 5/6 队首假设的成交量（Step 8 的模拟器）；(b) l3sim 精确排队的成交量；(c) 把 (V_L) 改为"价格严格优于 + 同价位 L3 前方量"重新按 Step 2 公式算出的成交量。报告 (b)/(a)、(c)/(a) 的比值及其随 (|L^\pm|) 的变化。
5. 用 (c) 的口径重新估计 (c^\pm,p^\pm) 和矩，重新生成 Catalog，与 Part A 的 Catalog 对比最优报价差异。这是对照实验，标注"L3 队列口径"，不与 Part A 的论文忠实结果混报。
6. 改价撤单的代价：策略每次改价都放弃当前队列位置。统计每次改价时放弃的 ahead 与新进簿的 ahead0，给出队列位置损失的分布；这项供 Step 12 最后一行使用。
输出 Table 10 与 Figure 8（ahead0 分布）。

Step 15 — 加入费率与延迟 [修改 4]
P1 是纯挂单、无手续费、无延迟。市价单层已在 Step 13 第 4–5 条按 P2 实现，本步补费率与延迟。

1. 费率。P2 Remark 2.1 / 2.2 给出返佣与费率进入价格和成本的方式：挂单成交价 (\pi^b=(p-s/2+\delta 1_{B^{b+}})(1-\rho))、(\pi^a=(p+s/2-\delta 1_{B^{a-}})(1+\rho))，市价单成本按 Remark 2.2 加比例费。本任务：挂单成交价乘 ((1\mp f_{\text{maker}}))，(f_{\text{maker}}) 按合约取 我方费率（USDT）或 我方费率（USDC）；市价单加 (f_{\text{taker}}=0.018\%)。费率进入 Step 我方费率 的递推时相当于 (p^\pm) 的平移与 (c^\pm) 的缩放，推导写出并单测。
2. 延迟。用 l3sim 的 Latency(fixed_ms=L)，(L\in\{1.8,3.8\}) 为主，50 ms 为拥堵情景（用户 2026-10-03 口径），{10, 25} 为稳健性网格（latency.yaml）。决策在 (t_k) 做出，订单在 (t_k+L) 进簿，撤单同路径；市价单同样经过 L 后才成交，成交价取进簿时刻的对手价。报告延迟 0 → 1.8 → 3.8 → 10 ms 的结果应单调恶化，不单调先查引擎接法。
3. 市价单核对。用户 2026-10-16 对吃单的规则：吃单只在预期收益 ≥ 我方费率 + 半价差，或挂单开仓后吃单平仓一开一平 ≥ 0.1 bp 时使用。对 Step 13 由价值函数比较触发的每笔市价单，报告是否满足这条，不满足的列出。

输出 Table 11：{P1 原版，P2 WoMO + 费率 + 延迟，P2 完整 + 费率 + 延迟} × (L) 档，指标同 Step 12，另加市价单笔数、市价单成交额占比、吃单费合计、返佣合计。

Step 16 — 按本地盘口校准 P2 的清算函数 L [修改 5]
P1 的 (\lambda=0.0005) 是 MSFT 的美元/股²，Part B 不使用。本步校准的是 P2 的清算函数
[
L(x,y,p,s)=x+yp-|y|\tfrac{s}{2}-\varepsilon\quad\text{（P2 Section 3.1）}
]
1. 定义。在 train + validation 的采样时刻 (t)，对库存网格 (I)（从 (V_{LO}) 到 Step 13 的 (y) 网格上界），用当时 L2/L3 盘口沿深度算实际清算所得 (x+\bar S_t(I)\,I)（卖出用 bid 侧，买回用 ask 侧），与 L 的预测 (x+I\,p_t-|I|\,s_t/2-\varepsilon) 比较，残差 (r_t(I))。单位 USDT；(I) 以合约张数计，各合约一张的名义见文件头。
2. (\varepsilon)：KuCoin 无固定费，(\varepsilon=0)；taker 费按 P2 Remark 2.2 以比例形式进入（我方费率），写明。
3. 报告 (r_t(I)) 随 (|I|) 的曲线、按小时、按点差状态。P2 假设线性冲击且与单量无关（Section 2.2 "we only consider a linear market impact"），报告 (|I|) 超过多少后这一假设开始失效，两种口径都给：残差超过半个 tick；残差超过 maker 返佣（我方费率 或 我方费率）。
4. 该 (|I|) 上界作为 Step 13 库存网格 (y_{\max}) 的依据之一，写明。
5. 用 Step 9 保存的 Part A 实际清算成本按 (I_T) 分桶，与 L 的预测叠画，作为对照。
6. 不引入 (\lambda)，不拟合二次项。
输出 Table 12 和 Figure 9。

=====================================================================
执行要求
=====================================================================
按照 Step 1–16 顺序执行。
每一步必须有实际产物和可检查的中间结果。 不允许跳过需求估计、状态转移或 Bellman Recursion，直接使用简化的做市公式完成策略。
每一次跑之前先说：用什么数据、跑哪些组、选优标准、预计多久、结果放哪；中途改动当场说明。
长任务用 scripts 下的 detach.py 启动；子进程用 CREATE_NO_WINDOW，查进程用 psutil；临时文件只放  下。
负面结果同样先查 bug 再下结论；失败报告写"我们的设计哪步亏钱、下一版改什么"，不归咎市场、交易所、费率、延迟。
每一步完成后：

1. 报告论文对应的公式或章节（P1 或 P2）。
2. 指出实际修改的代码。
3. 展示关键中间统计量或测试结果。
4. 验证该步骤是否符合论文。
5. 更新工程选择登记表。
6. 继续下一步骤。

Part A 优先完成原论文复现。Part B 的库存管理只许用 P2，不许回头用 P1 的 λ 或 Theorem 10。Part B 之外不要添加 Reinforcement Learning、Market Regime Detection 或新的 Alpha 模型。
最终交付应包括能运行的模型、训练流程、回测实验、论文结果对照（Table 1–7、Figure 4–6）、修改实验结果（Table 8–12、Figure 8–9、P2 Figure 3 型策略切片）和工程选择登记表。
核心验收标准：模型、参数估计方法、状态转移、最优报价和成交计算都能明确追溯到 P1 / P2 对应的公式，而不仅仅是一个表现不错的 Market Making Strategy。


=====================================================================
裁决附录（2026-11-06 第二批，针对执行者提出的七个问题；正文条文不动，与正文冲突处以本附录为准）
=====================================================================
事实更正：文件头"ETHUSDTM / ETHUSDCM 只有 L2"有误。ETHUSDCM 有 10 月 L3（data/research5/usdc_pairs，10-01…10-30 共 19 天，10-16…10-20 每天 24 小时）；XBTUSDTM 的 L3 在 data/research5/usdc_pairs_l3usdt；只有 ETHUSDTM 没有 L3。引擎 l3sim.py 第 31 行 L3_DIR 只登记了两个 BTC 合约，ETHUSDCM 的目录映射在适配层构造引擎前加入，不改引擎文件，报告写明。

1. 品种：用户原话"那就先不跑USDT，没有的数据先不跑"。没有 L3 的 ETHUSDTM 暂不跑。（撰写者解读，用户没说过：XBTUSDTM 有 L3，照跑；本轮跑 XBTUSDTM、XBTUSDCM、ETHUSDCM 三个合约。若用户本意是两个 USDT 合约都不跑，以用户为准。）
2. 切分：批准。每个合约用 segments.py 各生成一份切分（段的取舍、质量失败按本合约算），但 train/validation/final_test 的切点时间戳沿用 XBTUSDTM 的两个值（2026-10-18T04:31:34.397Z、2026-10-19T21:41:05.630Z）。segments.py 需加"切点从指定文件读取"的选项，属 research_mm 自身脚本。
3. 市价单执行：批准放适配层。两个口径分开报：P2 字面口径 = 在 t_k + L 时刻按引擎当时重建的对手盘最优价成交并加 taker 费；第二口径 = 沿深度走簿，供 Step 16 校准 L。两者都不假设他人对我方市价单作反应。
4. Gate 1 延迟单调性口径：用户 2026-11-06 裁决"按配对口径"。判据 = "同一决策配对"口径（同一张下单决策在两个延迟下都成交时逐步比较，0 → 1.8 → 3.8 → 10 ms 应逐步变差）；聚合口径（naive 全部成交）同时报出作诊断，不作判据。Step 15 的单调检查同此。
5. 9 月三天 L3（09-22、09-24、09-25）：批准。只用于 Step 14 的排队分布，单独一列"9 月样本"，不进校准、不进 PnL、不与 train + validation 合并统计。
6. Part A 训练与测试：用户原话"用9月的数据训练，10月的验证"。训练 = data/oos/ku_buyc 的 9 月购买数据（08-26…09-24 共 20 天，L2 + 成交，无 takerOrderId；同时间戳同方向的打印合并为一笔 MO，登记为近似）；测试 = 10 月 L3 日。（撰写者注，用户没说过：此裁决意味着 09-02 起 9 天"最终验证考卷勿调参"的限制对本线不再适用；滚动窗按可用日列表取测试日之前最近 20 天，报告与 P1 日历连续窗的差别。）
7. UTC 日内缺口：批准。不拆段；有效覆盖达到阈值的日子保留，日内短缺口期间冻结报价、不记成交、库存延续、缺口后用 ϖ 个区间重新预热指标；达不到阈值的整天剔除并列表。阈值数字待执行者报出每个 UTC 日的缺口分布后由用户定，或用"含缺口日 / 不含缺口日"两组做敏感性。
