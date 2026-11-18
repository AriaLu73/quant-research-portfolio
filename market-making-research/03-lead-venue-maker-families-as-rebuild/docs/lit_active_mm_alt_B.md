# 主动做市的其它途径 —— 文献综述 B(加密实证 + 机器学习/强化学习)

日期:2026-10-02。范围:除"用更快场所的价格"之外,主动做市还有哪些做法,其中哪些在**加密市场(现货或永续)**有证据;含机器学习做法与来自加密特有结构(资金费、强平、tick、费率档、计价币分割)的 edge。经典模型类文献(Guilbaud–Pham、Cartea 等、queue-reactive、VPIN 理论、多资产做市)由另一份综述负责,这里不重复。

**读法与核对方式**

- 只用公开网页来源(arXiv、出版社开放获取页、作者/学校托管的工作论文、会议稿)。没有打开本机任何 PDF 或内部文档。
- 每篇把网页/PDF 的文字抽成纯文本后阅读;**卡片里的数字都是我在论文原文文本里逐字看到的**,不是搜索摘要工具转述的。凡只见于搜索摘要、未在原文核到的数字,卡片里注明"未核实",且不进入综合部分。
- SSRN 全站对抓取返回 403,浏览器打开是机器人验证页,按规则不绕过。因此凡只有 SSRN 副本的论文都读不到全文(见文末清单)。
- 【原文】= 论文自己说的(带节号/表号/页码);【推导】= 我的推断。两者不混写。
- "读的版本"一栏如实写:全文 / 部分 / 仅摘要。**全文读完的只有 2 篇**(B02 正文与表 1–8、B04a);其余为部分阅读或仅摘要。
- 卡片编号 B01–B10 对应任务清单的 1–10 项;同一项多篇时加字母。任务清单第 7、10 项没有找到直接对口的论文,写成"缺口 + 旁证"卡(B07、B10)。偏题或只读到摘要的论文合并为短卡(B04c、B06d 补充条目),字段从简。
- 我方条件(用于判断相关性):KuCoin 永续;吃单 我方费率,挂单返佣 我方费率(USDT 本位)/我方费率(USDC 本位);同机房行情 0.3 ms、下单 1.5 ms;账户级限频;腰部 USDT 永续半点差 1–2 bp,贴盘口挂单返佣后 我方费率–5 秒亏约 2 bp;山寨吃单额约一半是成对打印。已失败项 1–6 与在跑的 USDT→USDC 线见任务书,不再复述。
- 所有 Test 都只涉及真实成交意愿的报价与撤单;不含幌骗、分层挂单、对敲等制造虚假供需的做法。

---

## 一、逐篇卡片

### B01 Stoikov, Zhuang, Chen, Zhang, Li, Wang, Shan (2024)《Market Making in Crypto》

- **引用 + 读的版本**:SSRN 5066176(2024-12-20)。**全文读不到**:SSRN 页面与 PDF 直连均返回 403,浏览器打开是机器人验证页,按规则不绕过;作者主页与 arXiv 无副本。只看到搜索引擎给出的摘要级描述(仅摘要)。第三方网站 paperswithbacktest 上的回测数字是该网站自己重算的日线结果,不是论文结果,不采用。
- **Strategy hypothesis**:【原文,摘要级】在加密永续合约上做自动做市;用 1 分钟 K 线、30 个币构造一个名为 Bar Portion(BP)的 K 线 alpha 信号;在 Hummingbot 上调风控参数后实盘。任务书里说的"BitMEX、Avellaneda–Stoikov 变体"我没能从可访问的文本中核实。
- **Economic mechanism**:摘要未给;BP 的定义我没读到,不重构。
- **Required data**:1 分钟 K 线(摘要)。
- **Holding horizon**:分钟级(由 1 分钟 K 线推断,【推导】)。
- **Expected signal**:Bar Portion;基准为 MACD。
- **Execution dependency**:未知(读不到正文)。
- **Failure modes**:【原文,摘要级】实盘证据只有 SOL-USDT、DOGE-USDT、GALA-USDT 三个交易对、24 小时,结论是"BP 优于 MACD 基准"——是相对比较,摘要没有说扣费后绝对盈利多少。【推导】24 小时样本无法区分 alpha 与当日方向。
- **Evidence**:无可核实数字(未读正文),不进入综合部分。
- **Test(KuCoin 合约)**:拿到正文前不设计实验。若用户能从 SSRN 手动下载,需要核对三件事:BP 的公式、实盘用的费率档、24 小时 PnL 是否扣了库存漂移。

### B02 Easley, O'Hara, Yang, Zhang (2024)《Microstructure and Market Dynamics in Crypto Markets》

- **引用 + 读的版本**:SSRN 4814346,2024-04。读的是康奈尔托管的公开 PDF <https://stoye.economics.cornell.edu/docs/Easley_ssrn-4814346.pdf>,47 页。正文 p.1–22 与表 1–8(p.28–30)全读;p.31 以后的表 9–10 与图 1–10(特征重要性柱状图)未读。
- **Strategy hypothesis**:【原文】没有策略、没有回测。论文只说五个微观结构指标(Roll、Roll impact、Kyle λ、Amihud、VPIN)能预测"收益分布统计量变化的符号"(已实现波动、自相关、峰度、JB、偏度),并称这些量"对电子做市、动态对冲、波动率估计有用"(摘要)。【推导】对做市只能当"状态变量/开关"(何时加宽或撤单),不是方向 alpha。
- **Economic mechanism**:【原文】订单流失衡 → 价格变化正自相关(Roll 升高)→ 波动升高并持续约一天(p.17);BTC、ETH 的 Roll 领先其它币的价格动态(p.19)。VPIN 水平 0.45–0.47,约为 E-mini/原油期货 0.22–0.23 的两倍,作者解读为"毒性更高"(p.15)。
- **Required data**:Binance 现货 USDT 交易对 1 分钟 K 线(开高低收+成交额),2021-01 至 2023-07,BTC/ETH/XRP/SOL/ADA。VPIN 用 bulk volume classification 从 K 线推买卖量,不是真实逐笔方向。
- **Holding horizon**:特征回看 50/100 根 1 分钟 K 线;标签前看 h=1500 根(约 1 天,p.11)。不是亚分钟。
- **Expected signal**:自身 Roll(最重要)、自身 VPIN(第二)、BTC/ETH 的 Roll(跨币)。Kyle λ、Amihud 几乎无用(p.18–19)。
- **Execution dependency**:无(没有成交模拟,没有费用)。
- **Failure modes**:预测的是"统计量变化的符号",不是价格方向;偏度不可预测(准确率 0.50,表 7);窗口重叠靠 1500 根前看来回避;样本只有 5 个大币、单一交易所;作者自己说小币和其它交易所"可能不同"(p.22)。
- **Evidence**:表 2 汇总准确率 0.538(50 根)/0.530(100 根);表 6 已实现波动 0.582/0.565;表 3 自相关 0.532/0.524;表 5 峰度 0.544/0.531;表 7 偏度 0.500/0.502。特征重要性(MDA,表 6,50 根,全样本):Roll 0.058、VPIN 0.009、Roll impact 0.009、Kyle 0.005、Amihud 0.001。表 8:2021-11 前后两段准确率几乎不变(0.538 对 0.540)。
- **Test(KuCoin 合约)**:用真实逐笔方向(先剔除成对打印)算每个腰部币的 1 分钟 Roll 与 VPIN(回看 50 根),按五分位分组,比较我方贴盘口挂单的 5 秒与 5 分钟 markout。预登记:最高分位比最低分位 markout 差 ≥1 bp 且样本外同号,才值得做成"撤单/加宽开关";否则判死。注意这是条件化我们已失败的测试 1,不是新 edge。

### B03 Dyhrberg, Foley, Svec (2019 会议稿 / JFQA 2023)《When Bigger is Better: The Impact of a Tiny Tick Size on Undercutting Behavior》

- **引用 + 读的版本**:JFQA 58(6):2387–2416(2023)。期刊终稿只读到摘要(剑桥页面付费墙)。读的是 EFMA 2019 会议稿《The impact of a tiny tick size on undercutting behavior》<https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2019-Azores/papers/EFMA2019_0382_fullpaper.pdf>,28 页;读了摘要、引言、数据与单变量结果、回归设定与表 4 的文字描述(约 p.1–13),表格本体与后半部分未读(部分阅读)。会议稿数字可能与终稿不同。
- **Strategy hypothesis**:【原文】不是策略论文。命题:tick 过小时,别人可以用经济上可忽略的代价"抢一个 tick"拿到价格优先(undercutting),时间优先失效,流动性提供者不愿挂单;把 tick 放大后 undercut 减少、挂单更多更大、深度增加、价差下降。
- **Economic mechanism**:【原文】被 undercut 使流动性提供者失去成交优先、库存难以快速出清 → 退出;粗价格网格"恢复时间优先的意义",挂单聚集到同一价位。
- **Required data**:Kraken 订单级数据;6 个交易对;2017-08-30 与 09-06 两次 tick 上调前后各一个月。
- **Holding horizon**:15 分钟区间的流动性指标;最优报价存续时间为秒级。
- **Expected signal**:相对 tick(tick/价格)。上调前 0.0015 bp(LTC-USD)到 0.133 bp(ETH-BTC);上调后 0.2261 bp(BTC-USD)到 2.6517 bp(ETC-BTC)。
- **Execution dependency**:结论完全是关于队列的:tick 越粗,时间优先越值钱。
- **Failure modes**:上调后价差仍"大体不受 tick 约束"(受约束时间仅升 2.9 个百分点至 8.2%);2017 年现货,慢撮合引擎;没有做市商 PnL。
- **Evidence**:单变量(表 3 文字):报价价差 −20.5 bp(−29.9%)、有效价差 −20.9 bp(−32.3%)、**已实现价差 −21.7 bp(−35.2%)**;深度 +32.4%;挂单暴露时间 +9.2 秒(+36.9%);undercut 串数 −10.5%。回归(表 4 文字):报价 −19.85 bp、有效 −16.33 bp、已实现 −18.05 bp,5% 显著。引言另给 12.98 / 10.04 / 11.22 bp(对应另一设定)。
- **对任务书问题的直接回答**:【原文】tick 变大后,"流动性提供的回报"(已实现价差)是**下降**的,不是上升;上升的是挂单量与深度。【推导】即:在价差不受 tick 约束的区间,更大的 tick 让更多人愿意排队、每笔赚得更少;它利好的是"在队列里靠前的人",不是所有挂单者。
- **Test(KuCoin 合约)**:对 KuCoin 全部合约按相对 tick 排序,分别统计 (a) 最优价被 1 tick 抢价的频率,(b) 我方回放中同一价位"先到 vs 后到"的成交概率与 markout 差。若 tick 粗的合约上"先到"优势显著(成交概率差 >20 个百分点且 markout 不更差),则把报价资源从细 tick 合约挪到粗 tick 合约,并用 0.3 ms 行情抢新价位的队首。判死:粗 tick 合约上队首成交的 5 秒 markout 仍 ≤ 我方费率。

