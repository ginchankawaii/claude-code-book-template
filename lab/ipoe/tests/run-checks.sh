#!/bin/bash
# 切替前後の疎通チェック (CPE 配下の Linux クライアントで実行)
#   出力をそのまま切替エビデンスとして保存する:
#     ./run-checks.sh | tee $(date +%Y%m%d-%H%M)-checks.log
#
#   期待する出口アドレスを渡すと、経路そのものを検証できる (強く推奨):
#     EXPECT_SRC4=198.51.100.10 ./run-checks.sh      # MAP-E (PD 方式)
#     EXPECT_SRC4=198.51.100.20 ./run-checks.sh      # MAP-E (RA 方式)
#     EXPECT_SRC4=203.0.113.1   ./run-checks.sh      # DS-Lite (AFTR で NAT された場合)
#
#   指定しないと「疎通はしているが、意図した経路ではない」状態を見逃します。
#   サイクル 3 で実際に、DS-Lite の AFTR NAT が効かず私設アドレスのまま出ていたのに
#   PASS=10 FAIL=0 になった実績があります。
set -u

V4_TARGET="203.0.113.80"
V6_TARGET="2001:db8:cafe::80"
DNS_NAME="www.lab.example"
BIG_MIN_BYTES="${BIG_MIN_BYTES:-5000000}"   # big.bin は 5MB。404 を掴んで PASS しないための下限
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

# ウォームアップ (判定には数えない)。
# 経路上 (クライアント → CPE → NGN → VNE → INET-SIM) の近隣探索が初回に間に合わず、
# **1 回目だけ IPv6 が FAIL する**ことが実測で確認されている (2 回目以降は必ず PASS)。
# 判定を緩めると本物の障害を見逃すので、閾値ではなくウォームアップで解消する。
ping -c1 -W3 "$V4_TARGET" >/dev/null 2>&1 || true
ping -c1 -W3 "$V6_TARGET" >/dev/null 2>&1 || true

echo "--- 疎通 ---"
check "IPv4 ping (${V4_TARGET})"      ping -c2 -W2 "$V4_TARGET"
check "IPv6 ping (${V6_TARGET})"      ping -c2 -W2 "$V6_TARGET"

echo "--- DNS ---"
# キャッシュを落としてから引く。ラボの dnsmasq は local-ttl=3600 なので、
# キャッシュが残っていると **切替で DNS 経路が壊れていても PASS してしまう**。
# 「切替前後のチェック」というこのスクリプトの用途でこそ発動する偽陽性なので必須。
# **限界**: これで消えるのは **このホストのキャッシュだけ**。CPE (OpenWrt) の dnsmasq にも
# キャッシュが残るため、切替直後の厳密な比較をするなら CPE 側でも
#   /etc/init.d/dnsmasq restart
# を実行してください (上流の local-ttl=3600 が効くので最長 1 時間残ります)
resolvectl flush-caches >/dev/null 2>&1 || true
check "A 解決 (${DNS_NAME})"          sh -c "getent ahostsv4 $DNS_NAME | grep -q ."
check "AAAA 解決 (${DNS_NAME})"       sh -c "getent ahostsv6 $DNS_NAME | grep -q ."

echo "--- HTTP 到達性 (応答に出口アドレスが表示される) ---"
# curl には必ず -f を付ける。付けないと 404/500 でも終了コード 0 になり、
# 「サーバは生きているがコンテンツが無い」状態を PASS と誤判定する。
BODY4="$(curl -4 -fs --connect-timeout 5 "http://${V4_TARGET}/" 2>/dev/null)"
BODY6="$(curl -6 -fs --connect-timeout 5 "http://[${V6_TARGET}]/" 2>/dev/null)"
printf '%s\n' "$BODY4" "$BODY6"
check "HTTP over IPv4"                test -n "$BODY4"
check "HTTP over IPv6"                test -n "$BODY6"

echo "--- 出口アドレス (意図した経路を通っているか) ---"
SRC4="$(printf '%s\n' "$BODY4" | awk '/^src:/{print $2; exit}')"
SRC6="$(printf '%s\n' "$BODY6" | awk '/^src:/{print $2; exit}')"
echo "INFO: 出口 IPv4 = ${SRC4:-(取得できず)} / 出口 IPv6 = ${SRC6:-(取得できず)}"
if [ -n "${EXPECT_SRC4:-}" ]; then
  check "出口 IPv4 が ${EXPECT_SRC4}"  test "$SRC4" = "$EXPECT_SRC4"
else
  echo "INFO: EXPECT_SRC4 未指定のため経路の検証は省略 (疎通だけでは MAP-E/DS-Lite の成立を示せません)"
fi
if [ -n "${EXPECT_SRC6:-}" ]; then
  check "出口 IPv6 が ${EXPECT_SRC6}"  test "$SRC6" = "$EXPECT_SRC6"
fi

echo "--- 大サイズ TCP 転送 (MSS/PMTUD 黒穴は小さいページだけ通る。ICMP の MTU 実測では見逃す) ---"
# 実転送バイト数を見る。-f だけだと 404 は弾けるが、
# 「200 だが中身が小さい」ケース (nginx の別コンテンツ等) を見逃すため。
big_ok() {  # big_ok <-4|-6> <URL>
  local n
  n="$(curl "$1" -fs -m 30 -o /dev/null -w '%{size_download}' "$2" 2>/dev/null)" || return 1
  [ -n "$n" ] && [ "$n" -ge "$BIG_MIN_BYTES" ] 2>/dev/null
}
check "TCP 5MB over IPv4"             big_ok -4 "http://${V4_TARGET}/big.bin"
check "TCP 5MB over IPv6"             big_ok -6 "http://[${V6_TARGET}]/big.bin"

echo "--- フラグメント (DF なし大 ICMP。相互接続試験で実装バグが出た領域) ---"
check "IPv4 fragment (2000B)"         ping -c2 -W2 -s 2000 "$V4_TARGET"
check "IPv6 fragment (2000B)"         ping -c2 -W2 -s 2000 "$V6_TARGET"

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
