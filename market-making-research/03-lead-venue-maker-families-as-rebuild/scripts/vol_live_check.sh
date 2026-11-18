#!/usr/bin/env bash
# Read-only health check of the MM_VOL_BTC_v1 live test on the colo host. Prints a short summary; changes nothing there.
S="AppData/Local/Temp/claude/E--HFT--/[id removed]/scratchpad"
timeout 90 ssh -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o BatchMode=yes -o ConnectTimeout=15 \
  -o UserKnownHostsFile="$S/colo_known_hosts" -i "Downloads/CryptoMM.pem" ubuntu@OUR_IP 'bash -s' <<'REMOTE'
echo "utc $(date -u '+%m-%d %H:%M:%S')"
echo "procs: $(sudo -n supervisorctl status | awk '{print $1"="$2}' | grep -v 'okx\|htx' | tr '\n' ' ')"
cd /opt/hft/logs/live
T=$(date -u -d '-12 min' '+%Y-%m-%d %H:%M:%S')
recent() { awk -v t="$T" 'substr($0,1,19) >= t' "$1"; }
O=/opt/hft/logs/supervisor/engine.out.log
echo "--- engine.out.log written $(stat -c '%y' $O | cut -c1-19); VOL_STAT $(grep -c VOL_STAT $O), fills $(grep -c VOL_FILL $O), flags $(grep -c VOL_FLAG $O)"
echo "--- last VOL_STAT"
grep 'VOL_STAT' $O | tail -2 | cut -c1-1400
echo "--- last flags"
grep 'VOL_FLAG' $O | tail -4 | cut -c1-300
echo "--- last fills / markouts"
grep 'VOL_FILL\|VOL_MARK' $O | tail -4 | cut -c1-320
echo "--- strategy lifecycle"
grep 'MmVolBtc' engine.log | grep -v '风控拦截' | tail -4 | cut -c1-23,95-300
echo "--- risk blocks in last 12 min: $(recent engine.log | grep -c '风控拦截')"
recent engine.log | grep '风控拦截' | tail -2 | cut -c1-300
echo "--- engine WARN/ERROR in last 12 min: $(recent engine.log | grep -c '|WARN|\||ERROR|\||CRITICAL|')"
recent engine.log | grep '|WARN|\||ERROR|\||CRITICAL|' | tail -8 | cut -c1-330
echo "--- adapters ERROR in last 12 min"
for f in adapter-kucoin-md.log adapter-kucoin-trade.log adapter-binance.log; do
  echo "$f: $(recent $f | grep -c '|ERROR|\||CRITICAL|') $(recent $f | grep '|ERROR|\||CRITICAL|' | tail -1 | cut -c1-240)"
done
echo "--- engine stderr: $(grep -c 'Traceback' /opt/hft/logs/supervisor/engine.err.log) tracebacks"
REMOTE