### B04a Bieganowski & Ślepaczuk (2026)《Explainable Patterns in Cryptocurrency Microstructure》

- **引用 + 读的版本**:arXiv:2602.00776v1(2026-01-31),<https://arxiv.org/pdf/2602.00776>,28 页,全文读完(含附录图题)。预印本,未经同行评审。
- **Strategy hypothesis**:【原文】用盘口第一档失衡、净吃单流、VWAP 相对中间价偏离等特征(CatBoost)预测 3 秒中间价对数收益(式 1);同一组特征在 BTC/LTC/ETC/ENJ/ROSE 上重要性排序与 SHAP 形状相近。再用同一信号做两种执行:吃单回测、挂单回测。
- **Economic mechanism**:【原文】失衡对收益单调、极端处凹;点差宽时预测力减弱;tick 相对价格越大,失衡的预测作用越强(6.1 节、图 5)——大 tick 下盘口失衡就是"连续价格在点差内位置"的可见代理。佐证:W 的现货(tick 10⁻⁴)盘口失衡与 W 永续(tick 10⁻⁵)中间价在现货点差内的位置,相关系数 0.94(图 7)。
- **Required data**:Binance Futures 永续,1 秒频率的顶档盘口 + 成交,2022-01-01 至 2025-10-12。
- **Holding horizon**:标签 3 秒;吃单策略典型持仓 1–2 秒(8.1 节)。
- **Expected signal**:L1 失衡(各币 SHAP 第一)、净订单流、VWAP-to-mid、点差、波动。
- **Execution dependency**:【原文】"Latency is not explicitly modeled; results should be interpreted as an upper bound in the fastest regime"(7.1 节)。挂单回测用"后续成交穿价与队列优先模型"模拟成交,具体队列模型未给;挂单结果"不含吃单费"。费率数值全文未写。
- **Failure modes**:【原文】8.1 节自认真实执行受延迟、抖动、队列位置影响,理想化利润"可能无法实现";挂单策略在 2025-10-10 闪崩中被单边连续成交、巨亏(8.4 节);8.3 节承认这是"速度决定一切"的军备竞赛。
- **Evidence**:表 1 吃单年化(ARC):BTC 0.13、ENJ 4.06、ETC 5.78、LTC 0.07、ROSE 7.00。表 2 挂单年化:BTC 2.93、ENJ −0.81、ETC −0.07、LTC 0.10、ROSE 0.27。表 4 t 检验(对买入持有):吃单仅 ETC/ENJ/ROSE 的 p<0.05;**挂单五个币 p 全部 >0.05**(最好 BTC p=0.106)。作者结论:这类信号"通过立即吃单变现最有效,简单挂单受逆向选择"(7.3 节)。
- **Test(KuCoin 合约)**:(1) 对全部 KuCoin 合约算"相对 tick"(tick/价格,对比半点差),筛出点差≈1 tick 的大 tick 合约;只在这些合约上重测 L1 失衡对下一次中间价变动的预测力,并用我方 0.3 ms 行情 + 队首撮合口径看"失衡不利时撤单、有利时排队"能否把 5 秒 markout 从 −2 bp 拉到 ≥0。(2) 跨合约版本:同一币的 USDT 合约与 USDC 合约(或现货)若 tick 粗细不同,用细 tick 合约的中间价在粗 tick 合约点差内的位置,预测粗 tick 合约哪一侧先被吃——这与我们已跑通的 USDT→USDC 线是同一机制,可用来解释并扩展它。判死条件:失衡分位间 markout 差 <我方费率(不够抵返佣外的毒性)。
- **与我们失败项的关系**:与失败项 2(BTC 上 OBI/microprice 无改进)一致——BTC 在 Binance 上吃单 p=0.75、不显著;论文补充的是"大 tick/小币上才显著,且要靠吃单"。

### B04b Briola, Bartolucci, Aste (2024/2025)《Deep limit order book forecasting: a microstructural guide》

- **引用 + 读的版本**:Quantitative Finance 25(7) 2025;读的是 arXiv:2403.09267v2 的 HTML 版 <https://arxiv.org/html/2403.09267v2>。读了摘要、第 1、5、7、8 节全文与第 4、6 节开头;第 2–3 节、表 8 明细与附录未细读(部分阅读)。**数据是 NASDAQ 股票,不是加密。**
- **Strategy hypothesis**:【原文】无策略。用 DeepLOB 预测中间价方向(三分类),研究"可预测率"与股票微观结构(tick 大小)的关系,并提出用"正确完成一笔完整交易的概率 p_T"(式 3)代替 MCC/F1 评价可用性。
- **Economic mechanism**:【原文】大 tick 股票(点差≈1 tick)盘口排队厚、价格变动少,盘口状态对下一次变动的信息量大;小 tick 股票盘口稀疏,预测接近随机。结论:行为差异"最终都可追溯到 tick 大小"(第 8 节)。
- **Required data**:LOBSTER 逐笔 10 档盘口,15 只 NASDAQ 股票,2017–2019。输入 100×40。
- **Holding horizon**:以盘口更新次数计:H10、H50、H100(非物理时间)。
- **Expected signal**:原始 10 档盘口序列(CNN+LSTM 自动提特征)。
- **Execution dependency**:【原文】7.2 节明说仅用历史数据回测深度模型的交易"不可能",因为要假设:能及时处理并下单、总能成交、零冲击、零成本;结论说大 tick 信号的可用性"显著依赖低延迟硬件"。论文因此**不报任何 PnL**(脚注 4)。
- **Failure modes**:高 MCC 不等于可交易;提高置信阈值使 MCC 上升但 p_T 下降(信号序列被打断,无法正确管理开平仓,图 12)。
- **Evidence**:7.1 节不设阈值的平均 MCC:H10 小 tick 0.11、中 tick 0.13、大 tick 0.29;H50 小 0.04、中 0.085、大 0.36;H100 小 0.01(作者:等同随机)、中 0.036、大 0.26。大 tick 在阈值 0.9 时仍保留 31% 的预测(H10)。小 tick 在 H50 有 39% 的"上涨"被错判为"下跌"。
- **Test(KuCoin 合约)**:不训练深度模型。先做便宜的筛选:把 KuCoin 合约按"平均点差/tick"分三组(≈1、1–3、>3),在每组上只用 L1 队列失衡做逻辑回归预测下一次中间价变动方向,比较 MCC。若大 tick 组 MCC 不显著高于小 tick 组,则"大 tick 更可预测"在 KuCoin 不成立,B04a/B03 相关实验一并降级。
- **定性**:**仅可预测性,非盈利性**;且非加密数据。

### B04c 其它盘口预测论文(合并短卡,均为"可预测性"而非"盈利性")

每篇只列与本题有关的事实;字段从简,因它们都没有可信的成交/费用/延迟模型。

**(1) Zhang, Zohren, Roberts (2019) DeepLOB**,arXiv:1808.03668,12 页,读了引言、数据与标签节,其余检索(部分阅读)。数据:FI-2010 + 伦敦交易所一年股票,非加密。【原文】交易模拟"假设在中间价成交,比较未扣费的毛利"(引言),作者明说模拟只用于模型间比较。Horizon:以盘口更新次数计(k=10…100)。结论:不是净盈利证据。

**(2) Kolm, Turiel, Westray (2023) Deep order flow imbalance**,Mathematical Finance 33(4):1044–1081。**全文读不到**(SSRN 与 Wiley 均 403),只读了 RePEc 上的摘要。【原文,摘要】115 只 NASDAQ 股票;用订单流(OFI)等平稳输入训练的简单网络显著优于直接用盘口状态的模型;"信息丰富"的股票更可预测;个股预测的有效期限约为"两次平均价格变动"。非加密,无成本评估可核实。

**(3) Jha, De Paepe, Holt, West, Ng (2020) Deep Learning for Digital Asset Limit Order Books**,arXiv:2010.01241,9 页,读了摘要、方法与 3.1 节(部分阅读)。数据:Coinbase BTC-USD,100 ms 快照、50 档、9 天(2019-06-12 至 06-20)。【原文】2 秒期限、类别平衡后的样本:下跌 61%、上涨 66% 准确率(7 天训练、1 天测试);摘要写 71% walk-forward 准确率。无交易模拟、无费用。

**(4) Fang, Chung, Ventre, Basios, Kanthan, Li, Wu (2020) Ascertaining price formation in cryptocurrency markets with Deep Learning**,arXiv:2003.00803,22 页,读了摘要与引言,其余检索(部分阅读)。数据:GDAX(Coinbase)L2 实时流,8 个交易对。【原文】预测"下一个 tick 中间价方向",BTC-USD 上"稳定的 78% 准确率";提出用交易费(±0.2%)作标签阈值,但没有扣费后的 PnL。

**(5) Khubiyev & Semenov (2025) Deep Learning Models Meet Financial Data Modalities**,arXiv:2504.13521,15 页,读了数据节与 4.2 节交易策略(部分阅读)。数据:Bybit 永续(BTC、ETH、SOL、ADA、TRX、TON、BNB、DOGE、GOAT),200–300 ms 快照,只有 3 天(2024-11-27 至 29),测试 1 天。【原文】做市回测"默认订单一定成交……不考虑盘口内的排队";策略"主要靠负手续费赚钱"。不构成证据。

**(6) Lee (2024) Price predictability in limit order book with deep learning model**,arXiv:2409.14157,9 页,读了摘要、数据与主要结果段(部分阅读)。数据:AAPL 2022(Nasdaq ITCH),非加密。【原文】对常用的平滑三分类标签,**不用模型的朴素预测就有 64.8% 准确率**,"与深度学习相当"——标签定义把过去信息带进了目标;只用价格序列时方向准确率 50%;加入 L1 挂单量失衡后方向准确率 71.1%;L1 以外的档位"对中间价预测影响很小"。

**(7) Silantyev (2019) Order flow analysis of cryptocurrency markets**,Digital Finance(2019)。**只读到摘要**(Springer 页面;正文付费墙)。【原文,摘要】BitMEX XBTUSD 永续;成交流失衡比总订单流失衡更能解释**同期**价格变动;深度不足与盘口更新到达率低是加密市场与成熟市场的主要差别。与 B08c 的"TFI 强于 OFI"一致;同样是同期关系,不是预测。

