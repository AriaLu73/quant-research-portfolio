# 做市策略亏损诊断 —— Research Plan(按优先级)与 Data Requirements Checklist

按用户 2026-11-09 提示词 v1(`prompt_v1_用户原文_2026-11-09.md`)第一步要求写:先出研究计划和最小可行数据集,再从 PnL Attribution 与 Maker Rebate Economics 开始。本文不含任何新的分析结果;引用的数字全部来自本会话已出的回测表,并标明出处。

---

## 0. 待确认的 Strategy Context(提示词 §1)

下面"已知"一栏只填本会话里有凭据的事实;诊断对象到底是哪一个数据集,要用户先定(见 §0.1)。

| 字段 | 已知(来源) | 缺失 / 待确认 | 缺失的重要性 |
|---|---|---|---|
| Exchange / Symbol | KuCoin 合约;回测覆盖 XBTUSDCM、XBTUSDTM、ETHUSDCM(repro/config/contracts.yaml) | 用户 11-08 说"只跑 BTCUSDC":诊断是否只做 XBTUSDCM | 决定样本量:XBTUSDCM 9 天 P1 只有 14,435 笔、[金额已抹];XBTUSDTM 39,795 笔、[金额已抹] |
| Maker Rebate / Taker Fee | USDC 合约 maker 我方费率、USDT 我方费率,taker 我方费率(我方费率档,contracts.yaml;出处 KuCoin MM Program 2026-04) | 实盘账户当前实际档位 | 返佣是本研究核心变量,差 0.5 bp 结论会翻 |
| Typical Quoted Spread | 回测报价距中价:XBTUSDTM P1 约 24 tick ≈ 0.3 bp 单边;XBTUSDCM P1 60–155 tick ≈ 0.7–1.9 bp 单边(reports/step12 的 trades csv `quote_distance_ticks`) | 实盘策略的报价距离 | 决定 spread capture 的量级 |
| Quote Update Frequency | 回测每 Δt 决策一次,Δt = 100 ms…2 s,基准 1 s;区间内不改价 | 实盘更新频率、是否事件驱动 | 决定 stale quote 分析能否做 |
| Typical Holding Period | P1:无平仓,库存整天延续(持仓段 = 整天);P2:≤ 300 s 段末强平 | 实盘持仓时长 | 库存腿与 markout 的会计边界取决于此 |
| Average / Maximum Inventory | 回测 P1 max\|I\|:XBTUSDCM 3,881 张(≈ [金额已抹])、XBTUSDTM 2,154 张(≈ [金额已抹]);P2 ≤ 1,829 张 | 实盘 |  |
| Order Size / Fill Rate | 每侧 1 张 V_LO:XBTUSDTM 24 张、XBTUSDCM 74 张、ETHUSDCM 696 张;下单→成交比例 P1 XBTUSDTM 约 4%、XBTUSDCM 约 0.1%(step14 summary) | 实盘 | Fill selection bias 分析要全部报价而不只成交 |
| Hedge Mechanism | 回测:P1 无对冲;P2 只有同合约市价单减仓 + 段末清仓(taker 我方费率);无跨所对冲 | 实盘是否有对冲、在哪对冲 | 提示词的 Hedging Cost 项在回测里 = P2 的市价单成本 |
| Latency | 回测固定 1.8 ms(下单、撤单同延迟;Table 11 扫 0/3.8/10/25/50 ms);实测口径:行情 0.3 ms、下单 1.5 ms、回路 ≈ 1.8 ms;拥堵 50 ms(用户 10-03 口径) | 实盘逐笔 ack / cancel 延迟日志 | 回测里延迟对 PnL 影响 < 1.5%(Table 11),实盘未测 |
| PnL Calculation Method | 回测:现金 ± 成交价款 + 返佣 − taker 费 + 日末(P1)/ 段末(P2)残余按中价或对手价计价;无 funding | 实盘的结算口径、是否含 funding | 对账基准 |
| Funding | 回测未计 | 实盘资金费率流水 | 持仓隔夜(P1)时不可忽略;P2 持仓 ≤ 300 s 基本为 0 |
| Market data | 自录 L3(逐笔委托,10 月 9 天)+ 购买 L2/成交(9 月);币安 lead feed 有(10-14…16 部分) | — | 可算 markout 到 1 ms 分辨率、精确排队位置 |

