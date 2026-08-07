#!/bin/bash
# 切替前後の疎通チェック (CPE 配下の Linux クライアントで実行)
#   出力をそのまま切替エビデンスとして保存する:
#     ./run-checks.sh | tee $(date +%Y%m%d-%H%M)-checks.log
set -u

V4_TARGET="203.0.113.80"
V6_TARGET="2001:db8:cafe::80"
DNS_NAME="www.lab.example"
PASS=0; FAIL=0

check() {  # check <名称> <コマンド...>
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "PASS: $name"; PASS=$((PASS+1))
  else
    echo "FAIL: $name"; FAIL=$((FAIL+1))
  fi
}

echo "=== IPoE 切替チェック $(date '+%F %T') ==="
echo "--- アドレス/経路 ---"
ip -6 addr show scope global | grep -E 'inet6|^[0-9]' || echo "(グローバル IPv6 なし)"
ip route show default; ip -6 route show default

echo "--- 疎通 ---"
check "IPv4 ping (${V4_TARGET})"      ping -c2 -W2 "$V4_TARGET"
check "IPv6 ping (${V6_TARGET})"      ping -c2 -W2 "$V6_TARGET"

echo "--- DNS ---"
check "A 解決 (${DNS_NAME})"          sh -c "getent ahostsv4 $DNS_NAME | grep -q ."
check "AAAA 解決 (${DNS_NAME})"       sh -c "getent ahostsv6 $DNS_NAME | grep -q ."

echo "--- HTTP 到達性 (応答に出口アドレスが表示される) ---"
curl -4 -s --connect-timeout 5 "http://${V4_TARGET}/" || echo "FAIL: HTTP v4"
curl -6 -s --connect-timeout 5 "http://[${V6_TARGET}]/" || echo "FAIL: HTTP v6"
check "HTTP over IPv4"                curl -4 -s --connect-timeout 5 -o /dev/null "http://${V4_TARGET}/"
check "HTTP over IPv6"                curl -6 -s --connect-timeout 5 -o /dev/null "http://[${V6_TARGET}]/"

echo "--- MTU 実測 (DF 付き ping, payload = MTU-28) ---"
for size in 1472 1432 1426; do   # 1500 / 1460(MAP-E,DS-Lite) / 1454(PPPoE)
  if ping -c1 -W2 -M do -s "$size" "$V4_TARGET" >/dev/null 2>&1; then
    echo "INFO: IPv4 パス MTU >= $((size+28)) (payload ${size} 通過)"
    break
  else
    echo "INFO: payload ${size} 不可"
  fi
done

echo "--- DNS フォールバック体感 (v6 障害注入時に遅延が出る) ---"
t0=$(date +%s%N); curl -s --connect-timeout 15 -o /dev/null "http://${DNS_NAME}/"; rc=$?
t1=$(date +%s%N); echo "INFO: http://${DNS_NAME}/ 所要 $(( (t1-t0)/1000000 )) ms (rc=$rc)"

echo "=== 結果: PASS=${PASS} FAIL=${FAIL} ==="
[ "$FAIL" -eq 0 ]
