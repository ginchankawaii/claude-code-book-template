#!/bin/bash
# VNE: MAP-E BR 模擬 (Ubuntu 24.04)
#   単一テスト CE 向けの静的 ip6tnl で BR を再現する。
#   CE 側が共有 IPv4 + 制限ポートで NAT する前提なので BR では NAT しない。
#   NIC: eth1=PG-CORE, eth2=PG-INET
#
# MAP ルール (CPE に設定する値):
#   rule-ipv6-prefix 2001:db8:1000::/40 / rule-ipv4-prefix 198.51.100.0/24
#   ea-len 16 / psid-offset 4  → PD 2001:db8:100a:500::/56 の CE は
#   IPv4=198.51.100.10, PSID=5 (240ポート)
set -euo pipefail

BR_ADDR="2001:db8:9999::1"
CE_MAP_ADDR="${CE_MAP_ADDR:-2001:db8:100a:500:0:c633:640a:5}"  # RFC7597 IID: 0000:IPv4:PSID
CE_SHARED_V4="198.51.100.10"
CORE_SELF="2001:db8:ff00::2/64"
CORE_NGN="2001:db8:ff00::1"
INET_SELF="203.0.113.1/24"
INET_SELF6="2001:db8:cafe::1/64"

cat > /etc/sysctl.d/90-vne.conf <<'EOF'
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
EOF
sysctl --system >/dev/null

ip -6 addr replace ${CORE_SELF} dev eth1
ip addr replace ${INET_SELF} dev eth2
ip -6 addr replace ${INET_SELF6} dev eth2
ip link set eth1 up; ip link set eth2 up

# BR アドレスと、ユーザプレフィックス帯の復路 (NGN 経由)
ip -6 addr replace ${BR_ADDR}/128 dev lo
ip -6 route replace 2001:db8:1000::/40 via ${CORE_NGN}

# MAP-E トンネル (BR⇔CE)。inner IPv4 MTU 1460
modprobe ip6_tunnel
ip -6 tunnel del map0 2>/dev/null || true
ip -6 tunnel add map0 mode ip6tnl local ${BR_ADDR} remote ${CE_MAP_ADDR} encaplimit none
ip link set map0 up mtu 1460
ip route replace ${CE_SHARED_V4}/32 dev map0   # 共有 IPv4 宛の復路をトンネルへ

echo "[VNE] MAP-E BR 起動: BR=${BR_ADDR}, CE=${CE_MAP_ADDR}, 共有IPv4=${CE_SHARED_V4}"
echo "      CE のアドレスが異なる場合: CE_MAP_ADDR=<addr> $0 で再実行"