### 0.1 必须先裁决:诊断对象是哪个数据集

| 选项 | 数据 | 能做的分析 | 做不了的 |
|---|---|---|---|
| A. 本会话的 l3sim 回测成交(P1 原论文 / P2,XBTUSDCM 9 天,5 个 Δt) | 每笔成交含下单时刻、排队位置 ahead0、等待时长、打到我方的吃单量、L3 分辨率中价 | PnL attribution、全部 horizon 的 markout、queue position、fill selection bias(有全部报价记录)、regime 分组、反事实回放(引擎可重跑) | 实盘延迟分布、撤单失败、交易所侧排队、对冲滑点(回测无对冲) |
| B. 实盘成交记录(用户提供导出) | 需要用户给:成交、委托、撤单事件、账户流水、funding | 真实 PnL 对账、真实延迟与撤单、funding | 排队位置要估(无 L3 对账);反事实只能 shadow / A/B |

两者不互斥,但分析框架先按哪个搭,要用户定。

---

## 1. Research Plan(按优先级)

每一步写:要回答的问题 → 输入 → 方法 → 输出 → 通过/不通过判据。全部按 bp(对成交名义额)与绝对 USDC 双口径报;样本量按独立观测数(成交笔数、天数)报。

### P0-1 PnL Attribution(提示词 §3)—— 先对账,再归因

- 问题:每笔成交的钱去了哪;Gross trading PnL 为负、返佣为正时,是赚价差还是返佣在补贴负期望成交。
- 会计边界(避免重复计):对每笔 maker 成交 i,以**下单时刻中价** m₀ 和**成交时刻中价** m_f 为两个锚:
  - Spread capture_i = side·(m_f − p_i)·q_i(成交价对成交时刻中价;side 卖 +1 买 −1)
  - 下单后到成交前的中价漂移 = side·(m₀ − m_f)·q_i(这项在 l3sim 里不为 0:盘口穿过挂单价后单子仍挂着,见 11-08 核对)
  - Inventory MTM = Σ 持仓 × 中价变化(按时间积分),等于 Σ_i side·(m_f − m_exit,i)·q_i 的汇总;**markout 是它的诊断切片,不进对账表**
  - Rebate_i = r·p_i·q_i;Taker fee / 对冲成本 = 市价单价款对当时中价之差 + 费;Funding(实盘才有);Residual = 账本 − 以上各项
- 输出:对账表(逐日、逐段、逐笔),Residual 必须 = 0(回测)或报出大小(实盘);公式、字段、图、Python 脚本(repro/sim_l3/pnl_attrib_p1p2.py 已有雏形,要按上述边界重写)。
- 判据:若 Spread capture + Rebate > 0 而 Inventory MTM < 0 且 |MTM| > 前两项之和 → 亏损来自持仓/逆向,不来自价差不足。

### P0-2 Adverse Selection / Markout(§4)

- 问题:成交后中价是否系统性对我方不利;亏在哪些成交、哪些环境、哪些 quote age。
- 定义:Signed markout_h,i = side·(m_f − m_{f+h})·q_i / 名义额,h ∈ {10 ms, 50, 100, 500 ms, 1, 5, 10, 30, 60 s};正 = 成交后中价向我方有利方向走。三条曲线分开:Fill price→future mid(总执行价值)、Fill-time mid→future mid(逆向选择)、Fill price→fill-time mid(spread capture);返佣只加一次,作为水平线叠加。
- 分组:买/卖、按量加权、波动(1 s 中价实现波动分位)、盘口失衡(成交前 BBO 量比)、吃单大小(sweep_qty)、点差宽度、quote age(成交时刻 − 下单时刻)、时段、regime。
- 输出:markout 曲线族 + 分组表(每格给 n、均值、t 值、按量加权)。
- 判据:|markout_5s| > spread capture + rebate 的分组 = 应避免的 fill 类型。
- 已有材料:trades csv 已带 5 s markout、quote age、ahead0、sweep_qty;L3 中价序列在 data/step14/<sym>/dt*/<day>_bbo.npz。

