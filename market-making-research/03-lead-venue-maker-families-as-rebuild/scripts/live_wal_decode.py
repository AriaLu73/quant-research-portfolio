"""Read-only: decode order / cancel / report / fill events of the live bus journal into one JSON line each."""
import base64, gzip, sys, json, zlib, dataclasses, enum, decimal
sys.path.insert(0, r"")
import orjson
from core.pb import bus_pb2
from core.glue import bus_codec

def plain(o):
    if dataclasses.is_dataclass(o):
        return {k: plain(v) for k, v in dataclasses.asdict(o).items()}
    if isinstance(o, enum.Enum):
        return o.value
    if isinstance(o, decimal.Decimal):
        return str(o)
    if isinstance(o, dict):
        return {str(k): plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [plain(v) for v in o]
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    if hasattr(o, "__dict__"):
        return {k: plain(v) for k, v in vars(o).items() if not k.startswith("_")}
    return str(o)

src, dst = sys.argv[1], sys.argv[2]
n = 0
with open(dst, "w", encoding="utf-8") as out:
    try:
        with gzip.open(src, "rb") as fh:
            for line in fh:
                if b'"topic":"trade.' not in line[:70]:
                    continue
                r = orjson.loads(line)
                env = bus_pb2.BusEnvelope(); env.ParseFromString(base64.b64decode(r["b64"]))
                try:
                    if env.msg_type == "KVGroup":        # cancels: a protobuf map, not a dataclass - str() of it is useless
                        kv = bus_pb2.KVGroup(); kv.ParseFromString(env.payload); o = dict(kv.entries)
                    else:
                        o = bus_codec.decode(env.msg_type, env.payload)
                except Exception as e:
                    o = {"decode_error": repr(e)[:100]}
                out.write(json.dumps(dict(seq=r["seq"], ts_ns=r["ts_ns"], topic=r["topic"], type=env.msg_type, src=getattr(env, "source", ""), msg=plain(o)), ensure_ascii=False) + "\n")
                n += 1
    except (EOFError, OSError, zlib.error):
        pass
print("decoded", n)
