#!/bin/bash
# Kea libdhcp_run_script フック: IA_PD リース確定時に、委譲プレフィックスの復路を
# 「要求元 CE の送信元アドレス宛の via 経路」として自動投入する。
# (on-link 経路では CE が MAP/配下アドレス宛の NS に応答せず復路が死ぬため)
#
# 重要: 初回割当は leases6_committed で通知される。lease6_select というフック
#       ポイントは run_script に存在しないため、そこに書くと初回は何も起きず
#       renew (既定 T1 ≒ 30分後) まで復路が入らない。
#       leases6_committed の環境変数は LEASES6_SIZE / LEASES6_AT<i>_TYPE /
#       LEASES6_AT<i>_ADDRESS / LEASES6_AT<i>_PREFIX_LEN。
#
# setup-ngn.sh が __ACCESS_IF__ を実 NIC 名に置換して /usr/local/sbin へ配置する。
# 動作確認:  journalctl -t kea-pd-route
ACCESS_IF="__ACCESS_IF__"

add_route() {  # $1=プレフィックス $2=プレフィックス長 $3=next-hop $4=ログ種別
  [ -n "$1" ] && [ -n "$2" ] && [ -n "$3" ] || return 0
  if ip -6 route replace "${1}/${2}" via "$3" dev "${ACCESS_IF}"; then
    logger -t kea-pd-route "$4 ${1}/${2} via $3 dev ${ACCESS_IF}"
  else
    logger -t kea-pd-route "FAILED $4 ${1}/${2} via $3 dev ${ACCESS_IF} (CAP_NET_ADMIN?)"
  fi
}

case "${1:-}" in
  leases6_committed)
    # 初回割当。1 パケットで複数リースが確定しうるので全件走査する
    _n="${LEASES6_SIZE:-0}"
    _i=0
    while [ "$_i" -lt "$_n" ]; do
      _t="LEASES6_AT${_i}_TYPE";       _t="${!_t:-}"
      _a="LEASES6_AT${_i}_ADDRESS";    _a="${!_a:-}"
      _p="LEASES6_AT${_i}_PREFIX_LEN"; _p="${!_p:-}"
      [ "$_t" = "IA_PD" ] && add_route "$_a" "$_p" "${QUERY6_REMOTE_ADDR:-}" committed
      _i=$((_i + 1))
    done
    ;;
  lease6_renew|lease6_rebind)
    [ "${LEASE6_TYPE:-}" = "IA_PD" ] && \
      add_route "${LEASE6_ADDRESS:-}" "${LEASE6_PREFIX_LEN:-}" "${QUERY6_REMOTE_ADDR:-}" "$1"
    ;;
esac
exit 0