### P0-3 Maker Rebate Economics(§5)

- 模型:E[Fill value] = E[spread capture] + rebate + E[post-fill markout_h] − 增量库存/对冲成本,h 取与持仓时长一致的 horizon(P2 用到段末,P1 用到日末或固定 60 s 两种都报)。
- 假设(每条可证伪):H1 去掉返佣后 我方费率 天净 PnL < 0;H2 返佣 / |gross loss| 比例 > 我方费率(返佣在补亏);H3 扣返佣后仍显著为负的 fill 集中在 quote age 最长 / 吃单最大的分位;H4 成交量与净收益负相关(Δt 或报价距离扫描);H5 存在 rebate-adjusted 最小 edge 阈值使净 PnL 最大且样本外成立。
- 方法:用 Δt 扫描(100…2000 ms)与报价距离扫描作为"成交量 vs 质量"的自然实验;阈值在前 5 天定、后 4 天验(不许全样本调参)。
- 判据:H5 的样本外净 PnL 必须 > 对照,且成交量 ≥ 用户定的下限。

### P1-1 Inventory / Hedging(§6)

- 库存分布、持仓时长分布、库存 × 后续收益(库存符号与未来 1/5/60 s 中价变化的相关)、库存 × 波动、skew 有效性(P1 的 A1 倾斜实测 ≈ 0.0002 tick/张,已知无效)、P2 市价单减仓的滑点与费。
- 判据:单边行情中库存是否同向累积(10-14 XBTUSDCM 日末 +2,450 张是现成案例)。

### P1-2 Execution / Latency / Queue(§7)

- 回测可做:quote age at fill、ahead0 分桶 markout、fresh vs stale(同一笔报价在不同延迟档的配对,Table 11 已有 0…50 ms 配对)、partial fill、fill probability(全部报价记录 vs 成交);实盘才有:cancel 失败、真实延迟分布。
- Fill selection bias:用全部下单记录(records,含未成交)算每类报价的成交概率 × 成交后价值,不只看成交。
- 判据:stale quote(age > 阈值)的 markout 显著差于 fresh。

### P1-3 Market Regime(§8)

- 分组:波动、趋势/均值回复(1 min 自相关)、流动性(盘口前 5 档量)、点差、失衡、吃单强度、时段、合约;funding regime 回测没有。
- 输出:每个 regime 的净 bp、成交额、markout、库存;判据:哪些 regime 的净 bp 含返佣仍 < 0。

### P2 Counterfactual Experiments(§9)

- 按 P0/P1 结论挑选 A–I 中有证据支持的 2–3 个,在 l3sim 里重跑(不是从历史成交里删 fill),同种子配对,先 5 天定参、后 4 天验;每个实验按提示词格式写 Hypothesis…Acceptance Criteria。
- 做不了可靠回放的(撤单延迟改善、市场反馈)→ 建议实盘探针 / 小规模 A/B,不在回测里下结论。

### 交付(§10)

A 根因排序、B 图表清单、C P0/P1/P2 待办、D 代码(按下面数据 schema)、E Executive Summary。

---

## 2. Data Requirements Checklist(最小可行数据集)

"回测 A" 列 = 本会话已有;"实盘 B" 列 = 需要用户提供。★ = 最小可行数据集必需。

