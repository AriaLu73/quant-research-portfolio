# MM-UH [金额已抹] 实盘测试:我方机房 部署记录与操作步骤(2026-10-02)

## 已完成(由 Claude 在 16:25–16:40 执行)
- 机器:i-00b0373dba87ece4f(我方机房),EIP 我方IP,主机指纹 SHA256:W/HWCaN+/ITeg/VYNOuMktK47tPA/LDYbwPwz//4jfc;原为空白系统。
- 安装包:deploy/out/hft_full_uh_20261002_162541.tgz(154 个文件,sha256 7f45b8ab…;deploy/build_uh_bundle.py 生成)→ 解包到 /opt/hft。
  不含密钥、数据、日志;配置与本地相同,唯一区别:exchanges.yaml 的 OKX simulated_trading 在包内为 1。实盘风控文件是保守档原样。
- 环境:apt(python3.12-venv、gcc-12、supervisor)、.venv 与依赖、protobuf、tickcodec 编译、目录权限(config/secrets 0700)。脚本 /tmp/install_uh.sh,日志 /tmp/install_uh.log。
- supervisor:七个程序全部登记、**autostart=false、均未启动**;hft-adapter-kucoin 带 HFT_KUCOIN_COLO=1。
- 校验:engine / adapters.kucoin / web.backend / microstructure 导入通过;strategies/deploy/MM_UH_FV2_v7.py 沙箱审计通过,sha256 4e0527b227de0ef1…(与本地一致)。
- 没做:录密钥、启动任何进程、改风控、上传 / 启动策略。

## 待用户操作(顺序)
1. KuCoin 账户:两个合约账户各入金 [金额已抹];XBTUSDCM、XBTUSDTM 两个合约设为全仓、杠杆 20。API key 只开合约交易 + 读取,绑定 IP 我方IP。
2. 录密钥(交互式,本人操作):
   ssh -i Downloads\CryptoMM.pem ubuntu@我方IP
   cd /opt/hft && .venv/bin/python scripts/encrypt_keys.py init && .venv/bin/python scripts/encrypt_keys.py set kucoin swap
3. 启动服务(顺序:broker → 适配器 → engine → web):
   sudo supervisorctl start hft-broker && sleep 3 && sudo supervisorctl start hft-adapter-kucoin && sleep 5 && sudo supervisorctl start hft-engine && sleep 5 && sudo supervisorctl start hft-web && sudo supervisorctl status
4. 开 Web 后台(不暴露公网,本机执行后浏览器开 http://127.0.0.1:8080):
   ssh -i Downloads\CryptoMM.pem -L 8080:127.0.0.1:8080 ubuntu@我方IP
5. Web 后台改合约风控七项(见 config/deploy_kucoin_uh_1k.yaml 的 web_risk_changes):日亏 [金额已抹] → 20;10 秒下单 20 → 300;每日下单 5000 → 150000;
   单品种占权益 0.20 → 0;主流币单笔占权益 0.60 → 2.5;KuCoin 杠杆上限 5 → 20;KuCoin 保证金模式加 cross。
   **"允许全仓"这一项是功能前提**:策略下单不带杠杆与保证金模式,风控层在允许全仓时把订单标成全仓;否则按逐仓、杠杆 1 发出(core/glue/order_convert.py to_kucoin),
   [金额已抹] 的远档单要 [金额已抹] 保证金,[金额已抹] 的账户会被交易所拒单。
6. Web 后台上传策略 strategies/deploy/MM_UH_FV2_v7.py(机器上已有同一文件),品类 swap_usdt、交易所 kucoin,参数用 config/deploy_kucoin_uh_1k.yaml 里 params 一节,启动。

## 需用户裁决的一项(基建配置,未动)
- 网关自己的限速 config/live/exchanges.yaml → kucoin.rate_limit.futures:rest_per_10s 100(下单 + 撤单合计每秒 10 次)、order_rate 15。
  策略平均每秒约 1.3 次请求,远低于它;但行情急的时候回测里 10 秒内最多 221 张单(加等量撤单)。超出时请求在网关里排队(最多等 5 秒,超时拒绝),
  撤单也排同一个队 → 急行情里撤单变慢,这是回测里没有的。KuCoin 最低档实际限额是 30 秒 2,000 权重,策略自己的令牌桶只用其中一半。
  放开到 rest_per_10s 300、order_rate 30 才与策略的预算一致。这是基建配置,按"不允许改基建"没有动。

## 第一小时要看的
- supervisor 各进程 RUNNING;logs/supervisor/*.err.log 无报错;Web 快照里两条合约行情在动。
- 下单 / 撤单被拒的原因码(PT-xx、EC_RATE_LIMIT、交易所拒单);对冲单是否成交、净敞口是否回零;当日盈亏。
- 任何一项异常:Web 后台紧急按钮(只读 / 平仓),或 sudo supervisorctl stop hft-engine。

## 2026-10-02 晚:行情与交易拆成两个进程(急动时管道排队的修复)

实盘首测发现:平时回路约 2 ms,行情急动时行情晚到 15–55 ms、撤单 21–37 ms 才生效(基线:BTC-USDT 永续盘口 p90 19.7 ms / p99 82 ms;撤单请求→交易所已撤 p90 11 ms / p99 30 ms)。改动:

| 项 | 内容 | 位置 |
|---|---|---|
| 订阅 | KuCoin 只留 XBTUSDTM、XBTUSDCM(现货留 KCS-USDT、币本位留 XBTUSDM,配置不允许品类为空) | 我方机房 `config/symbol_subscribe.yaml`(本机专用,打包部署会覆盖,需重做) |
| 盘口档数 | `depth_publish_levels` 50 → 5 | 我方机房 `config/live/exchanges.yaml`(只改这一行) |
| 进程角色 | `HFT_ADAPTER_ROLE=md`(只收行情、上报通道状态)/ `trade`(下单、撤单、私有回报、对账);缺省 `all` = 原行为 | `adapters/base.py`;supervisor:`hft-adapter-kucoin`(md)+ `hft-adapter-kucoin-trade` |
| 撤单直写 | 引擎撤单帧不再排出流队列,立刻写总线 | `core/bus/tcp_bus.py::publish_nowait`、`engine/main.py::_send_cancel` |
| 撤单限流 | 429000 / 429001 立刻重试并换通道(长连接 ↔ REST),间隔 0 / 10 / 20 / 40 / 80 ms | `gateway/order_gateway.py` |
| 撤单确认 | 撤单受理不再报"已撤";终态认推送,1 s / 3 s 无推送则查单;仍在挂则重撤(最多 5 轮) | `gateway/order_gateway.py`、`adapters/kucoin/main.py` |

拆分后的注意事项:
- 成交 / 回执 / 撤单失败日志在 `logs/supervisor/adapter-kucoin-trade.err.log`;行情通道日志仍在 `adapter-kucoin.err.log`。
- 交易进程不上报通道状态(引擎把"未连接"当行情断流而撤单),所以 Web 上的 REST 成败计数为 0;改看交易进程日志里每分钟一行的"交易通道指标"。
- 启动顺序:broker → hft-adapter-kucoin(md)→ hft-adapter-kucoin-trade → hft-engine。两个适配器任何一个没起来都不要启动策略。
- 验证延迟:`sudo .venv/bin/python /tmp/wal_lag.py <录制段>`(行情滞后与撤单生效的分位数)。
- 系统盘只有 8 G,总线录制要留意(`df -h /`);策略启动前的旧段可挪走或删除。
