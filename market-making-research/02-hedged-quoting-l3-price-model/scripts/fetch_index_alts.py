#!/usr/bin/env python3
"""research3 H-I:给山寨合约补拉 KuCoin 自己的 1 秒指数价历史(公开 REST,只读;复用 research4/fetch_index_hist.py)。
输出到 data/research3/index_hist(与 research4 的目录分开,不干扰另一会话);限速放慢(另一会话可能同时在拉,限频按 IP 共享)。
用法:python fetch_index_alts.py 20260910,20260924,20260918,20260921 @data/research3/index_syms_alts.txt"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research4"))
import fetch_index_hist as F
F.OUT = os.path.join(ROOT, "data", "research3", "index_hist")
F.MIN_GAP_S = float(os.environ.get("IDX_MIN_GAP", "0.12"))
if __name__ == "__main__":
    F.main()