- **Strategy hypothesis(共同)**:盘口状态/订单流能预测极短期中间价方向。
- **Economic mechanism**:队列失衡 = 下一次价格变动方向的概率;见 B04a、B04b。
- **Required data**:L2 快照(100 ms–1 s)即可;L1 足够((6) 的结论)。
- **Holding horizon**:下一次价格变动至数秒。
- **Expected signal**:L1 挂单量失衡、OFI。
- **Execution dependency**:全部未建模或假设必成交。
- **Failure modes**:(6) 指出常用的平滑标签会把过去信息带进预测目标,高准确率可能来自标签而非模型;(3)(5) 的样本只有 9 天与 3 天。
- **Evidence**:见各条。
- **Test(KuCoin 合约)**:任何我方的盘口预测实验都先跑 (6) 的"朴素基线":用上一步的平滑收益直接当预测,若准确率与模型相近,说明标签有泄漏,结果作废。标签一律用"未来第一次中间价变动的方向"或固定物理时间的未平滑收益。

### B04d Albers, Cucuringu, Howison, Shestopaloff (2025)《The good, the bad, and latency: exploratory trading on Bybit and Binance》

- **引用 + 读的版本**:Quantitative Finance 25(6):919–947,开放获取;读的是牛津 ORA 上的出版版 <https://ora.ox.ac.uk/objects/uuid:[ID已抹]/files/rs4655j600>,30 页。读了摘要、3.1.3 节(延迟与同机房)、4.3–4.4 节的失败率机制段,其余按关键词检索(部分阅读)。(不在"已读"清单内;已读的是同组 2021 与 2025《Market Maker's Dilemma》。)
- **Strategy hypothesis**:【原文】不是做市策略。实盘发出数百万笔吃单(市价单与"瞄准最优价的可成交限价单"),比较实际成交与下单时盘口快照下的预期成交。
- **Economic mechanism**:【原文】吃单也被逆向选择:事后赚钱的单更容易成交失败或成交价变差,事后亏钱的单则如期成交。原因是有信号时多个吃单者与撤单的挂单者同时向交易所发消息,谁先到是"彩票":即便同机房,消息到交易所的时间"平均约 2 ms、标准差约 1 ms",而各家反应时间差只有几微秒。
- **Required data**:自己的实盘下单回报 + 盘口快照(Bybit:我方机房 新加坡;Binance:我方机房)。
- **Holding horizon**:毫秒(下单到撮合)到数秒的 markout。
- **Expected signal**:波动率、延迟、盘口流动性与失败率强相关;10 分钟波动率对失败率的线性拟合 R² 72.2%。
- **Execution dependency**:全部。
- **Failure modes**:只研究吃单侧;BTC 为主。
- **Evidence**:Bybit BTC 实验全部订单的失败率 1.354%;失败率在未来收益≤0 时接近零,在未来收益为正时显著大于零(图 3);实验标的是反向(币本位)永续:Bybit 吃单费 我方费率、点差约 0.16 bp,Binance 吃单费 我方费率、点差约 0.03 bp(3.1 节)。
- **Test(KuCoin 合约)**:【推导】这篇给"失败项 3"提供了机制解释而非新方向:Binance 一跳之后的 1–3 ms 内,我方撤单与对方吃单在 KuCoin 入口处是抖动主导的抽签,靠 1.5 ms 的下单延迟稳定赢不了。可检验的含义:统计我方"收到 Binance 跳动后发出的撤单"成功率与同时刻被成交率;若成功率在 30%–70% 之间且与我方处理耗时无关,则确认是抽签——此时应改为**事前**条件(波动率/失衡升高时不在盘口),而不是事后抢撤。

### B05a Sadighian (2019)《Deep Reinforcement Learning in Cryptocurrency Market Making》

- **引用 + 读的版本**:arXiv:1911.08647,<https://arxiv.org/pdf/1911.08647>,19 页。读了第 5–7 节(方法、环境规则、结果)全文,其余按关键词检索(部分阅读)。预印本。
- **Strategy hypothesis**:【原文】A2C/PPO 智能体用盘口、TFI、OFI 快照学做市(挂单档位偏斜 + "清仓"市价动作),两种奖励:持仓 PnL、trade completion。
- **Economic mechanism**:【原文】未给经济机制,只称策略梯度能解库存控制问题。
- **Required data**:Coinbase L3 逐笔重建盘口,每 1 秒一个快照;BTC-USD、ETH-USD、LTC-USD;训练 8 天(2019-09-27 至 10-04),测试 2 天(11-01、11-02)。
- **Holding horizon**:1 秒步长,动作重复 5 步。
- **Expected signal**:15 档盘口、订单流失衡(OFI)、成交流失衡(TFI)、自身仓位与挂单队列位置。
- **Execution dependency**:【原文】5.3 节:挂单若与已有挂单同价,"默认跳到队列前一个 tick",作者自己说这在实盘"不太适用";**限价单费用/返佣不计**,只有市价单收 0.20%/边。无延迟。
- **Failure modes**:测试只有 2 天;无挂单费;队列假设乐观;ETH 上持仓 PnL 奖励为负。
- **Evidence**:表 3 每笔平均 PnL:trade completion 奖励下 A2C BTC 0.0017%、ETH 0.0005%、LTC 0.0017%;PPO 为 0.0001%/0.0002%/0.0018%。表 4 日均收益:A2C BTC 3.31%、LTC 1.51%;持仓 PnL 奖励下多个为负(如 A2C LTC −0.18%)。
- **Test**:不值得照搬。若要复核,只需把其每笔 0.0017%(0.17 bp)与我方实测 1–5 秒 −2 bp 的毒性对比——量级差一个数量级,说明其模拟器没有逆向选择。
- **定性**:无现实费用、无现实队列、无延迟;**不构成净盈利证据**。

### B05b Sadighian (2020)《Extending Deep Reinforcement Learning Frameworks in Cryptocurrency Market Making》

- **引用 + 读的版本**:arXiv:2004.06985,<https://arxiv.org/pdf/2004.06985>,16 页。读了第 6.3 节(费用/成交/滑点规则)、第 7 节结果与表 3 部分,其余按关键词检索(部分阅读)。预印本。
- **Strategy hypothesis**:【原文】把"事件"定义为中间价变动超过阈值(价格事件)而非每 tick/每秒,目的是让策略"不依赖延迟";比较 7 种奖励函数。
- **Economic mechanism**:【原文】"The maker-taker fee structure is crucial to the success of our agent's market making trading strategy"(6.3 节)——收益靠返佣。
- **Required data**:BitMEX XBTUSD 永续,L2 盘口 + 成交,约每秒 1 个快照;训练 8 天(2019-12-27 至 2020-01-03),测试 30 天(2020-01-04 至 02-03)。
- **Holding horizon**:秒到分钟;库存上限 10 笔。
- **Expected signal**:盘口、OFI、TFI、技术指标的不同组合(表 2 的 6 组)。
- **Execution dependency**:【原文】计入返佣 我方费率、吃单费 我方费率(当时 BitMEX 费率);挂单要等"该价位下单时的全部挂单金额被成交吃完"后才开始成交(保守的队尾模型);清仓加 0.01% 滑点。无延迟建模。
- **Failure modes**:【原文】最好结果 17.61%,而同期买入持有 16.25%(测试期恰是上涨月)——无法区分做市收益与方向暴露;2020-01-19 比特币 200 秒内跌 5%,**所有实验当天亏 5%–10%**;两张结果表里多数奖励/特征组合为负(我按括号计数:时间事件环境 69 负/17 正,价格事件环境 61 负/23 正;如时间事件下 UPnL 全部为负,−11.67% 至 −56.52%)。
- **Evidence**:第 7 节与表 3,数字如上。BitMEX XBTUSD tick [金额已抹],盘口各档到中间价距离"99.99% 的时间不变"(6.1.1 节)——即大 tick、点差恒为 1 tick。
- **Test**:无直接实验。【推导】给我们的唯一信息是:我方费率 返佣 + 大 tick + 队尾模型下,RL 才勉强打平买入持有;我方返佣只有 我方费率,条件更差。
- **定性**:含费用与保守队列,但无延迟;结果不显著优于买入持有,**不构成净盈利证据**。

### B05c Spooner, Fearnley, Savani, Koukorinis (2018)《Market Making via Reinforcement Learning》

- **引用 + 读的版本**:AAMAS 2018;arXiv:1804.04216,<https://arxiv.org/pdf/1804.04216>,10 页。读了第 3 节(模拟器)、第 5 节评价方法与基准、5.4 节与表 6,其余检索(部分阅读)。**数据是 2010 年欧洲股票,不是加密。**
- **Strategy hypothesis**:【原文】表格型 RL(SARSA + 线性组合 tile coding),动作=买卖两侧挂单距离(以移动平均半点差为单位)+ 清仓;核心贡献是"非对称抑制"奖励:削弱持仓投机收益项,让智能体靠点差而非趋势赚钱。
- **Economic mechanism**:【原文】纯 PnL 奖励会学成趋势跟随、持大仓;抑制投机项后库存显著下降、样本外更稳。
- **Required data**:5 档盘口深度 + 成交,10 只股票,2010-01 至 08。
- **Holding horizon**:事件驱动,日内。
- **Expected signal**:点差、中间价变动、盘口/队列失衡、成交量失衡、波动、RSI + 自身库存与挂单距离。
- **Execution dependency**:【原文】只有聚合深度,撤单位置未知,假设"撤单在队列中均匀分布"来推队列位置;无市场冲击。全文未出现手续费、返佣、延迟(关键词检索无命中)。
- **Failure modes**:无费用、无延迟;2010 年数据;结果在不同股票间符号不一。
- **Evidence**:表 6 综合智能体样本外归一化日 PnL(单位 10⁴ 个点差):HSBA.L 15.43±13.01、GSK.L 7.32±7.23、VOD.L 5.02±6.35,但 ING.AS −3.21±29.05、NOK1V.HE −5.28±33.42;平均绝对持仓由固定价差基准的数百至数千降到个位到百位。Abernethy–Kale 基准在其更真实的模拟器中 10 只里 8 只为负,作者据此指出旧结果"可能不能推广到更真实的市场"(5.1 节)。
- **Test**:不照搬。可借鉴的只有奖励设计:若将来做学习型报价,目标函数要剔除持仓漂移(与我方"CL 利润大部分是持仓漂移"的教训一致)。
- **定性**:**未扣费用、无延迟**,非加密;不构成净盈利证据。

### B05d Jiang, Yang, Wang, Li, Huang, Li (2025)《Resolving Latency and Inventory Risk in Market Making with Reinforcement Learning》(RELAVER)

