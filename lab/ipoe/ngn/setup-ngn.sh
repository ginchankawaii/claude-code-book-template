#!/bin/bash
# NGN-SIM 構築/モード切替スクリプト (Ubuntu 24.04)
#   usage: setup-ngn.sh ra   … ひかり電話なし相当 (RA 方式, /64)
#          setup-ngn.sh pd   … ひかり電話あり相当 (DHCPv6-PD 方式, /56)
#   NIC: eth1=PG-ACCESS, eth2=PG-CORE
set -euo pipefail

MODE="${1:?usage: $0 ra|pd}"
LABDIR="$(cd "$(dirname "$0")" && pwd)"

# NIC名は環境変数で上書き可 (Ubuntu 24.04のpredictable namingでは ens18/ens19 等になる)
ACCESS_IF="${ACCESS_IF:-eth1}"
CORE_IF="${CORE_IF:-eth2}"

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
ip -6 addr replace 2001:db8:1014:300::1/64 dev "${ACCESS_IF}"   # アクセス網側 (RA 方式の GW)
ip -6 addr replace ${CORE_SELF} dev "${CORE_IF}"
ip link set "${ACCESS_IF}" up; ip link set "${CORE_IF}" up

# 網内ルーティング: BR/AFTR と外向き v6 は VNE 経由
ip -6 route replace 2001:db8:9999::/64 via ${CORE_VNE}
ip -6 route replace 2001:db8:8888::/64 via ${CORE_VNE}
ip -6 route replace 2001:db8:cafe::/64 via ${CORE_VNE}
# PD 方式時、委譲プレフィックスの復路はアクセス網側リンクへ簡易的に on-link 扱い。
# 注意: CE が MAP アドレス宛の NS に WAN 側で応答しない実装だと復路が死ぬ。
# その場合は on-link をやめ、CE の WAN GUA を next-hop に指定する:
#   ip -6 route replace 2001:db8:100a:500::/56 via <CEのWAN GUA> dev ${ACCESS_IF}
ip -6 route replace 2001:db8:100a:500::/56 dev "${ACCESS_IF}"

case "$MODE" in
  ra)
    sed "s/^interface eth1/interface ${ACCESS_IF}/" "${LABDIR}/radvd.conf" > /etc/radvd.conf
    # 実網同様、RA 方式でもステートレス DHCPv6 (Information-Request への DNS 応答) は動かす
    # (RDNSS 非対応 CPE の「v6 は付くのに名前解決できない」を防ぐ/検証するため)
    sed "s/\"eth1\"/\"${ACCESS_IF}\"/" "${LABDIR}/kea-dhcp6-stateless.conf" > /etc/kea/kea-dhcp6.conf
    systemctl enable --now radvd kea-dhcp6-server
    systemctl restart radvd kea-dhcp6-server
    echo "[NGN-SIM] RA モード (ひかり電話なし相当, 2001:db8:1014:300::/64)"
    echo "  この /64 での MAP-E 期待値: 共有IPv4=198.51.100.20, PSID=3"
    ;;
  pd)
    # RA は経路広報 + M/O フラグのみ (プレフィックスは配らず PD で委譲)
    sed "/prefix 2001/,/};/d; s/AdvManagedFlag off/AdvManagedFlag on/; s/^interface eth1/interface ${ACCESS_IF}/" \
        "${LABDIR}/radvd.conf" > /etc/radvd.conf
    sed "s/\"eth1\"/\"${ACCESS_IF}\"/" "${LABDIR}/kea-dhcp6.conf" > /etc/kea/kea-dhcp6.conf
    # PD リース時に復路経路 (via CE) を自動投入するフックスクリプトを配置
    sed "s/__ACCESS_IF__/${ACCESS_IF}/" "${LABDIR}/kea-pd-route.sh" > /usr/local/sbin/kea-pd-route.sh
    chmod +x /usr/local/sbin/kea-pd-route.sh
    systemctl enable --now radvd kea-dhcp6-server
    systemctl restart radvd kea-dhcp6-server
    echo "[NGN-SIM] PD モード (ひかり電話あり相当, 2001:db8:100a:500::/56 を委譲)"
    echo "  この /56 での MAP-E 期待値: 共有IPv4=198.51.100.10, PSID=5"
    ;;
  *) echo "usage: $0 ra|pd" >&2; exit 1 ;;
esac