| # | 数据 | 字段 | 用途 | 回测 A | 实盘 B |
|---|---|---|---|---|---|
| 1★ | Maker 成交 | 时间戳(交易所钟)、方向、价、量、订单 id、下单时刻、成交时刻盘口 | PnL、markout、quote age | 有(trades csv / step14 npz fills) | 需要成交流水 + 委托 id 对应 |
| 2★ | 全部委托事件 | 下单 / 撤单 / 改价 / 拒单 时间、价、量、原因 | fill probability、selection bias、cancel 延迟 | 有(records、requotes;无拒单) | 需要 OMS 日志 |
| 3★ | 市价单 / 对冲 | 时间、方向、量、成交价、费 | hedge cost、taker drag | 有(P2 mos) | 需要 |
| 4★ | 中价 / BBO 序列 | ≤ 10 ms 分辨率 | markout 10 ms…60 s、spread capture | 有(L3 分辨率 bbo.npz) | 需要行情录制 |
| 5★ | 费率 | maker / taker bp,按账户档位 | 返佣经济学 | 有(contracts.yaml) | 需确认实盘档位 |
| 6★ | 账本 / 库存轨迹 | 现金、库存、逐段结算 | 对账 | 可从 1–3 重建 | 需要账户流水 |
| 7 | 盘口深度 | 前 5 档量、失衡 | regime、toxicity 分组 | 有(L3 重建) | 需要 |
| 8 | 成交流 | 全市场逐笔成交、吃单方向、大小 | trade intensity、toxic flow | 有 | 需要 |
| 9 | 延迟日志 | 行情 / 下单 ack / 撤单 ack 时间戳 | §7 | 回测为常数;实测口径 0.3 / 1.5 ms | 需要 |
| 10 | Funding | 每 8 h 费率与持仓 | funding PnL | 无(回测未计) | 需要 |
| 11 | 外部参考价 | 币安同品种 BBO | fair value 误差(§2 第 8 项) | 部分天有 | 可选 |

最小可行数据集 = 1–6。回测 A 六项齐全;实盘 B 一项都还没有。

---

## 3. 已有、可直接复用的材料

| 材料 | 位置 | 对应提示词章节 |
|---|---|---|
| P1 原论文 9 天成交明细(XBTUSDCM 1000 ms、XBTUSDTM 250 ms / 1000 ms),含 quote age、ahead0、5 s markout | repro/reports/step12/P1_M_g3_*_trades_*.csv | §3 §4 §7 |
| P2 成交明细(3.8 ms,三合约) | repro/reports/step15/P2_full_3.8ms_trades_*.csv | §3 §6 |
| 价差腿 / 持仓腿 / 市价单腿 归因雏形 | repro/sim_l3/pnl_attrib_p1p2.py、reports/step12/pnl_attrib_P1P2_*.md | §3 |
| 延迟 0…50 ms 配对(fresh vs stale 的下界) | reports/step15/table11_*.md | §7 |
| Δt 扫描(成交量 vs 质量) | reports/step12/table8_l3sim_*.md、fill_XBTUSDCM_progress_20261109_0030.md | §5 |
| 全部报价记录(含未成交、改价放弃的 ahead) | data/step14/<sym>/dt*/<day>_*.npz 的 records / requotes | §7 selection bias |
| L3 分辨率中价 | data/step14/<sym>/dt*/<day>_bbo.npz | §4 |
| 引擎(可做反事实回放) | scripts\research7\l3sim.py + repro/sim_l3/agents.py | §9 |

已知限制(写进每份结果):目录仍为队首口径估的需求(用户 11-07 裁决待重跑);l3sim 假设我方不改变他人行为(H2),XBTUSDCM 上 P2 返佣感知版占市场吃单 我方费率 时该假设存疑;10 月只有 9 个有 L3 的日子,其中 5 天残缺;Step 12 补跑的 100 ms 两天(10-15、10-19)进程现处于挂起状态。

---

## 4. 等用户裁决的事项

1. 诊断对象:选项 A(回测成交)还是 B(实盘导出),或 A 先做、B 数据到了再做。
2. 若选 A:诊断哪些方案 —— P1 原论文(哪个 Δt)、P2(Step 13 目录 / Table 11 返佣感知目录)。
3. 合约范围:只 XBTUSDCM,还是加 XBTUSDTM。
4. 挂起中的 Step 12 两个任务:继续、终止。