- **引用 + 读的版本**:arXiv:2505.12465,<https://arxiv.org/pdf/2505.12465>,15 页。读了摘要、4.1 节实验设置、结果段,其余检索(部分阅读)。**数据是中国股指期货(IC/IF/IH/IM,500 ms 快照),不是加密。**
- **Strategy hypothesis**:【原文】在带 30–100 ms 随机延迟、每 500 ms 批量撮合的环境里,RL 把"挂单持有时间"纳入状态-动作空间,用相对队列位置等指标决定是否保留旧单,以减少因延迟导致的无谓撤单与库存堆积。
- **Economic mechanism**:【原文】延迟使决策价与到达价不一致;保留队列中靠前的旧单比撤掉重挂更值钱。
- **Required data**:5 档盘口 + 成交,500 ms;样本外 2023-08 至 10(59 天)。
- **Holding horizon**:500 ms 决策,4 小时一局。
- **Expected signal**:相对队列位置、挂单存续时间、趋势预测器。
- **Execution dependency**:队列位置与延迟是模型核心;费率为参数 δ(数值未核到)。
- **Failure modes**:批量撮合、500 ms 快照与加密连续撮合不同;收益来自"持更多库存 + 趋势预测"(原文:"achieves higher profits by holding more inventory")。
- **Evidence**:表 2:IC、IH 环境利润 [金额已抹]、89.207;IM 环境 11.877 而其它方法为负。
- **Test(KuCoin)**:【推导】只取一个可检验点——"旧单的队列位置有价值"。在我方回放里统计:同一价位上挂单存续时间越长(队列越靠前)的成交,5 秒 markout 是否更好;若是,则在限频约束下应"少撤少改",把撤单预算留给盘口失衡明显不利的时刻。
- **定性**:含延迟与队列,但非加密、批量撮合;结论不可直接移植。

### B05e Gašperov, Begušić, Posedel Šimović, Kostanjčar (2021)《Reinforcement Learning Approaches to Optimal Market Making》(综述)

- **引用 + 读的版本**:Mathematics 9(21):2689,开放获取;读的是出版社 PDF <https://mdpi-res.com/d_attachment/mathematics/mathematics-09-02689/article_deploy/mathematics-09-02689.pdf>,23 页。读了第 4 节的统计小结(4.4、4.10–4.12)与第 5 节结论,逐篇综述表未细读(部分阅读)。
- **Strategy hypothesis**:【原文】综述 22 篇 RL 做市论文(2001–2021);结论是"研究者几乎一致认为 (D)RL 优于标准做市策略",但领域仍处早期。
- **Economic mechanism**:不适用(方法综述)。
- **Required data**:【原文】13/22(59%)用模拟器,多数基于解析做市模型;其中只有 4/13(31%)用历史数据标定;9/22(41%)直接回放历史数据(单一路径,"容易过拟合")。
- **Holding horizon**:不适用。
- **Expected signal**:【原文】状态变量中库存出现在 20/22(91%);点差 8/22;队列失衡 6/22;波动 6/22;RSI 6/22。
- **Execution dependency**:【原文】"多数现有工作(13/22,59%)完全忽略交易费用和其它市场摩擦,这在一定程度上削弱了其实用意义"(4.12 节)。
- **Failure modes**:【原文】"全部 22 篇都报告了正面结果"(4.10 节)——作者同时指出数据集、实验设定差异巨大,加上 DRL 的可复现性危机,无法横向比较。【推导】22/22 正面 + 59% 不计费用 = 发表偏差,不能当作 RL 做市有净利的证据。
- **Evidence**:见上,均出自 4.4、4.10、4.12 节。
- **Test**:无。用途是给 RL 类论文定基准:凡不计挂单费/返佣、不建模队列与延迟者,结果一律按"仅相对比较"处理。

### B05f Kumar (2023)《Deep Reinforcement Learning for High-Frequency Market Making》

- **引用 + 读的版本**:ACML 2022,PMLR 189;<https://proceedings.mlr.press/v189/kumar23a/kumar23a.pdf>,16 页。读了摘要、引言贡献段、第 2 节框架说明,其余检索(部分阅读)。
- **Strategy hypothesis**:【原文】在自建的"真实感"限价订单市场模拟器(含撮合引擎、FIX 接口、延迟管理器、NYSE 式 maker-taker 费)里训练 DRQN 做市智能体,优于 Spooner 等(2018)的 TD 基准;并用模拟器研究 maker-taker 费对市场质量与智能体盈利的影响。
- **Economic mechanism**:无新机制。
- **Required data**:**不使用真实行情回放**;是多智能体模拟("不受历史数据约束"),用复现典型事实来验证。
- **Holding horizon / Expected signal**:事件驱动;状态含队列失衡、成交量失衡等。
- **Execution dependency**:模拟器内含延迟与费用,但对手方是模拟的吃单者(动量型),逆向选择是设定出来的。
- **Failure modes**:模拟器中的"毒性"与真实市场无关;非加密;无真实数据样本外。
- **Evidence**:表 2 报告归一化 PnL 与平均绝对持仓;我未核对具体数值,不引用。
- **Test**:无。
- **定性**:含延迟与费用,但在模拟市场里;**不构成真实市场净盈利证据**。

### B06a Le, Nam Anh (2026)《Funding-Aware Optimal Market Making for Perpetual DEXs》

- **引用 + 读的版本**:arXiv:2605.06405v1(2026-05-07),<https://arxiv.org/pdf/2605.06405>,21 页。读了摘要、6.1–6.3 节(资金费率标定)、表 1、表 2 与第 7–8 节讨论,模型推导部分(第 3–5 节)只看了结构(部分阅读)。预印本,单一作者。
- **Strategy hypothesis**:【原文】把资金费率当作随机状态变量并入做市 HJB:库存既有价格风险,又产生随状态变化的资金费现金流;报价偏移由"库存价值差分"恢复。即:资金费为正且持续时,更愿意持空头库存(收资金费),报价向卖方倾斜。
- **Economic mechanism**:【原文】资金费率有持续性(小时级半衰期)但会跳;"funding-price innovation correlations are small",所以模型**不依赖资金费预测价格**,只把它当库存的持有收益/成本。
- **Required data**:Hyperliquid 每小时资金费 + 1 分钟 L2 中间价(ETH/BTC/SOL);成交强度用更早的官方成交数据标定;holdout 2025-11-26 至 2025-12-31。
- **Holding horizon**:小时(库存持有跨越多个资金费结算)。
- **Expected signal**:当前资金费率水平及其 OU 均值回复速度。
- **Execution dependency**:【原文】"This is not a queue-position or latency-aware execution model";成交用到中间价距离的指数强度模型模拟;不建模队列、延迟、maker 优先级、成交条件下的逆向选择(第 8 节)。
- **Failure modes**:【原文】资金费残差重尾,OU+跳的似然增益很大,纯 OU"不应被当作最终规律";SOL 的增益"主要是杠杆/风险偏好效应",经风险缩放的 AS 在 SOL 上赚得更多;BTC 胜率仅 0.57。【推导】我方失败项 4 已见:大的资金费差与逼空同时出现,价格腿亏——本文也确认资金费与价格创新相关性近零,即资金费不保护价格腿。
- **Evidence**:表 1:OU 半衰期 ETH 5.56 h、BTC 4.07 h、SOL 2.31 h;每小时跳概率 2.05%/1.24%/0.16%;资金费-价格创新相关 0.0026/0.0278/−0.0151。表 2(100 个种子,holdout 终值权益):ETH AS 74,472 → HJB 75,784(+1,312,胜率 0.62,库存 RMS 5.74→3.65);BTC 46,808 → 47,617(+809,胜率 0.57)。即相对经典 AS 的改进约 1.7%。
- **Test(KuCoin 合约)**:KuCoin 多数合约 8 小时或 4 小时结算。实验:对我方已在跑的 USDT→USDC 线,在库存偏斜项里加入"下次结算前预计资金费 × 剩余时间"的持有收益(例如资金费 +1 bp/8 h 时,允许空头库存的偏斜阈值放宽等值的 bp)。预登记指标:样本外总 PnL 提升且库存 RMS 不升;若提升 < 资金费收入本身(即只是多拿了方向暴露),判无效。
- **定性**:改进幅度小、模拟器无队列无逆向选择;**是库存管理的边际优化,不是新 edge**。

### B06b Zhai (2026)《Public Trader Identity: Adverse Selection and Return Predictability》

- **引用 + 读的版本**:arXiv:2608.04373v3(2026-08-23),<https://arxiv.org/pdf/2608.04373>,40 页。读了摘要、引言、3.1–3.2 节(钱包打分与持续性)、4.2 节预测结果与延迟检验、图 4 说明;附录未读(部分阅读)。预印本。
- **Strategy hypothesis**:【原文】无策略。命题是"毒性是钱包的持续属性":按主动单的 10 秒 markout 给钱包打分,排名跨相邻 10 天窗口保持(秩相关 0.52);跟踪最高分钱包的实时活动能提高 1 秒收益预测。
- **Economic mechanism**:【原文】逆向选择成本集中在很窄的尾部:控制市场、时间、单量、波动、点差后,markout 在前 15 个二十分位"保持平坦",最高一个二十分位升到 3.11 bp;最高十分位的 markout 从 0.5 秒的 1.25 bp 升到 10 秒的 2.11 bp,5 分钟仍高;其余 80%(D1–D8)接近零,与协议 TWAP 子单(机械执行)同一水平(3.2 节)。
- **Required data**:Hyperliquid 全量逐消息(下单/撤单/拒单/成交,带钱包地址);2026-07 十个最活跃永续,171 亿条消息,1430 万笔主动单,147,113 个钱包。
- **Holding horizon**:200 ms–30 秒;预测力在 0.5–1 秒达峰。
- **Expected signal**:匿名基准 10 个变量(最优档与 5 bp 内深度失衡、1 秒/30 秒报价更新 OFI、成交流、点差等)+ 身份块 11 个变量(毒性钱包的挂单、成交流、净买方广度)。
- **Execution dependency**:【原文】把全部特征延迟 200 ms,匿名基准的 1 秒 R² 从 10.88% 掉到 6.40%(ridge)、从 19.48% 掉到 9.64%(树)——"公开盘口状态比身份增量陈旧得更快"(4.2 节)。无交易回测、无费用。
- **Failure modes**:KuCoin 匿名,没有钱包地址;纯预测 R²,不是 PnL;样本 1 个月(另有 2025-12 独立样本复现,附录 C 未读)。
- **Evidence**:1 秒样本外 R²:匿名 10.88% → 加身份 12.31%(+13.2%,t=9.2);树模型 19.48% → 20.65%。在成交时刻评估,身份增量从 1.43 升到 2.47 个百分点。匿名基准里贡献最大的是近盘口深度失衡(去掉它损失 1.93 个百分点)。231 个最高十分位钱包中 91.3% 在验证期继续交易。
- **Test(KuCoin 合约)**:KuCoin 无身份,但可检验同一结构:把我方每笔被动成交按"吃单特征"分桶(单笔金额、是否连续同向扫多档、是否紧跟 Binance 跳动 1–3 ms、是否成对打印、是否等间隔等量的 TWAP 型),看 markout 是否同样"多数桶≈0、少数桶 −3 bp 左右"。若是,目标不再是预测价格,而是**只躲最毒的那一桶**(触发式撤单/缩量),撤单次数可压在限频内。判死:任何可观测分桶都分不开 markout(差 <1 bp)。
- **与我们实测的对应**:【推导】我方腰部币贴盘口 1–5 秒亏约 2 bp,与本文最高十分位 10 秒 2.11 bp 同量级——提示我方成交对手大比例落在毒性尾部,而不是"所有吃单都毒"。

