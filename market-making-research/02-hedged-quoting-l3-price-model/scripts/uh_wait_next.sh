#!/usr/bin/env bash
# research3:等任一条全天链再跑完一天,然后打印逐日结果(只读)。用法:bash scripts/research3/uh_wait_next.sh
cd "$(dirname "$0")/../.."
L="logs/r3_C5P1_chainA.log logs/r3_C5P1_chainB.log logs/r3_CXRP5k_chain.log logs/r3_C5ETH_chain.log"
[ "$1" = "btc" ] && L="logs/r3_C6S15_chainA.log logs/r3_C6S15_chainB.log"
n0=$(cat $L 2>/dev/null | grep -c "^DAYDONE")
until [ "$(cat $L 2>/dev/null | grep -c '^DAYDONE')" -gt "$n0" ]; do sleep 45; done
bash scripts/research3/uh_all_status.sh | grep -v "^折算\|含在跑的\|^  ALL"
for f in $L; do [ -f "$f" ] && echo "$f $(grep '^DAYDONE' $f | tail -1)"; done
true
