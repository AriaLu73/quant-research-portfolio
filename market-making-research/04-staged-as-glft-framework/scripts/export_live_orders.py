#!/usr/bin/env python3
"""从实盘总线的 WAL(只读)导出某个时刻之后的全部订单类记录:下单、撤单指令、订单回报、成交。
用途(用户 10-15:"B 做完之后再 A"):量这次部署实盘真实的下单 / 撤单延迟、"在我方价位排到"的成交是在撤单发出后多久被打到的,
  再按实测改回测的延迟模型。
只读:只打开 WAL 段文件读,不写服务器上任何文件,不发任何东西;结果写到 --out 指定的文件(默认当前目录)。
每条记录一行 JSON:wal_ts_ns(总线落盘时刻,服务器本地时钟)、topic、msg_type,以及消息本身的全部字段(Decimal / 枚举转成字符串)。
用法(在服务器上):cd /opt/hft && sudo .venv/bin/python scripts/research7/export_live_orders.py --since 2026-10-15T05:18 --out live_orders_20261015.jsonl.gz
"""
import argparse, base64, dataclasses, datetime as dt, enum, gzip, json, os, sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from core.bus.wal import WalReader      # noqa: E402
from core.glue import bus_codec         # noqa: E402
from core.pb import bus_pb2             # noqa: E402

PREFIXES = ("trade.order.new.", "trade.order.cancel.", "trade.order.report.", "trade.fill.", "trade.signal.")


def plain(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, enum.Enum):
        return v.value
    if dataclasses.is_dataclass(v):
        return {f.name: plain(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="UTC 时刻,例 2026-10-15T05:18")
    ap.add_argument("--wal", default=os.path.join(ROOT, "data", "wal", "live"))
    ap.add_argument("--out", default="live_orders.jsonl.gz")
    ap.add_argument("--until", default="", help="UTC 截止时刻(不含),例 2026-10-15T00:00;空 = 不限")
    ns = ap.parse_args()
    since = int(dt.datetime.fromisoformat(ns.since).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    until = int(dt.datetime.fromisoformat(ns.until).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9 if ns.until else 0
    n, bad, kinds = 0, 0, {}
    with gzip.open(ns.out, "wt", encoding="utf-8") as fo:
        # 10-15:不用 replay 的 since_ns 按段名裁剪——服务器上所有段名用的是同一个前缀(总线启动时刻),按它裁剪只剩最后两段;
        # 改为读全部段、逐条按落盘时刻筛
        for seq, topic, ts_ns, raw in WalReader(ns.wal).replay(topic_prefix=PREFIXES, since_ns=0):
            if ts_ns < since or (until and ts_ns >= until):
                continue
            env = bus_pb2.BusEnvelope()
            try:
                env.ParseFromString(raw)
                obj = bus_codec.decode(env.msg_type, env.payload)
                rec = {"wal_ts_ns": ts_ns, "seq": seq, "topic": topic, "msg_type": env.msg_type, "obj": plain(obj)}
            except Exception as exc:  # noqa: BLE001 - 解不开的记原样,不中断
                bad += 1
                rec = {"wal_ts_ns": ts_ns, "seq": seq, "topic": topic, "decode_error": repr(exc)[:200]}
            fo.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            n += 1
            kinds[topic.split(".")[1] + "." + topic.split(".")[2]] = kinds.get(topic.split(".")[1] + "." + topic.split(".")[2], 0) + 1
    print("导出 %d 条(解不开 %d 条),按类别:%s → %s" % (n, bad, kinds, os.path.abspath(ns.out)))


if __name__ == "__main__":
    main()
