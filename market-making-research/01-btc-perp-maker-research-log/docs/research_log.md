# 研究日志(Research Log)— KuCoin BTC 永续做市策略

> 口径标注:PAPER RESULT(文献)/ OUR SIM(快速模拟器,ESTIMATED 队列)/ OUR BACKTEST(项目引擎 engine/backtest,L3 队列、colo 延迟、我方费率档 费率)/ OUR OOS(冻结后随机 5×1h)。
> 训练池:2025-10-01、2026-01-01、2026-04-01;OOS 池:2026-06-01、2026-07-01、2026-08-01(策略级结果在冻结前不触碰)。

## 1. Data Audit(2026-09-13)
- 6 天 Tardis 原始 L2 增量 + 逐笔成交,共 144 个小时数据集;142/144 可用,标记 2 个(07-01 18h 短暂交叉簿;08-01 13h 一次 6s 缺口)。
- 无非法价/量、无成交 id 重复;交易所时间回跳 ≤10.5ms,单调钳制处理。详见 data_readiness.md、dataset_registry.json。

## 2. 因子检验(训练池,factor_report_train.md)
- 无条件 mid 预测:imb5 / imb1 / OFI(100–500ms)/ 队列耗尽率 IC(Spearman)0.45–0.50 @250–500ms,逐日同号 3/3;衰减:5s 0.3–0.4,30s 0.15–0.24。
- **E(Markout | Bid Fill)** 无条件:10ms −0.30bp → 500ms −0.68 → 5s −0.89 → 30s −1.23bp(Ask 对称)。返费 我方费率 覆盖不了。
- 成交后 markout 的状态依赖:本侧顶档量(bq1)顶十分位 −0.05bp、imb5 顶十分位 +0.08bp(500ms);逆向十分位 −0.9~−1.0bp。
  → 提供流动性有利的状态 = 本侧队列大 / 失衡向本侧;不利 = 本侧队列薄、OFI 逆向、刚发生逆向成交、波动/成交强度高。

## 3. Quote Economics(quote_econ.md,ESTIMATED 队列)
- 挂盘口 30s 内 P(fill)=0.55;E[mk|fill] 5s −0.65、30s −0.83bp;含返费净 5s +0.05、30s −0.13bp。
- QuoteEV 最好分桶:本侧队列 0.7–2.6 BTC(+0.10)、对侧队列大(+0.11)、OFI 温和同向(+0.08)、低波动(+0.11)、成交稀疏(+0.04);最差:OFI 强逆向(−0.14)、队列耗尽逆向(−0.11)、高波动(−0.09)。
- 所有分桶 30s markout 均 ≤ −0.66bp:成交后价格持续漂移不利,持仓时间必须短。

## 4. 策略模拟(OUR SIM)与引擎回测(OUR BACKTEST)
- SIM 面板(policy_grid.md,整笔成交假设):基线 −0.41bp;imb5 门控(post 0.3 / pull −0.3)+0.23bp,三天皆正,66/72 小时为正;延迟敏感:10ms +0.19、25ms +0.13、50ms +0.09、100ms +0.04bp。
- 引擎小面板(6 切片):GLFT 基线 −0.53bp(0/6 正);v1(imb 门控)−0.33bp(0/6 正)。**引擎与 SIM 不一致**。
- 诊断(20260401 13h):引擎成交 2363 笔、均量 0.034 BTC(部分成交主导),57% 成交发生在 imb 对齐 < −0.3(应已撤单/或为不受门控的减仓侧),5s markout −1.13bp;SIM 同小时 1285 笔整笔成交,29% 逆向,markout −0.41bp。
  根因假设:① 减仓侧不受门控 → 部分成交使库存长期非零,减仓侧持续裸露在逆向状态被小单逐笔吃(队首毒性);② SIM 整笔成交假设高估了有利状态的成交占比。
  → SIM 已加入部分成交、减仓侧门控(reduce_post/pull)、持仓超时解除门控(hold_max_s);引擎策略同步加参数。

## 4b. 迭代记录(2026-09-13 续)
- SIM 改为部分成交模型(前方量耗尽后按逐笔成交量成交,与引擎一致)后,原"整笔成交"下的正结果全部消失:imb 门控 −0.87bp、所有减仓门控/超时变体均负(policy_grid2/3.md)。整笔模型把撤单归因量也算成成交,是乐观偏差来源。
- 引擎 v2(imb 门控 + 减仓侧同样门控):+0.76bp、3/6 正,但成交少、PnL 由库存 MTM 主导(单切片 −6.5bp~+3.5bp),不是稳定的做市收益。
- 跨所领先(OKX mid − KuCoin mid,04-01 单日,20ms/100ms 采样):所有门控变体均负(policy_grid5/6);作为 KuCoin 挂单保护信号不成立。
- 成交拆解(SIM/引擎一致):① 档位被撤空/吃穿后"独挂"成交 −1.4~−2.0bp;② 挂单 0.5s 内成交 −1.1~−1.35bp;③ 挂单 ≥2s、所在档 ≥0.6 BTC(队首于大队列)成交 −0.25~+0.5bp。
  事件层验证:打在 bb 的成交按该档量十分位,顶两档(≥0.56 BTC)markout 500ms/5s/30s = −0.16/−0.24/−0.30 与 −0.05/−0.05/−0.30bp(L07/L10 队首价值)。
