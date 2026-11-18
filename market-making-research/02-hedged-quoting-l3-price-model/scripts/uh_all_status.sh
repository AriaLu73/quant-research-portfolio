#!/usr/bin/env bash
# research3:三条全天链(BTC 利润版 / XRP / ETH)的逐日结果 + 行为审计是否全过。只读。
cd "$(dirname "$0")/../.."
date "+%H:%M"
for p in C6S15 C5P1; do
  echo "== $p  已完成的天: $(ls data/research5/runs/${p}_2026*.json 2>/dev/null | wc -l) 个文件(含在跑的)"
  .venv/Scripts/python.exe -X utf8 scripts/research3/uh_portfolio_report.py $p 2>&1 | grep -v "^组合\|^品种\|^限频"
  for f in logs/r3_${p}_2026*_behaviour.txt; do [ -f "$f" ] && ! grep -q "BEHAVIOUR PASS" "$f" && echo "审计未过: $f"; done
done
