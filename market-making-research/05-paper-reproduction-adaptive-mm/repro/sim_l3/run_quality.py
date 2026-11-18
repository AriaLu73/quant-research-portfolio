"""阶段 0:按合约跑 research_mm 的 l3_quality.scan_day / trade_gaps.main(先注入合约常量)。
用法  python run_quality.py scan <sym> <YYYYMMDD>
      python run_quality.py trade_gaps <sym>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine_bridge as B   # noqa: E402

if __name__ == "__main__":
    mode, sym = sys.argv[1], sys.argv[2]
    B.patch_engine(sym)
    if mode == "scan":
        import l3_quality as Q
        Q.scan_day(sys.argv[3], sym)
    elif mode == "trade_gaps":
        import trade_gaps as T
        T.main(sym)
    else:
        raise SystemExit("mode ∈ {scan, trade_gaps}")
