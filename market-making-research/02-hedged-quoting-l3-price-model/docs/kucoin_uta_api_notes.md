# KuCoin UTA V2 接口要点(2026-10-02 摘自官方 docs-new 原文;实现依据)
REST 基址 https://api.kucoin.com(colo:rest_spot 域名)。签名头与经典相同(KC-API-KEY / SIGN / TIMESTAMP / PASSPHRASE,v2 口令)。成功 code = "200000"。
- 下单 POST /api/ua/v2/unified/order/place(权重 1,Unified Account 池,权限 Unified)
  必填 tradeType(SPOT|FUTURES|MARGIN)、symbol(XBTUSDTM)、side(BUY|SELL)、orderType(LIMIT|MARKET)、size、sizeUnit(合约:UNIT=张 或 BASECCY;不给会被拒)。
  可选 clientOid(≤40)、price、timeInForce(GTC|IOC|FOK|RPI;GTT 合约不支持)、postOnly、reduceOnly、marginMode(ISOLATED|CROSS,缺省 CROSS)、stp(CO|CN|CB;合约无 DC)。
  UTA 不支持 positionSide。返回 data.{orderId, clientOid, tradeType}。活动单上限:每 UID [ID已抹]、每合约 500。
- 撤单 POST /api/ua/v2/unified/order/cancel(权重 1){tradeType, symbol(统一账户合约必填), orderId 或 clientOid} → data.{orderId, clientOid, ts}
- 按合约全撤 POST /api/ua/v2/unified/order/cancel-all(权重 20)
- 查单 GET /api/ua/v2/unified/order/detail?tradeType&symbol&orderId|clientOid(权重 4,Management 池)
  data:orderId, clientOid, symbol, side, orderType, size, sizeUnit, price, filledSize, avgPrice, fee, feeCurrency, cancelSize, status, updatedTime, tradeId …
  status:0 未触发 / 1 已触发 / 2 live / 3 filled / 4 partial filled(仍活动)/ 5 canceled / 6 partial canceled
- 未结订单 GET /api/ua/v2/unified/order/open-list?tradeType=FUTURES&pageNumber&pageSize(权重 4)→ data.{items[], totalPage}
- 持仓 GET /api/ua/v2/unified/position/open-list(权重 3)→ data[]:symbol, id, marginMode, size(张,带符号), entryPrice, markPrice, leverage, unrealizedPnL, realizedPnL, liquidationPrice, positionMargin …
- 账户 GET /api/ua/v2/unified/account/overview(权重 5)→ equity, availableMargin, im, mm, riskRatio, liability
        GET /api/ua/v2/unified/account/balance(权重 5)→ accounts[0].currencies[]:currency, equity, hold, balance, available, liability
- 杠杆 GET /api/ua/v2/unified/account/leverage?tradeType=FUTURES&symbol&marginMode=CROSS → [{symbol, leverage, marginMode}];改:POST …/account/modify-leverage(权重 20)
- 限频(UTA):按 UID、每秒重置;UTA Trading 池 我方费率档 我方费率/s … 我方费率档 我方费率/s;超限 HTTP 429 / 429000;响应头 gw-ratelimit-limit / remaining / reset。
私有推送 wss://wsapi-push.kucoin.com(colo:ws_push_private_pro)。连上先收 {"message":"welcome","pingInterval":18000,"pingTimeout":10000},再发鉴权:
  {"op":"auth","kc-api-key":K,"kc-api-timestamp":ms,"kc-api-sign":b64(HMAC_SHA256(secret, ts+"POST/api/websocket/users/verify")),"kc-api-passphrase":b64(HMAC_SHA256(secret, passphrase))}
  成功 {"id":…,"result":true};失败 {"result":false,"message":"auth failed"}。心跳 {"id":…,"op":"ping"} ↔ {"op":"pong"}(每秒超过一次会被断开)。
  订阅 {"id":…,"action":"SUBSCRIBE","channel":"orderAll","tradeType":"UNIFIED"};余额 {"action":"SUBSCRIBE","channel":"balance","accountType":"UNIFIED"};持仓 channel positionAll。
  订单推送 {"T":"orderAll.UNIFIED","P":推送 ns,"d":{oi 订单号, ci clientOid, os 状态码(同上), eT 事件 OPEN|UPDATE|FILL|CANCEL|TRIGGER|MATCH, tT FUTURES, s 合约, S BUY|SELL,
    oT LIMIT|MARKET, p 价, q 量, qU UNIT, fS 累计成交量, lS 本次成交量, ls 本次成交价, aP 均价, f 累计手续费, fC 费币种, lR MAKER|TAKER, ti 最新成交号, cS 撤销量, rS 剩余量, cR 撤单原因, O 下单 ns, U 更新 ns, pO, rO, stp, tIF}}
  成交推送 execution(.lite 无 f / fC):{"T":"execution.UNIFIED","d":{ti, oi, ci, s, S, oT, p, q, lR, E 撮合 ns, f, fC, fT NORMAL|ADL|LIQUID|SETTLEMENT}}
  余额推送 {"T":"balance.UNIFIED","d":{c 币种, b 余额, a 可用, e 权益, h 冻结, l 负债, U ns}}
WS 下单(第二步,未做):wss://wsapi.kucoin.com/v2/private(colo:ws_order_uta),同一套鉴权。
注:`/api/ua/v1/...` 一版已被官方列为废弃接口。
