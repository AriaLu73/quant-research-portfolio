#!/usr/bin/env bash
# 等到 DAYDONE 的天数超过 $1;打印新完成的日期。
cd .
until [ "$(cat logs/r3_alldata_chainA.log logs/r3_alldata_chainB.log 2>/dev/null | grep -c '^DAYDONE')" -gt "$1" ]; do sleep 60; done
cat logs/r3_alldata_chainA.log logs/r3_alldata_chainB.log | grep '^DAYDONE'
