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
# LAN 側に IPv6 を配らない構成 (実務の既定) では IPv6 を判定から外す。
#   SKIP_V6=1 ./run-checks.sh
# PPPoE→IPoE の切替動機は「PPPoE が遅い」であって IPv6 化ではないため、
# **お客様の LAN は IPv4 のままにするのが通常**です。LAN を IPv6 化すると
# アドレス再設計・FW 見直し・アプリ検証が発生するので、要件でない限りやりません。
# その構成では IPv6 が通らないのが**正しい状態**で、FAIL として数えると誤解を招きます。
SKIP_V6="${SKIP_V6:-0}"
PASS=0; FAIL=0

check() {  # check <名称> <コマンド...>
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "PASS: $name"; PASS=$((PASS+1))
  else
    echo "FAIL: $name"; FAIL=$((FAIL+1))
  fi
}

# LAN が IPv4 のみの構成では IPv6 項目を判定に数えない (INFO として残す)
check_v6() {
  if [ "$SKIP_V6" = "1" ]; then
    echo "SKIP: $1 (SKIP_V6=1 / LAN は IPv4 のみの構成)"
    return 0
  fi
  check "$@"
}

echo "=== IPoE 切替チェック $(date '+%F %T') ==="
echo "--- アドレス/経路 ---"
ip -6 addr show scope global | grep -E 'inet6|^[0-9]' || echo "(グローバル IPv6 なし)"
ip route show default; ip -6 route show default

# 経路の初回ウォームアップ (判定には数えない)。近隣探索の取りこぼし対策
ping -c1 -W3 "$V4_TARGET" >/dev/null 2>&1 || true
ping -c1 -W3 "$V6_TARGET" >/dev/null 2>&1 || true

# **IPv6 の送信元アドレスを先に確認する。**
# ここが「意図しないプレフィックス」だと、以降の IPv6 項目が全部タイムアウトするが、
# 症状は「なんとなく IPv6 だけ死ぬ」にしか見えず原因に辿り着けない。
#
# 実際に踏んだ例 (サイクル 5): CPE の GUA が deprecated (preferred_lft 0) になった瞬間、
# RFC 6724 の送信元選択が **OpenWrt 既定の ULA (fd00::/8)** にフォールバックし、
# ラボ内に ULA の復路が無いため IPv6 が全滅した。IPv4 は MAP-E トンネル経由で
# 送信元選択が絡まないため無傷 →「IPv4 は通るのに IPv6 だけ死ぬ」という紛らわしい形になる。
if [ "$SKIP_V6" != "1" ]; then
SRC6_SEL="$(ip -6 route get "$V6_TARGET" 2>/dev/null | sed -n 's/.* src \([0-9a-f:]*\).*/\1/p')"
case "${SRC6_SEL:-}" in
  fd*|fc*)
    echo "警告: IPv6 の送信元に ULA (${SRC6_SEL}) が選ばれています。" >&2
    echo "      GUA が deprecated になっている可能性があります (ip -6 addr show で preferred_lft を確認)。" >&2
    echo "      ラボ内に ULA の復路は無いので、以降の IPv6 項目は全て FAIL します。" >&2
    echo "      対処: CPE で ULA を無効化する (uci set network.globals.ula_prefix='')" >&2 ;;
  "") echo "警告: IPv6 の送信元アドレスを決定できません (グローバル IPv6 が無い可能性)" >&2 ;;
  *)  echo "INFO: IPv6 の送信元に ${SRC6_SEL} を使います" ;;
esac
fi

echo "--- 疎通 ---"
check "IPv4 ping (${V4_TARGET})"      ping -c2 -W2 "$V4_TARGET"
check_v6 "IPv6 ping (${V6_TARGET})"      ping -c2 -W2 "$V6_TARGET"

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
check_v6 "HTTP over IPv6"                test -n "$BODY6"

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
check_v6 "TCP 5MB over IPv6"             big_ok -6 "http://[${V6_TARGET}]/big.bin"

echo "--- フラグメント (DF なし大 ICMP。相互接続試験で実装バグが出た領域) ---"
check "IPv4 fragment (2000B)"         ping -c2 -W2 -s 2000 "$V4_TARGET"
check_v6 "IPv6 fragment (2000B)"         ping -c2 -W2 -s 2000 "$V6_TARGET"

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