- 由此得到 mm_v4(join family):只在新/薄档(公开量 ≤ q_max 0.1 BTC)挂单抢队首;宽限 500ms 后若该档公开量 < q_pull 0.25 BTC 则撤(档位没长起来 = 脆弱);imb5 门控 0.3/−0.3;减仓侧同门控、持仓 120s 后解除;档位消失立即撤单。
  SIM(部分成交):+0.48bp,三天皆正,45/72 小时正,小时均值 +9 / std 33。引擎小面板:+0.53bp,gross −0.17bp(逆向选择首次低于返费),4/6 正,worst −4.0。

## 5. 版本记录
| version | 变更 | SIM 净 bp(训练 3 天) | 引擎小面板 净 bp / 正切片 | 状态 |
|---|---|---|---|---|
| glft_base | AS/GLFT 基线(γ=1e-4,A=0.6,k=1.57,σ 在线) | −0.41 | −0.53 / 0/6 | BACKTESTED(基线) |
| mm_v1 | imb5 门控 post 0.3 / pull −0.3,减仓侧不门控 | +0.23(整笔)/ −0.87(部分成交)| −0.33 / 0/6 | FAILED: ADVERSE_SELECTION(减仓侧)+ QUEUE_FAILURE(部分成交) |
| mm_v2 | v1 + 减仓侧同门控(无超时) | −0.21(部分成交)| +0.76 / 3/6 | FAILED: INVENTORY_FAILURE(PnL 由库存漂移主导) |
| mm_v3 | v2 + 持仓 120s 解除门控 + 顶档 <0.6 BTC 撤单 | +0.05 | −1.08 / 2/6 | FAILED: FILL_FAILURE(成交极少)+ ADVERSE_SELECTION |
| mm_v4 | 抢新档队首(q_max 0.1)+ 宽限 500ms 后 q_pull 0.25 + imb 门控 + 减仓门控/120s + 消失即撤 | +0.48 | 小面板 +0.53 / 4/6;**全面板 +0.06bp / 11/24** | PARAMETER_FREEZE → OOS(seed 20260913)**NOT_PASSED**:−0.35bp,1/5 正 |
| mm_v5 | v4 + max_clips 2 + vol_max 1.0bp + ofi_pull −1.5 | +0.56 | +0.14 / 4/6(成交极少) | FAILED: FILL_FAILURE |
| (sim only) | "确认增长后加入"(q∈[0.25,0.6] 且 200ms 内增长) | −0.24~+0.03 | — | FAILED: NO_SIGNAL |

## 6. 本轮结论与失败分析(2026-09-13)
- 引擎(项目回测,L3 队列/部分成交/colo 延迟/我方费率档 返费)下:GLFT 基线 训练 −0.56bp(0/24)、OOS −0.31bp(0/5);mm_v4 训练 +0.06bp(11/24)、OOS −0.35bp(1/5)。**无策略通过 5×1h OOS**。
- 失败分类:ADVERSE_SELECTION(主)。成交量 70% 来自"薄档被扫穿、档位消失后延迟窗内成交"(markout −1bp),减仓侧成交 −0.7~−1.0bp;只有"挂单 ≥2s 且所在档 ≥0.6 BTC"的成交(~25% 量)净为正。
- 小时胜率(训练 46%、SIM 63%)远低于 5/5 所需(≥90%),差距是结构性的,不是参数问题。
- 保真度注记:Tardis 簿减量有 20% 先于成交打印;引擎把该减量按撤单归因(0.5)推进队列后又按成交推进 → 队列前推偏乐观;真实成交应更少、更靠队尾。
- 下一轮假设见 strategy_report_mm_v4.md §10:预测性撤单(耗尽率)、减仓侧只在队首大队列状态挂、换多 tick 标的(需 ETH L2 增量数据)、引擎队列对账开关。

## 7. 产物索引
- 脚本:scripts/research/{extract_kucoin_tardis, extract_okx_tardis, data_readiness, factor_lab, quote_econ, policy_sim, run_slices, draw_oos_slices, strategy_report}.py;网格脚本 _grid*.py。
- 数据:data/research/kucoin(L1/成交/审计)、data/research/factors(因子+事件)、data/research/runs(引擎面板结果)、data/oos/ku_td(96 个 1h 切片 feed)。
- 文档:docs/research/{data_readiness, literature, factor_report_train, quote_econ, policy_grid*, strategy_report_mm_v4}.md;docs/backup_strategies.md(无入库)。
