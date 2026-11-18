# KuCoin 统一账户(UTA)下单通道:改动方案(2026-10-02,待用户确认后动代码)

## 0 起因与现状
- 用户账户是统一账户模式(`/api/ua/v1/account/mode` → `selfAccountMode: UNIFIED`),且必须用 UTA(延迟)。系统的 KuCoin 下单 / 回报 / 对账只接了经典接口。
- 2026-10-02 在 colo 机上用这把 key 只读验证(/tmp/uta_read.py):UTA V2 的读接口全部可用(code 200000)。
  统一账户权益 0、无币种余额、无持仓、无挂单;BTC-USDC / BTC-USDT 全仓杠杆都是 3。资金在**资金账户**(USDT 982.48、USDC 500),既不在经典合约账户也不在统一账户。
- 文档来源:KuCoin docs-new「UTA REST V2」「UTA WebSocket V2」(`/api/ua/v1/...` 那一版已列为废弃接口,不用)。

## 1 原则
- 只"加":`config/live/exchanges.yaml` 的 kucoin 段加 `account_mode: classic | unified`(缺省 classic),经典路径一行不改。
- 只动 KuCoin 相关:`core/glue/order_convert.py`、`gateway/order_gateway.py` 的 KuCoin 分支、`adapters/kucoin/main.py` 的私有通道与对账、`core/glue/adapter_mapper.py`(新增 UTA 映射函数)、配置与测试。
  不动:引擎、风控逻辑、行情通道(公共行情照旧走经典 WS,已在 colo 上正常)、其它交易所、策略。
- 行情不改意味着:策略看到的盘口、回测口径都不变。

## 2 接口对照(UTA V2,REST 基址 api.kucoin.com → colo 域名 rest_spot)
| 用途 | 经典(现有) | UTA V2(新增) | 权重 / 资源池 |
|---|---|---|---|
| 下单 | POST /api/v1/orders(合约域名) | POST /api/ua/v2/unified/order/place | 1 / Unified Account |
| 撤单 | DELETE /api/v1/orders/{id} | POST /api/ua/v2/unified/order/cancel | 1 / Unified Account |
| 查单(按 clientOid) | GET /api/v1/orders/byClientOid | GET /api/ua/v2/unified/order/detail?tradeType&symbol&clientOid | 4 / Management |
| 未结订单 | GET /api/v1/orders?status=active | GET /api/ua/v2/unified/order/open-list?tradeType=FUTURES | 4 / Management |
| 持仓 | GET /api/v1/positions | GET /api/ua/v2/unified/position/open-list | 3 / Management |
| 余额 | GET /api/v1/account-overview | GET /api/ua/v2/unified/account/overview + /balance | 5 / Management |
| 杠杆(只读) | GET /api/v2/getCrossUserLeverage | GET /api/ua/v2/unified/account/leverage | 10 / Management |
| 私有推送 | bullet-private + /contractMarket/tradeOrders、/contractAccount/wallet | wss://wsapi-push.kucoin.com(colo:ws_push_private_pro);频道 orderAll、execution.lite、balance、position,tradeType=UNIFIED | — |

下单报文(合约):`{tradeType: "FUTURES", symbol: "XBTUSDCM", clientOid, side: "BUY"|"SELL", orderType: "LIMIT"|"MARKET", size, sizeUnit: "UNIT", price, postOnly, reduceOnly, marginMode: "CROSS", stp: "CN"}`。
- `sizeUnit: UNIT` = 张数,沿用现有的"币 → 张"换算(XBTUSDCM 每张 0.0001 BTC、XBTUSDTM 每张 0.001 BTC),不引入新的数量口径。
- 订单不再带 leverage(UTA 的杠杆是账户 / 合约级设置)。
成交推送 execution.lite 的字段:ti 成交号、s 合约、p 价、q 量、S 方向、oi 订单号、ci clientOid、oT 订单类型、lR MAKER / TAKER、E 撮合时间。不含手续费 → 沿用现有的"按账户费率表计费"(`_apply_fee`)。

## 3 改动清单
1. `order_convert.to_kucoin_uta(order)`:上面的下单报文;单测逐字段对照文档。
2. `order_gateway`:account_mode = unified 时下单 / 撤单 / 查单走 UTA 路径与返回格式(`data.orderId`);错误码归一化补 UTA V2 错误码表。
3. `adapters/kucoin/main.py`:UTA 私有通道(连接、鉴权、订阅、心跳、重连);`map_private_message` 的 UTA 分支 → 现有的 OrderReport / Fill / Position / Asset 对象;
   启动对账 `fetch_snapshot_for_recon` 的 UTA 分支。私有 WS 的鉴权方式(token 还是签名)以 WebSocket V2 Introduction 为准,实现时先读原文。
4. 风控账本:统一账户只有一个保证金池 → 资产更新映射到合约池(现有 PT-05 / PT-10 用的 pool);两条腿共用,不再有两个钱包。
5. 限频:网关限速与策略令牌桶的权重按「Rate Limit Rule (UTA)」重设(UTA 下单与撤单权重都是 1;经典是 2 和 1)。只改配置值与策略参数,不改限速代码。
6. 测试:报文构造、各类推送的解析(用文档示例 + 实测抓到的真实消息)、对账、经典路径回归(现有测试全过)。

## 4 验证(回测覆盖不到这段代码)
- 单元测试:第 3 节的 1–6。
- 只读实测:私有通道能连上、能订阅;对账读回的余额 / 持仓与网页一致。(我可以做)
- **最小真单实测**:远离盘口挂一张最小单(BTC-USDC 1 张 = 0.0001 BTC ≈ [金额已抹],post-only)→ 收到挂单回报 → 撤单 → 收到撤单回报;再做一张会成交的最小单,核对成交回报、持仓、费率。
  这一步是真实下单,由用户触发 / 在场确认。顺带量下单与撤单的往返延迟(回测假设 1.5 ms;10-02 实测 UTA 的账户类读接口往返约 11–16 ms,下单接口未测)。

## 5 用户侧(与代码无关,现在就可以做)
- 资金从资金账户划到**统一交易账户**(现在统一账户里是 0)。
- BTC-USDC、BTC-USDT 的全仓杠杆从 3 调到 20。
- 给这把 API key 加 IP 白名单 我方IP(现在没有白名单)。

## 6 时间
约一天:接口与单测半天,私有推送与对账半天,之后是最小真单实测。之后才是 [金额已抹] 策略测试。

## 7 第二步(不在本次范围)
UTA WebSocket V2 支持用 WS 下单 / 撤单(Add Order / Cancel Order),比 REST 再快;本次先用 REST 把链路跑通,量过延迟再决定。

## 8 实施状态(2026-10-02 17:45)
- 第 3 节 1–3、6 已完成并部署到 colo 机;第 4 项(账本)沿用经典做法:统一账户各币种余额记入 U 本位合约池;第 5 项(限频配置)未改,待用户裁决。
- 测试:新增 36 条(tests/glue/test_kucoin_uta.py、tests/test_kucoin_uta_gateway.py、tests/test_kucoin_uta_adapter.py);非研究类全套 573 条通过(研究类测试因 .venv 无 pandas 无法收集,与本次无关)。
- colo 机只读实测:适配器以统一账户模式重启,私有通道走 colo 域名连接、鉴权通过、订阅成功;启动对账读回 0 项(账户为空)。
- 未完成:最小真单实测(scripts/kucoin_uta_smoke.py,用户本人带 --confirm 运行);真实推送报文与文档样例的逐字段核对要靠这一步。
