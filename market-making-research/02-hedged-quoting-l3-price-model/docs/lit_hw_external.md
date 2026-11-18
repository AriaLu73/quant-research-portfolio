# H-W(拦截成对打印)的外部资料检索(2026-10-01,用户要求:论文与 GitHub 有没有人写过)

## 结论
- **没有找到讲"如何拦截成对打印赚钱"的论文或公开策略代码。** 找到的是另一面:刷量方自己的开源代码,以及学术界检测刷量的方法。前者直接验证了我们的机制假设,后者给"罕见量"过滤提供了依据。

## 1. 开源刷量机器人:ADAMANT TradeBot(github.com/Adamant-im/adamant-tradebot,trade/mm_trader.js)
[代码事实,经网页抓取摘要,未逐行人工核对]
- 用途:给代币项目方"做交易量、维持点差和深度"。支持两套账户/密钥。
- **点差内成交(executeInSpread)的顺序:先用账户 1 挂一张限价单(maker),再用账户 2 以同一价格下一张限价单(taker)去吃它。**
  `order1 = await makerApi.placeOrder(makerOrderSide, pair, price, coin1Amount, 1, null)` → `order2 = await takerApi.placeOrder(side, pair, price, coin1Amount, 1, null)`
- 价格:在点差内随机取,下限 = 最高买价 + 1 个最小价位,上限 = 最低卖价 − 1 个最小价位。数量:在 mm_minAmount…mm_maxAmount 之间随机(再乘波动系数)。
- 点差不足 2 个最小价位时不做点差内成交,改为打自己的盘口。
- **代码里明确处理两种"被第三方截胡":**
  - 情形 1:maker 单被第三方机器人先吃掉,taker 单没成交;
  - 情形 2:"After a maker order is placed, a third party quickly places another order just before it, and the maker order remains unfilled"——**正是 H-W 的做法**。
  - 两种情形都会调用 `sniperBotActivity(...)` 计数,并撤掉剩余订单。计数之后做什么(暂停、换模式)在公开代码里看不到,属于付费版的"Anti-cheat"模块。
- 对我们的含义:
  1. 假设 1(对方吃单腿是普通限价单、价格更优的单先成交)对这一类机器人**成立**;taker 是限价单且价格 = maker 价,所以我方必须挂在更优价(内 1 tick),同价不行。
  2. 假设 3(对手会察觉)的风险是**真实且内建的**:它每次被截都在计数。持续时间无法从公开资料判断。
  3. 数量随机 → 与我们"成对打印用零散量"的观察一致,支持用"罕见量"识别。
  4. 两腿之间的间隔取决于它两次下单请求的往返(我们数据里峰值 3–4 ms,另有近一半 ≤ 1 ms 的拦不到)。
- 同类:Hummingbot 的 order_optimization("jump orders")是公开的"压到最优价前一档"的实现,对应我们数据里那个 2–4 ms 的抢一档机器人。

## 2. 检测刷量的论文(给"罕见量过滤"提供依据)
- Cong, Li, Tang, Yang, "Crypto Wash Trading"(Management Science):用成交量首位数字(Benford)、**成交量取整/聚集**、尾部分布检测;未受监管交易所平均 70% 以上成交量是刷出来的。
- Aloosh & Li, "Direct Evidence of Bitcoin Wash Trading"(Management Science 2024):用 Mt. Gox 泄露的账户级数据直接验证,Benford、**成交量聚集**、对数正态等间接指标有效。
- Victor & Weintraud, "Detecting and Quantifying Wash Trading on Decentralized Cryptocurrency Exchanges"(arXiv 2102.07001):在链上限价簿交易所按"净头寸不变的闭环"识别,自成交与双账户结构为主。
- Bitwise 2019 向 SEC 的报告:可疑交易所的成交打印在点差内、成交量直方图异常。
- 用法:这些文献说明真实交易者的量有聚集/取整规律,而刷量是另一种分布;我们的过滤是其逆用——抢一档机器人用固定量,成对打印用随机量。阈值应写成逐合约滚动的似然比/期望值门槛,而不是固定 0.5%。

## 3. 压一档 / 抢队 / 延迟竞速(给"存活时间""内 1 tick"提供依据)
- Buti, Consonni, Rindi, Wen, Werner 的一组文章("Sub-Penny Trading and Queue Jumping"、"Tick Size, Trading Strategies and Market Quality"):小 tick 助长压一档(undercutting),对不活跃品种尤甚。
- Aquilina, Budish, O'Neill, "Quantifying the High-Frequency Trading Arms Race"(已在我方文献库):延迟竞速的窗口应从报文数据里量出来——对应把"存活 3 ms"改成逐合约滚动估计的对手反应时间分位数。
- 库存上限:GLFT / Bergault 的风险预算形式(已在文献库)。

## 来源
- https://github.com/Adamant-im/adamant-tradebot
- https://docs.hummingbot.org/strategy-configs/order-optimization
- https://arxiv.org/abs/2102.07001
- https://doras.dcu.ie/32898/1/Direct%20evidence%20of%20bitcoin%20wash%20trading.pdf
- https://quantpedia.com/detecting-wash-trading-in-major-crypto-exchanges/
- https://keyrock.com/wash-trading-effects-on-crypto-markets/
- https://unsw.edu.au/business/sites/default/files/seminars-conferences/Sub-Penny-and-Queue-Jumping.pdf