### B06c Barone & Lillo (2026)《Trading in the Sunshine or in the Shade: Market Impact and Adverse Selection on Hyperliquid》

- **引用 + 读的版本**:arXiv:2606.15715v1,<https://arxiv.org/pdf/2606.15715>,31 页。读了摘要、引言结论段、第 3 节入场条件段与第 7 节开头,其余按关键词检索(部分阅读)。预印本。
- **Strategy hypothesis**:【原文】无做市回测。命题:公开可见的 TWAP(协议原生,每 30 秒一个子单,参数从开始就公开)信息含量低;做市方会主动为其提供流动性。
- **Economic mechanism**:【原文】Admati–Pfleiderer 预告交易:宣布者被识别为非知情 → 成本低;逆向选择成本转移到同向的隐藏大单上。
- **Required data**:Hyperliquid 地址级成交;430 万个重建的隐藏母单、46.5 万个原生 TWAP。
- **Holding horizon**:母单执行期(分钟到小时)及完成后 1.5–4 倍时长。
- **Expected signal**:等间隔、等量、同向的子单序列(原生 TWAP 均匀执行;隐藏母单是前重后轻的 U 形)。
- **Execution dependency**:无(非策略论文)。被动成交高度集中:按被动成交额排名前 40 个地址占约 68%。
- **Failure modes**:KuCoin 上 TWAP 不公开,只能统计识别,识别误差会把知情母单混进来;原生 TWAP 启动前 30 分钟价格已顺向走 +18.2 bp(趋势跟随),接它的库存要承担趋势。
- **Evidence**:可见 TWAP 的临时冲击比可比隐藏母单低约 9 bp;完成后价格位移少约 5 bp(表 2:−5.0 至 −5.5 bp,各期限均显著);同向可见 TWAP 占比每升 10 个百分点,隐藏母单的永久成本多 0.8–0.9 bp;TWAP 活跃期间显示深度上升、盘口向吸收侧倾斜。
- **Test(KuCoin 合约)**:在成交流里用规则识别"TWAP 型吃单"(同向、间隔方差小、单量方差小、≥5 笔)。比较我方被动成交中对手为 TWAP 型与非 TWAP 型的 5 秒/5 分钟 markout。预登记:TWAP 型 markout 比其余至少好 1.5 bp。通过后的用法:识别出活跃 TWAP 时,在其吸收侧保留/加厚挂单(真实成交意愿,不是虚假挂单),其余时间退到深档。

### B06d Garcia Seuma (2026a, 2026b) 强平瀑布两篇

- **引用 + 读的版本**:(a)《Where does the criticality live? Early-warning signals are event-heterogeneous across seven crypto-perpetual liquidation cascades》arXiv:2607.27070,13 页;(b)《Measuring the engine of a liquidation cascade: subcritical branching inside a first-order transition》arXiv:2608.03616,13 页。两篇都只读了摘要、引言与按关键词检索到的结果段(部分阅读)。预印本,单一作者。
- **Strategy hypothesis**:【原文】无策略。(a) 问:强平瀑布前有没有可复现的预警信号;(b) 用 Hyperliquid 链上成交日志直接测 2025-10-10 瀑布的"分支比"(一笔强平引发多少后续强平)。
- **Economic mechanism**:【原文】强平单对价格不敏感,其冲击把价格推向下一批强平线;但 (b) 测得分支比只有约 0.1–0.2(深度亚临界),严重程度由"外生冲击 × 路径上的强平分布 × 流动性撤出"决定,而不是由发散的乘数决定。
- **Required data**:(a) Binance USD-M BTCUSDT 1 分钟 K 线 + 5 分钟持仓量/多空比/吃单买卖量;(b) Hyperliquid 逐分钟资产上下文与节点成交日志。
- **Holding horizon**:分钟到小时(事件级)。
- **Expected signal**:【原文】(a) 唯一通过 300 次安慰剂起点检验的规律是瀑布前"吃单买卖比的方差收缩"(Fisher 合并 p≈5×10⁻⁶),但作者明说它是"总体层面的前兆,不是单事件警报"(6 个事件里 2 个单独看与零假设重叠)。价格的临界减速信号在 7 个事件里出现 5 个,恰好在两次突发消息(关税)事件中缺席。
- **Execution dependency**:无。
- **Failure modes**:样本只有 7 个事件;单事件预警"按构造就脆弱"(作者语)。
- **Evidence**:(b) 起爆后 88% 的强制卖出在 30 分钟内完成;62.6% 的强制卖出名义额被交易所兜底金库在盘口外吸收,最坏一分钟强平 [金额已抹]中金库接 [金额已抹]、盘口只接 [金额已抹];瀑布期间 Binance 的 Kyle 型冲击系数升到 1.2–3.5 倍(6 小时均值),Hyperliquid 报价冲击升到 3.2–9.1 倍;持仓量在 Hyperliquid 清掉 45%–70%,Binance BTC −24.6%。
- **Test(KuCoin 合约)**:【推导】这两篇对做市的含义是负面的:(1) 强平流大部分不经过盘口(在有兜底机制的场所),挂单能接到的只是小头;(2) 接到的那部分处在冲击系数放大数倍的时段。可做的唯一实验是风控性质的:以"过去 N 分钟吃单买卖比方差的分位数"作为缩量开关,回放 9 月数据看能否降低最大单日亏损而不显著减少收入;不作为 alpha。
- **与我们失败项的关系**:与失败项 5(接强平单)一致并给出原因:强平流前置、集中、且多数被场内机制吸收。

**补充 (c) Gornall, Rinaldi, Xiao (2025 初稿)《Perpetual Futures and Basis Risk: Evidence from Cryptocurrency》**,AEA 2026 会议稿 <https://www.aeaweb.org/conference/2026/program/paper/ByyFEfr4>,55 页,只读了摘要与"Liquidations"小节(部分阅读)。【原文】用 Kraken 与 Deribit 的强平数据:Kraken 永续上强平占成交量 1.9%–3.0%(永续推出前季度合约为 2.8%–3.6%,推出后降到 0.3%–0.7%);Deribit 两类合约都在 0.4%–0.8%。强平单成交的有效价差"只有几个基点","尽管是强制卖出,价格冲击有限"。【推导】平时的强平单量占比很小、付出的价差也只有几个基点——"接强平"在常态下既没有量也没有超额点差,只在瀑布时有量,而那时见 (b)。

**补充 (d) Giagkiozis & Said (2024)《Reconciling Open Interest with Traded Volume in Perpetual Swaps》**,Ledger 9:1–15;arXiv:2310.14973,11 页,读了摘要与按关键词检索到的结果段(部分阅读)。【原文】逐笔接入 7 家衍生品交易所(Bybit、Deribit、Binance、BitMEX、OKX、Kraken 等的 BTC 永续,不含 KuCoin):部分交易所报告的持仓量变化超过同期成交量所能解释的上限("完全不可信"),另一些"似乎延迟推送强平消息"。【推导】持仓量与强平推送不能未经核对就当实时信号用;在 KuCoin 上要先做同样的对账(|ΔOI| ≤ 区间成交量)。

### B07 报价/保证金币种分割(USDT 对 USDC)——文献缺口与三条间接证据

**检索结论**:针对"同一交易所、同一标的、USDT 计价(或保证金)市场与 USDC 计价市场之间谁领先、薄的一侧做市是否有溢价"的学术论文,我**没有找到**(arXiv、RePEc、搜索引擎多组关键词;SSRN 无法访问)。也没有找到同一交易所"币本位对 U 本位永续"之间高频领先关系的专门论文;Alexander & Heck (2020)《Price discovery in Bitcoin: the impact of unregulated markets》可能涉及,但其公开副本(Sussex figshare、SSRN)我取不到,未读。以下三条是能读到的间接证据,合成一张卡。

- **引用 + 读的版本**:(a) Galati (2023) 工作论文(见 B08a)的表 1、表 6 与 6.1 节;(b) Bieganowski & Ślepaczuk (2026)(见 B04a)6.1 节与图 7;(c) Mizrach (2023)《Stablecoins: Survivorship, Transactions Costs and Exchange Microstructure》arXiv:2201.01392v2,46 页,只读了第 7.2、8.2 节(部分阅读)。
- **Strategy hypothesis**:【推导,非任何论文的结论】同一标的在主流计价币(USDT)市场完成价格发现;薄的计价币(USDC)市场报价更宽、吃单流里有一部分是"看着 USDT 市场来捡过时报价"的套利者。若做市方自己以 USDT 市场为锚(同机房 0.3 ms),就免疫了这部分逆向选择,剩下的是更宽的点差。
- **Economic mechanism**:【原文 (a)】Binance 现货同一两周样本(2022-07-01 至 07-15):BTCUSDC 的 20 秒价格冲击高于 BTCUSDT,作者评:流动性差的交易对"信息不对称更大";取消手续费后 BTCUSDT 的价格冲击下降,而 EUR/GBP/USDC 对的价格冲击"基本不变"(6.1 节)。【原文 (b)】同一标的(W)的细 tick 永续中间价在粗 tick 现货点差内的位置,与现货盘口失衡相关 0.94——同场所内,细 tick/高流动性合约给出粗 tick/薄合约点差内部的"连续价格"。
- **Required data**:两个市场的 L1(至少)+ 成交;同一时钟。
- **Holding horizon**:(a) 的度量是成交后 20 秒;我方实测领先在毫秒级。
- **Expected signal**:USDT 侧中间价/微观价相对 USDC 侧报价的位置(基差偏离)。
- **Execution dependency**:依赖"在本场所内最快看到 USDT 侧"——不依赖比 Binance 知情者快。
- **Failure modes**:【推导】(1) 同档返佣的第二个做市商出现,点差被压到 USDT 侧水平;(2) USDC 脱锚时两侧基差漂移,锚失效(需 USDC/USDT 汇率作第三条腿);(3) 容量由 USDC 侧自然吃单流决定,无法靠放大挂单量扩张。
- **Evidence**:(a) 表 1 面板 A,Binance BTCUSDT 全样本均值:报价价差 0.9954 bp、有效价差 1.8918 bp、20 秒价格冲击 2.5706 bp、**已实现价差 −0.6789 bp**。表 6 面板 A,Binance BTCUSDC:报价价差 3.7461 bp、有效价差 4.3754 bp、价格冲击 4.321 bp、**已实现价差均值 +0.0544 bp(中位数 +0.6118 bp)**、每分钟 87 笔成交。【推导,由上述表中数字相除/相减】薄计价币市场的点差约为 USDT 市场的 3.8 倍,平均已实现价差高约 我方费率,但价格冲击也高约 1.75 bp。(c) Binance 上 USDC/USDT 稳定币对的买卖价差"一律约 0.01%";500 ms 内撤单占比(HFT 代理)Tether 在 Binance 为 46.7%,USDC 在 Binance 超过 25%。
- **Test(KuCoin 合约)**:(1) 复刻 (a) 的分解:对每个同时有 USDT 与 USDC 合约的币,算两侧的有效价差、20 秒价格冲击、已实现价差;再把 USDC 侧的价格冲击拆成"USDT 侧已先动"与"USDT 侧未动"两部分。预登记:前者占 USDC 侧价格冲击的一半以上——这就是我方能躲开的部分,也是这条线为什么赚钱的可证伪解释。(2) 外推检验:同一方法用于 KuCoin 的币本位合约对 U 本位合约、现货对永续;只有当"薄侧点差/厚侧点差 ≥2 且薄侧每日真实吃单额 ≥ 某下限"时才值得开线。(3) tick 版本:按 B04a,检查两侧 tick 粗细差异,粗 tick 侧用细 tick 侧定位排队方向。

