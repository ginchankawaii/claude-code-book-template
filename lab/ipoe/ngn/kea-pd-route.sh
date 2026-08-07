#!/bin/bash
# Kea libdhcp_run_script フック: IA_PD リース確定時に、委譲プレフィックスの復路を
# 「要求元 CE の送信元アドレス宛の via 経路」として自動投入する。
# (on-link 経路では CE が MAP/配下アドレス宛の NS に応答せず復路が死ぬため)
# setup-ngn.sh が __ACCESS_IF__ を実 NIC 名に置換して /usr/local/sbin へ配置する。
ACCESS_IF="__ACCESS_IF__"

case "${1:-}" in
  lease6_select|lease6_renew|lease6_rebind)
    if [ "${LEASE6_TYPE:-}" = "IA_PD" ] && [ -n "${QUERY6_REMOTE_ADDR:-}" ]; then
      ip -6 route replace "${LEASE6_ADDRESS}/${LEASE6_PREFIX_LEN}" \
        via "${QUERY6_REMOTE_ADDR}" dev "${ACCESS_IF}"
      logger -t kea-pd-route "route ${LEASE6_ADDRESS}/${LEASE6_PREFIX_LEN} via ${QUERY6_REMOTE_ADDR}"
    fi
    ;;
esac
exit 0
