#!/usr/bin/env bash
# 等两条链都跑完第 ($1 + 1) 天(或都结束)。
cd .
cnt() { grep -c '^DAYDONE' "$1" 2>/dev/null || echo 0; }
until { [ "$(cnt logs/r3_ALLFV5k.log)" -gt "$1" ] && [ "$(cnt logs/r3_ALLFV10k.log)" -gt "$1" ]; } || { grep -q '^CHAINDONE' logs/r3_ALLFV5k.log && grep -q '^CHAINDONE' logs/r3_ALLFV10k.log; }; do sleep 60; done
grep '^DAYDONE' logs/r3_ALLFV5k.log | tail -1; grep '^DAYDONE' logs/r3_ALLFV10k.log | tail -1