### B08a Galati (2023 工作论文 / JBF 2024)《Exchange market share, market makers, and murky behavior: The impact of no-fee trading on cryptocurrency market quality》

- **引用 + 读的版本**:Journal of Banking & Finance 165, 107222(2024)。读的是 2023-10-18 的工作论文版《Boosting Exchange's Market Share: The Impact of No-Fee Trading on Market Quality》,Università del Molise Discussion Paper 091/23,<http://web.unimol.it/progetti/repec/mol/ecsdps/ESDP23091.pdf>,57 页。读了摘要、引言、指标定义(p.19–20)、表 2 与第 5 节结果段,其余检索(部分阅读)。工作论文数字可能与期刊版不同。
- **Strategy hypothesis**:【原文】不是策略。自然实验:Binance 2022-07-08 起对 BTC 现货交易对取消 maker 与 taker 费;处理组 Binance BTCUSDT,对照组 FTX、KuCoin 的 BTCUSDT 与 Binance ETHUSDT;样本 2022-07-01 至 07-15,毫秒级逐笔。
- **Economic mechanism**:【原文】零费后挂单方把报价价差拉宽、深度变浅,"流动性提供者的收益上升,代价由吃单方承担";同时逆向选择(价格冲击)下降。作者把它解读为可疑的做市行为。【推导】另一种读法:吃单免费后涌入大量低信息含量(含刷量)的吃单,单位成交的毒性被稀释。
- **Required data**:逐笔成交 + 最优报价(Refinitiv Tick History)。
- **Holding horizon**:价格冲击与已实现价差按成交后 **20 秒**中间价计算(p.20)。
- **Expected signal**:费率制度本身(是否零吃单费/促销)。
- **Execution dependency**:无成交模型;已实现价差是全市场平均,不含排队。
- **Failure modes**:单一事件、两周窗口;只有 BTC 现货;处理组在促销结束后份额回落。
- **Evidence**:表 2(Binance BTCUSDT,前→后,bp):报价价差 0.2872 → 1.7036;有效价差 1.8047 → 1.9788;20 秒价格冲击 3.6688 → 1.4724;**已实现价差 −1.8641 → +0.5064**。正文:已实现价差平均升 2.4 bp(双重差分口径 2.3 bp),报价价差升 1.4 bp,价格冲击降 2.2 bp;其它交易所与 Binance ETHUSDT 的挂单方"继续面对负的已实现价差"。表 1 面板 C(对照组 **KuCoin BTCUSDT 现货**,全样本均值):报价价差 0.4389 bp、有效价差 1.8438 bp、20 秒价格冲击 3.8927 bp、已实现价差 −2.0489 bp(中位数 −1.4947 bp)。
- **Test(KuCoin 合约)**:(1) 用同一口径(成交后 20 秒)算 KuCoin 各合约的全市场已实现价差,作为"不排队、不挑单"的基线;我方 −2 bp 与论文里 Binance 零费前的 −1.86 bp、KuCoin 现货的 −2.05 bp 同量级,说明这是行业基线而非我方执行问题。(2) 查 KuCoin 是否存在吃单费减免/零费促销的合约或时段;若有,比较促销内外的 20 秒价格冲击。预登记:促销期价格冲击低 ≥1 bp 才值得把挂单资源挪过去。
- **与我们失败项的关系**:解释失败项 1——在有吃单费的主流品种上,贴盘口挂单的平均已实现价差本来就是负的,约 −1.9 bp,我方费率 返佣补不上。

### B08b Brauneis, Mestel, Riordan, Theissen (2022)《The anatomy of a fee change — evidence from cryptocurrency markets》

- **引用 + 读的版本**:Journal of Empirical Finance 67:152–167。**只读到摘要**(RePEc 页面;全文付费墙)。
- **Strategy hypothesis / mechanism**:【原文,摘要】Coinbase Pro 对 BTC-USD 引入 maker 费并同时降低 taker 费;相对 tick 可忽略,可检验 Colliard–Foucault(2012)零 tick 模型。结果:报价价差上升,但升幅被 taker 费下降"超额补偿";报价深度与成交笔数下降,平均单笔变大。
- **Required data / Horizon / Signal / Execution**:未读正文,不写。
- **Failure modes**:单一事件。
- **Evidence**:摘要无数字。Galati 文中称自己测到的 1.4 bp 报价价差上升"幅度是 Brauneis 等(2022)的两倍"——这是二手转述,原文数字我未核实,不进入综合。
- **Test**:无独立实验。【推导】与 B08a 合起来的含义:在 tick 可忽略的品种上,挂单方会把自己承担的费率变化转嫁进报价价差;返佣档位的优势会被同档竞争者的更窄报价吃掉,只有档位高于边际竞争者时才剩下净优势。

### B08c Bozzetto, Sifat, Nahidi (2026)《Fee Structure and Order Flow Informativeness in the Cryptocurrency Market》

- **引用 + 读的版本**:收于 Springer《AI, FinTech, and the Future of Robo-Advisory》pp.315–328,开放获取;读的是出版社网页版 <https://link.springer.com/chapter/10.1007/978-3-032-18109-1_13>。读了摘要、数据节、第 5.1 节结果文字与第 6 节讨论;表格本体网页未展开(部分阅读)。书章,评审强度不明。
- **Strategy hypothesis**:【原文】不是策略。自然实验:Binance 2023-03 把 BTC/USDT 从零手续费改回收费,看订单流失衡(OFI)与成交流失衡(TFI)对**同期**中间价变动的解释力如何变化。
- **Economic mechanism**:【原文】手续费是"筛选机制":有费时只有信息价值足够高的单才会发出;零费时噪声单涌入,订单流信息含量被稀释。
- **Required data**:Binance BTC/USDT 现货盘口,2022-07-31 至 2023-07-31;回归频率 1 秒到 1 小时。
- **Holding horizon**:同期回归(不是预测);10 分钟、1 小时。
- **Expected signal**:OFI、TFI。
- **Execution dependency**:无。
- **Failure modes**:同期解释力不是可交易预测;文中事件日期前后不一(摘要写 3 月,数据节写 3 月 22 日,回归以 3 月 15 日分段);单一交易对。
- **Evidence**:OFI 的 R²:小时频率 5.03% → 11.15%;10 分钟频率 4.04% → 21.55%。收费后 TFI 单独解释小时价格变动的 51.78%;OFI+TFI 在 10 分钟频率 R² 56.30%。Chow 检验 F=1977.61。
- **Test(KuCoin 合约)**:与 B08a 合并为一个实验——"吃单方实际付多少费"决定流量毒性。按我方能观测的代理(成对打印占比、单笔规模分布)把合约分成"低费/补贴流量多"与"正常付费流量"两组,比较 TFI 对后续 5 秒中间价的解释力与我方 markout。【推导】含义对我们是双向的:付 我方费率 吃单费还来吃的单,平均信息价值必然高于 我方费率 + 半点差,所以贴盘口亏约 2 bp 是均衡结果,不是偶然。

### B09a Cong, Li, Tang, Yang (2022/2023)《Crypto Wash Trading》

- **引用 + 读的版本**:Management Science 69(11):6427–6454(2023)。读的是 NBER 工作论文 w30783(2022-12),<https://www.nber.org/system/files/working_papers/w30783/w30783.pdf>,74 页。读了摘要、引言(方法与主要结论)、数据说明段、附录中"交易所如何刷量"一段,其余检索(部分阅读)。
- **Strategy hypothesis**:【原文】不是策略。用三类统计规律检测虚假成交:(1) 成交量首位有效数字应符合 Benford 定律;(2) 真实交易的单笔数量应在整数处聚集(人的认知参照点);(3) 单笔数量的尾部应服从幂律。再用"非整数成交相对整数成交的超额比例"估计刷量占比。
- **Economic mechanism**:【原文】刷量为提高交易所排名与获客;机器生成的假单"舍入程度低"(有效小数位更多),且为避免被发现会限制单笔规模。刷量方式:直接打印成交记录;交易所自有账户自成交;用机器人在多个账户间真实下单对敲;或用返佣/交易挖矿激励用户对敲(附录)。
- **Required data**:公开逐笔成交(价格、数量、时间),29 家交易所,2019-07-09 至 2019-11-03,现货 BTC/ETH/LTC/XRP。**不需要账户级数据**。
- **Holding horizon**:不适用。
- **Expected signal**:首位数字分布、整数聚集度、尾部指数。
- **Execution dependency**:不适用。
- **Failure modes**:【原文】"仅凭成交历史极难识别具体哪一笔是刷量";交易所名称匿名化;2019 年现货。
- **Evidence**:未受监管交易所刷量平均占报告成交量 77.5%(中位数 79.1%);12 家二线交易所超过 80%;受监管交易所全部通过 Benford 检验,一线未监管交易所 20% 以上的检验不通过,二线 60% 以上不通过。附录:交易所自成交可通过"盘口深度与成交价差不匹配"发现。
- **Test(KuCoin 合约)**:把这三类检验按合约、按小时跑在我方采集的成交流上,并与已有的"成对打印"标记交叉:(a) 成对打印的单笔数量是否舍入更少、首位数字偏离 Benford;(b) 剔除成对打印后其余成交是否通过检验。用途是校准成交模型:**回放撮合时,被判为成对打印/刷量的成交不得消耗我方挂单的排队量、不得计入参与率分母**(我方 research3 已有此规则,这里给出独立的统计判据)。
- **对真实做市商成交模型的含义**:【推导】公开成交量 ≠ 可成交的对手流。若某合约约一半吃单额是自成交,则"按成交量比例估计的成交概率"应减半,而剩下的一半流量平均毒性更高——这与我方实测"成对打印占山寨吃单额约半数、真实吃单有毒"一致。

