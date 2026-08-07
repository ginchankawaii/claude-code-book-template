#!/bin/bash
# NGN-SIM 構築/モード切替スクリプト (Ubuntu 24.04)
#   usage: setup-ngn.sh ra   … ひかり電話なし相当 (RA 方式, /64)
#          setup-ngn.sh pd   … ひかり電話あり相当 (DHCPv6-PD 方式, /56)
#   NIC: eth1=PG-ACCESS, eth2=PG-CORE
set -euo pipefail

MODE="${1:?usage: $0 ra|pd}"
LABDIR="$(cd "$(dirname "$0")" && pwd)"

CORE_SELF="2001:db8:ff00::1/64"
CORE_VNE="2001:db8:ff00::2"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y radvd kea-dhcp6-server tcpdump

# フォワーディング有効化 (v6 forwarding 有効時も RA を受けない設定は不要: 自身が広報側)
cat > /etc/sysctl.d/90-ngn.conf <<'EOF'
net.ipv6.conf.all.forwarding=1
EOF
sysctl --system >/dev/null

# アドレス付与
ip -6 addr replace 2001:db8:1000:1::1/64 dev eth1   # アクセス網側 (RA 方式の GW)
ip -6 addr replace ${CORE_SELF} dev eth2
ip link set eth1 up; ip link set eth2 up

# 網内ルーティング: BR/AFTR と外向き v6 は VNE 経由
ip -6 route replace 2001:db8:9999::/64 via ${CORE_VNE}
ip -6 route replace 2001:db8:8888::/64 via ${CORE_VNE}
ip -6 route replace 2001:db8:cafe::/64 via ${CORE_VNE}
# PD 方式時、委譲プレフィックスの復路はアクセス網側リンクへ (CE の LL 宛は NDP で解決
# できないため、簡易的に on-link 扱いにする。CE 実機の WAN GUA 宛 via 指定でも可)
ip -6 route replace 2001:db8:100a:500::/56 dev eth1

case "$MODE" in
  ra)
    install -m 644 "${LABDIR}/radvd.conf" /etc/radvd.conf
    systemctl disable --now kea-dhcp6-server 2>/dev/null || true
    systemctl enable --now radvd
    systemctl restart radvd
    echo "[NGN-SIM] RA モード (ひかり電話なし相当, 2001:db8:1000:1::/64)"
    ;;
  pd)
    # RA は経路広報 + M/O フラグのみ (プレフィックスは配らず PD で委譲)
    sed '/prefix 2001/,/};/d; s/AdvManagedFlag off/AdvManagedFlag on/' \
        "${LABDIR}/radvd.conf" > /etc/radvd.conf
    install -m 644 "${LABDIR}/kea-dhcp6.conf" /etc/kea/kea-dhcp6.conf
    systemctl enable --now radvd kea-dhcp6-server
    systemctl restart radvd kea-dhcp6-server
    echo "[NGN-SIM] PD モード (ひかり電話あり相当, 2001:db8:100a:500::/56 を委譲)"
    ;;
  *) echo "usage: $0 ra|pd" >&2; exit 1 ;;
esac
