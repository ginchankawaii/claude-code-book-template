#!/bin/bash
# VNE: MAP-E BR 模擬 (Ubuntu 24.04)
#   単一テスト CE 向けの静的 ip6tnl で BR を再現する。
#   CE 側が共有 IPv4 + 制限ポートで NAT する前提なので BR では NAT しない。
#   NIC: eth1=PG-CORE, eth2=PG-INET
#
# MAP ルール (CPE に設定する値):
#   rule-ipv6-prefix 2001:db8:1000::/40 / rule-ipv4-prefix 198.51.100.0/24
#   ea-len 16 / psid-offset 4
# モード別の既定値 (NGN-SIM の配布プレフィックスと整合):
#   PD 方式 (/56 = 2001:db8:100a:500::/56): IPv4=198.51.100.10, PSID=5 → そのまま実行
#   RA 方式 (/64 = 2001:db8:1014:300::/64): IPv4=198.51.100.20, PSID=3 →
#     CE_MAP_ADDR=2001:db8:1014:300:0:c633:6414:3 CE_SHARED_V4=198.51.100.20 $0
set -euo pipefail

# 役割別 MAC から NIC 名を自動解決 (provision.sh で作った VM 向け。未設定の変数だけ埋める)
if [ -f "$(dirname "$0")/../detect-ifs.sh" ]; then . "$(dirname "$0")/../detect-ifs.sh"; fi

case "${1:-}" in
  stop)
    # DS-Lite だけを検証するときに使う。残すと map0 が旧 CE の MAP アドレス宛のまま
    # 生き続け、共有 IPv4 宛の復路がそちらへ流れて切り分けを汚す
    ip -6 tunnel del map0 2>/dev/null || true
    echo "[VNE] MAP-E BR を停止しました (トンネル・共有IPv4の復路を削除)"; exit 0 ;;
esac

BR_ADDR="2001:db8:9999::1"
CE_MAP_ADDR="${CE_MAP_ADDR:-2001:db8:100a:500:0:c633:640a:5}"  # RFC7597 IID: 0000:IPv4:PSID
CE_SHARED_V4="${CE_SHARED_V4:-198.51.100.10}"
CORE_IF="${CORE_IF:-eth1}"
INET_IF="${INET_IF:-eth2}"
CORE_SELF="2001:db8:ff00::2/64"
CORE_NGN="2001:db8:ff00::1"
INET_SELF="203.0.113.1/24"
INET_SELF6="2001:db8:cafe::1/64"

cat > /etc/sysctl.d/90-vne.conf <<'EOF'
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
EOF
sysctl --system >/dev/null

ip -6 addr replace ${CORE_SELF} dev "${CORE_IF}"
ip addr replace ${INET_SELF} dev "${INET_IF}"
ip -6 addr replace ${INET_SELF6} dev "${INET_IF}"
ip link set "${CORE_IF}" up; ip link set "${INET_IF}" up

# BR アドレスと、ユーザプレフィックス帯の復路 (NGN 経由)
ip -6 addr replace ${BR_ADDR}/128 dev lo
ip -6 route replace 2001:db8:1000::/40 via ${CORE_NGN}

# MAP-E トンネル (BR⇔CE)。IPv4-in-IPv6 なので mode は ipip6。inner IPv4 MTU 1460
modprobe ip6_tunnel
ip -6 tunnel del map0 2>/dev/null || true
ip -6 tunnel add map0 mode ipip6 local ${BR_ADDR} remote ${CE_MAP_ADDR} encaplimit none
ip link set map0 up mtu 1460
ip route replace ${CE_SHARED_V4}/32 dev map0   # 共有 IPv4 宛の復路をトンネルへ

echo "[VNE] MAP-E BR 起動: BR=${BR_ADDR}, CE=${CE_MAP_ADDR}, 共有IPv4=${CE_SHARED_V4}"
echo "      CE のアドレスが異なる場合: CE_MAP_ADDR=<addr> $0 で再実行"