### B09b Le Pennec, Fiedler, Ante (2021)《Wash trading at cryptocurrency exchanges》

- **引用 + 读的版本**:Finance Research Letters 43, 101982。**只读到摘要**(RePEc;全文付费墙)。
- **Strategy hypothesis / mechanism**:【原文,摘要】用网站流量与托管的用户资金两类"成交量之外"的指标,在如实报告的交易所上标定"应有成交量",再与报告成交量比较。
- **Evidence**:【原文,摘要】有刷量证据的一组交易所把真实成交量夸大 25–50 倍;证据混合的一组夸大 1.25–33 倍。12 家交易所。
- **Required data**:网站流量、链上钱包余额、报告成交量(交易所级,不是合约级)。
- **Holding horizon / Signal / Execution**:不适用。
- **Failure modes**:只能给交易所级的总量比例,不能定位到合约或单笔。
- **Test**:无。对我们的用处仅是交叉校验:交易所级方法无法替代 B09a 的逐笔统计检验与我方的成对打印标记。

### B10 按流动性档位的做市盈利性——没有找到直接研究;三条旁证

**检索结论**:我没有找到按合约流动性档位(主流/腰部/长尾/新上市)比较做市商**净**盈利的学术或带数据的从业者研究。lo.tech《The State of Crypto Market Making Report 2025》(从业者报告,71 页,只做了关键词检索)是面向项目方的定性介绍(KPI、最小点差、合同条款),没有分档盈利数据,不采用。以下为旁证。

- **引用 + 读的版本**:(a) Bieganowski & Ślepaczuk (2026) 表 2、表 4(见 B04a,全文);(b) Nayyar (2025)《Backtesting Market Making Strategies in Crypto Landscapes》,University of Skövde 硕士论文(15 学分),<https://his.diva-portal.org/smash/get/diva2:1972292/FULLTEXT01.pdf>,34 页,读了摘要、数据与结果节(部分阅读;学生论文,非同行评审);(c) Barone & Lillo (2026)(见 B06c);(d) Galati (2023) 表 1、表 6(见 B07、B08a)。
- **Strategy hypothesis**:【推导】"越薄/越新越好做"是否成立。
- **Economic mechanism**:薄合约点差更宽(对做市有利),但单位成交的信息含量也更高、可成交量更小(不利)。
- **Required data**:各档合约的逐笔成交 + L1,统一口径的已实现价差。
- **Holding horizon**:20 秒至 5 分钟的 markout。
- **Expected signal**:点差/tick、真实吃单额、价格冲击占有效价差的比例。
- **Execution dependency**:薄合约上排队不是瓶颈,被动成交量才是。
- **Failure modes**:旁证之间口径不一;(b) 只有 2 天。
- **Evidence**:
  - (a) Binance 永续、同一信号的挂单回测,按市值档:BTC 年化 2.93,LTC 0.10,ROSE 0.27,ETC −0.07,ENJ −0.81;**五个币对买入持有的 t 检验 p 值全部 >0.05**。即:在这份回测里,小币的简单挂单并不比大币好,甚至更差。
  - (b) Bybit 新上市合约 CLANKER/USDT(2025-04-28 至 29),不计手续费、100 ms 步长:GARCH 报价策略从 [金额已抹]亏 [金额已抹],Roll 固定点差策略亏 [金额已抹];两者都累积了净多头库存。
  - (c) Hyperliquid 上被动成交高度集中:前 40 个地址占被动成交额约 68%。
  - (d) Binance 现货同一两周:BTCUSDT 已实现价差均值 −0.6789 bp;更薄的 BTCUSDC 为 +0.0544 bp(中位数 +0.6118 bp),但价格冲击 4.321 bp 对 2.5706 bp。KuCoin BTCUSDT(对照组,表 1 面板 C):报价价差 0.4389 bp、有效价差 1.8438 bp、价格冲击 3.8927 bp、**已实现价差 −2.0489 bp**。
- **Test(KuCoin 合约)**:做一张全合约横截面表(用已购的 9 月全合约日):每个合约的 有效半点差、20 秒与 5 分钟价格冲击、已实现价差(加 我方费率 返佣后)、剔除成对打印后的真实吃单额、点差/tick。按真实吃单额分五档看"返佣后已实现价差 × 真实吃单额"的日美元量。预登记:若没有任何一档的中位数为正,则"换档位"不是出路,出路只能是条件化(挑时刻、挑对手、挑锚)。注意 9 月四个全合约日在 research3 已用于别的检验,这张表只做描述,不调参。
- **与我们失败项的关系**:与失败项 6(Binance 没有的长尾合约,仅弱正)一致:薄 ≠ 好做;(d) 提示"薄 + 有同场所强锚"才出现非负的已实现价差。


---

## 二、综合

本节所有数字均已在对应卡片的原文文本中核对;卡片中标"未核实"或"仅摘要"的内容不在此引用。

### 2.1 有加密证据的不同做法(按做法,不按论文)

| # | 做法 | 机制(一句话) | 最好的证据(论文,数字) | 证据是否扣了现实费用/队列/延迟 | 是否依赖"最快" | 与我方失败项 1–6 的重叠 | 在 KuCoin 合约上证伪它的那一个实验 |
|---|---|---|---|---|---|---|---|
| A | 同场所强锚:在薄的计价币/粗 tick 合约上,围绕同场所的厚合约报价 | 【推导】薄侧点差更宽,其逆向选择有一部分来自"厚侧已先动"的套利者;以厚侧为锚可免疫这部分 | Galati 表 1/表 6(Binance 现货,同一两周):BTCUSDT 已实现价差 −0.6789 bp、价格冲击 2.5706 bp;BTCUSDC 已实现价差 +0.0544 bp(中位数 +0.6118)、价格冲击 4.321 bp、报价价差 3.7461 bp 对 0.9954 bp。Bieganowski 图 7:细 tick 永续在粗 tick 现货点差内的位置与现货失衡相关 0.94 | 否。全市场平均已实现价差(成交后 20 秒),未扣费、无排队、无延迟;且没有任何论文直接检验"以厚侧为锚做薄侧" | 只需在本场所内快(0.3 ms 足够),不需要快过 Binance 知情者 | 无重叠;就是我方在跑的 USDT→USDC 线 | 把 USDC 侧的 20 秒价格冲击拆成"USDT 侧已先动/未动"两部分;若"已先动"部分不到一半,这个解释不成立(B07 Test 1) |
| B | 挑流量:躲开毒性尾部,偏向 TWAP 型/机械型吃单 | 逆向选择成本集中在少数对手;预告/机械执行的流量信息含量低 | Zhai:控制后 markout 在前 15 个二十分位平坦,最高二十分位 3.11 bp;最高十分位 0.5 秒 1.25 bp → 10 秒 2.11 bp,其余接近零。Barone–Lillo:可见 TWAP 完成后价格位移比隐藏母单少 5.0–5.5 bp | 否。是 markout 与回归系数,不是做市 PnL;且证据来自带钱包地址的 Hyperliquid | 否。靠分类不靠速度;撤单是低频触发式,能放进限频 | 与失败项 2 相邻但不同:那是用本场所成交流做公允价,这是按对手类型决定接不接 | 用可观测特征(单笔规模、扫档、是否紧跟 Binance 跳动、成对打印、等间隔等量)给被动成交分桶;若没有任何分桶能把 markout 拉开 ≥1 bp,判死(B06b Test) |
| C | 大 tick 合约上争队列优先 | tick 相对点差越粗,盘口失衡越能预测下一跳,时间优先越值钱 | Bieganowski 6.1 节/图 5:失衡的 SHAP 贡献随相对 tick 增大;Sadighian 2020:BitMEX XBTUSD 各档到中间价距离 99.99% 的时间不变。旁证(非加密):Briola H10 的 MCC 小 tick 0.11、大 tick 0.29。反向证据:Dyhrberg(Kraken)tick 放大后已实现价差 −21.7 bp(−35.2%),深度 +32.4% | 否。全部是可预测性或市场质量指标 | 部分依赖:要在新价位上排到队首,本场所内快即可;但清空队列的那批吃单仍是知情方 | 与失败项 2 部分重叠(BTC 上失衡/微观价无改进;论文自己也是 BTC 吃单 p=0.75 不显著) | 只在点差≈1 tick 的 KuCoin 合约上,测队首成交的 5 秒 markout;仍 ≤ 我方费率 则判死(B03、B04a Test) |
| D | 状态开关:预计毒性/波动升高时撤出或加宽 | 订单流失衡 → 价格自相关与波动升高并持续 | Easley:Roll/VPIN 预测"已实现波动变化的符号"准确率 0.582(50 根 1 分钟 K 线回看,约 1 天前看);Bieganowski:固定点差挂单在 2025-10-10 闪崩中被单边连续成交;Garcia Seuma:瀑布前吃单买卖比方差收缩通过 300 次安慰剂检验,但作者明说不是单事件警报 | 否。预测的是分布统计量,不是 PnL | 否 | 是失败项 1 的条件化版本,不是新 edge | 按 Roll/VPIN 五分位比较我方挂单 markout;最高与最低分位差 <1 bp 或样本外反号,判死(B02 Test) |
| E | 资金费感知的库存偏斜 | 库存同时是价格敞口和资金费现金流;资金费有小时级持续性 | Le:OU 半衰期 ETH 5.560 h、BTC 4.071 h、SOL 2.310 h;holdout 终值 ETH 74,471.93 → 75,784.42、BTC 46,808.28 → 47,617.37(相对经典 AS);资金费与价格创新相关 0.0026/0.0278/−0.0151 | 否。作者自述"不是队列或延迟感知的执行模型",成交为强度模型模拟 | 否 | 与失败项 4、5 相邻:资金费不保护价格腿(相关性近零与我方"资金费差大时价格腿亏"一致) | 在已跑通的线上加资金费持有收益项;若 PnL 提升不超过多拿的方向敞口本身带来的资金费收入,判无效(B06a Test) |
| F | 选费率制度:去吃单方少付费/被补贴的地方挂单 | 手续费是筛选器;吃单免费时噪声流量涌入,单位成交毒性下降 | Galati 表 2(Binance BTCUSDT 零费前→后):20 秒价格冲击 3.6688 → 1.4724 bp,已实现价差 −1.8641 → +0.5064 bp。Bozzetto 等:恢复收费后 OFI 对同期价格变动的 R²(10 分钟)4.04% → 21.55% | 否。全市场平均、未扣费、无排队;且事件发生在现货 | 否 | 无重叠 | 先查 KuCoin 合约是否存在吃单费减免的合约/时段;存在则比较其内外 20 秒价格冲击,差 <1 bp 判死;不存在则此项不适用(B08a Test 2) |
| G | 机器学习预测短期方向后**吃单**(不是做市) | 盘口失衡、净吃单流预测 3 秒收益 | Bieganowski 表 1/表 4:吃单回测对买入持有的 t 检验仅 ETC、ENJ、ROSE 的 p<0.05;BTC、LTC 不显著;**同一信号的挂单回测五个币 p 全部 >0.05** | 部分。文中称报告含吃单费的结果(费率数值未写),但"延迟未建模,结果应视为最快情形下的上界" | 是 | 与失败项 2、3 重叠 | 不建议测;若测:加 我方费率 吃单费与我方 我方费率 ms 回路后净值 ≤0 即判死 |
| H | 强化学习学报价策略 | 智能体从盘口/订单流状态学挂单距离与库存控制 | Sadighian 2020(BitMEX,含 我方费率 返佣、我方费率 吃单费、队尾成交模型):30 天最好 17.61%,同期买入持有 16.25%,多数配置为负。Gašperov 综述:22 篇全部报告正面结果,而 13/22(59%)完全忽略费用与摩擦 | 只有 Sadighian 2020 计了费用与保守队列,仍无延迟 | — | 与失败项 1 重叠(学出来的仍是库存偏斜类策略) | 不测。没有一篇给出扣除现实费用、队列、延迟后的净盈利 |
| I | 接强平流 | 强平单对价格不敏感 | Garcia Seuma:2025-10-10(Hyperliquid 成交日志)起爆后 88% 的强制卖出在 30 分钟内完成,62.6% 被兜底金库在盘口外吸收;七次瀑布中 Binance 的冲击系数(6 小时均值)升至 1.2–3.5 倍;Gornall 等:Kraken 永续上强平占成交量 1.9%–3.0%,其有效价差"只有几个基点" | 否 | 否 | 即失败项 5;文献给出原因 | 已失败,不重测 |

注:RELAVER(B05d)提出"保留队列靠前的旧单、少撤少改",但数据是中国股指期货、批量撮合,**没有加密证据**,不列入上表;其可检验点并入做法 C 的实验。

### 2.2 在我方这些具体的延迟、费率、队列、合约、API 条件下,还有什么 edge 值得测?

排序依据:不需要快过 Binance 知情吃单者;用得上本场所内 0.3 ms;撤单少、放得进限频;有 0.7/我方费率 返佣;能接在已跑通的 USDT→USDC 线上。

1. **A 同场所强锚的外推(最值得)**。【原文】薄计价币市场点差数倍于 USDT 市场、平均已实现价差不为负,但价格冲击更高(Galati)。【推导】我方那条线赚钱的原因很可能正是"躲掉了来自厚侧的那部分价格冲击、留下了宽点差"。下一步不是加资金,而是找同构的配对:币本位对 U 本位、现货对永续、tick 粗细不同的同标的合约。每个候选先做 B07 Test 1 的冲击分解,再决定是否开线。容量小是结构性的(由薄侧真实吃单额决定),靠多配对并行而不是单配对放大。
2. **B 按流量类型挑对手**。【原文】毒性集中在最高十分位对手,其余接近零(Zhai);TWAP 型流量永久冲击小(Barone–Lillo)。【推导】我方"贴盘口 1–5 秒亏约 2 bp"与论文中最高十分位的 2.11 bp 同量级,说明问题可能是"接到的全是那一类单",而不是"所有单都毒"。这条不拼速度,撤单是触发式的。难点是 KuCoin 匿名,只能用行为特征代理;分桶实验成本低(用现有回放日志即可),先做。
3. **C 大 tick 合约的队首**。本场所内快有用,且"少撤、守队列"与限频相容。但文献证据全是可预测性,且 Dyhrberg 显示 tick 放大后每笔流动性提供回报是下降的。只作为筛选实验:先看 KuCoin 是否存在点差≈1 tick 的合约,再测队首 markout。
4. **F 费率制度**。检验成本最低(查一次 KuCoin 费率公告即可知道是否适用)。若 KuCoin 合约没有吃单费减免的合约或时段,直接划掉。
5. **D 状态开关**。不是 edge,是把已有策略的最坏时段切掉;作为风控项与 1、2 并行。
6. **E 资金费偏斜**。改进幅度在论文自己的模拟里也很小(ETH 终值 74,471.93 → 75,784.42),且模拟器无逆向选择;排最后,等 1 的线稳定后作为库存项微调。

不值得测:G(必须最快,且要付 我方费率 吃单费)、H(无净盈利证据)、I(已失败且文献解释了原因)。

**哪些机器学习结果只是可预测性、不是盈利性(明确列出)**

- 只报准确率/MCC/R²,没有任何成交与费用:Easley 等(预测的还是波动等统计量的变化符号,前看约 1 天)、Briola 等(作者主动拒绝报 PnL)、Kolm 等(仅摘要)、Jha 等、Fang 等、Lee、Zhai(R²)、Bozzetto 等与 Silantyev(同期解释力,连预测都不是)。
- 报了 PnL 但成交假设不现实:DeepLOB(中间价成交、未扣费毛利)、Khubiyev–Semenov(默认必成交、不排队)、Sadighian 2019(挂单费不计、默认插到队前)、Spooner 等(无费用无延迟)、Kumar(模拟市场)、Bieganowski–Ślepaczuk(无延迟;挂单结果全不显著)。
- 计了费用与保守队列的只有 Sadighian 2020,结果是多数配置为负、最好的也只略高于买入持有。
- 结论:本轮读到的机器学习/强化学习论文中,**没有一篇**给出同时扣除现实手续费、排队与延迟后的做市净盈利。

### 2.3 论文之间的矛盾

1. **tick 大小**:Briola 等、Bieganowski–Ślepaczuk 说大 tick → 更可预测(H10 的 MCC 0.29 对 0.11);Dyhrberg 等说 tick 放大后流动性提供的每笔回报(已实现价差)下降 21.7 bp、深度上升。【推导】不矛盾但指向不同:前者是"点差被 tick 锁住"的区间,后者是 tick 仍远小于点差的区间(上调后相对 tick 仅 0.2261–2.6517 bp,受约束时间 8.2%)。
2. **越薄越好做吗**:Bieganowski–Ślepaczuk 的挂单回测 BTC 最好(年化 2.93)、小币为负或接近零;Galati 的表里更薄的 BTCUSDC 平均已实现价差高于 BTCUSDT;Easley 等推测小币"无效率更大"。口径不同(策略回测 / 全市场平均 / 无数据的推测),没有一篇直接比较做市商净盈利。
3. **零手续费后为什么挂单方赚了**:Galati 解读为做市方"可疑地"拉宽价差、把优惠据为己有;Bozzetto 等解读为手续费是筛选器、零费时订单流信息含量被噪声稀释。两者数据方向一致(零费期价差更宽、价格冲击更低),解释相反。
4. **强化学习做市有没有用**:Gašperov 综述里 22 篇"全部正面";Sadighian 2020 加上费用与队列后多数配置为负;Spooner 等把 Abernethy–Kale 基准放进更真实的模拟器后,表 6 的 10 只股票里我数到 8 只为负。
5. **高准确率是否真实**:Jha 等(摘要 71%)、Fang 等(78%)对 Lee:常用平滑标签下不用模型的朴素预测即有 64.8%,只用价格序列时方向准确率为 50%。
6. **强平的价格冲击**:Gornall 等说"冲击有限、价差只有几个基点"(常态、平均);Garcia Seuma 说瀑布期冲击系数升到 1.2–3.5 倍(Binance)与 3.2–9.1 倍(Hyperliquid 报价口径)。是两种状态,不是同一事实的两种估计。
7. **毒性是普遍的还是集中的**:Easley 等据 VPIN 0.45–0.47 说加密"毒性更高";Zhai 的逐钱包 markout 显示 80% 的钱包接近零、尾部才毒。VPIN 用 1 分钟 K 线和 bulk volume classification 估,不是逐笔 markout,两者测的不是同一个量。
8. **Bieganowski–Ślepaczuk 文内不一致**:7.3 节文字说吃单与挂单"在多数资产上都盈利",表 4 却显示挂单策略五个币无一显著。

### 2.4 找过但没能读全文的论文(以及实际读到了什么)

| 论文 | 实际读到的 | 原因 |
|---|---|---|
| Stoikov 等 (2024) Market Making in Crypto | 仅搜索引擎给出的摘要级描述 | SSRN 403 + 机器人验证,无其它副本 |
| Kolm, Turiel, Westray (2023) Deep order flow imbalance | RePEc 摘要 | SSRN、Wiley 均 403 |
| Dyhrberg, Foley, Svec (JFQA 2023 终稿) | 期刊摘要;另读了 2019 年 EFMA 会议稿前半 | 期刊付费墙 |
| Brauneis, Mestel, Riordan, Theissen (2022) | RePEc 摘要 | 付费墙 |
| Le Pennec, Fiedler, Ante (2021) | RePEc 摘要 | 付费墙 |
| Silantyev (2019) | Springer 摘要 | 付费墙 |
| Galati (JBF 2024 终稿) | 2023 年工作论文版(部分) | ScienceDirect 403 |
| Cong, Li, Tang, Yang (Management Science 2023 终稿) | NBER 工作论文版(部分) | 终稿未取 |
| Alexander & Heck (2020) Price discovery in Bitcoin | 未读 | figshare 页面取不到文件,SSRN 403 |
| Albers 等 (2026) Hyperliquid [ID已抹] 数据 / "被拒订单预测收益" | 未读;只见于 Zhai 的引用 | 仅 SSRN |
| 《Order Book Liquidity on Crypto Exchanges》(JRFM 2025)、《High-frequency dynamics of Bitcoin futures》(2025)、Brauneis 等《Bitcoin unchained》(2022)、《Delayed Marks, Funding Memory, and Forecasting Liquidation-Tail Risk…》(Forecasting 2026) | 未读 | MDPI / ScienceDirect 403 |
| HLP、GMX、dYdX 流动性提供者收益的实证研究 | 没找到学术实证;只找到 Chitra 等 (2025)《Perpetual Demand Lending Pools》(机制理论,只看了摘要与目录)与若干无数据的从业者文章 | 文献缺口 |
| USDT 对 USDC 计价/保证金市场的价格发现与流动性溢价 | 没找到专门论文;见 B07 的旁证 | 文献缺口 |
| 按流动性档位的做市净盈利 | 没找到;见 B10 的旁证 | 文献缺口 |

另外看过但判定不对口、未写卡的:Anastasopoulos 等《Order Flow and Cryptocurrency Returns》(日/周频)、Plazuelo Pascual 等《Price Discovery in Cryptocurrency Markets》(DEX 对 CEX)、Fernández Vicente 博士论文《Market Making Strategies with Reinforcement Learning》(多智能体模拟,文中写明模拟里的买卖不计交易费)、Ochedzan & Antulov-Fantulin《The Impact of Market Informedness on Market Makers' Profitability》(纯智能体模拟)、lo.tech 2025 行业报告(定性)。
