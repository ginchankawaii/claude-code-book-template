#!/bin/bash
# VNE: DS-Lite AFTR 模擬 (Ubuntu 24.04)
#   CE(B4) との ip6tnl + 網側 NAT (masquerade)。ポート開放不可はこの構成の仕様どおり。
#   NIC: eth1=PG-CORE, eth2=PG-INET
#   usage: CE_WAN6=<CEのWAN IPv6> setup-aftr.sh   (省略時は PD 方式の CE 想定値)
set -euo pipefail

AFTR_ADDR="2001:db8:8888::1"
CE_WAN6="${CE_WAN6:-2001:db8:100a:500::1}"   # B4 側トンネル終点 (CE の WAN/LAN 側 GUA)
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

# INET 側アドレスは map-br と共通 (ip addr replace なので単独実行・共存どちらも可)
ip -6 addr replace ${CORE_SELF} dev "${CORE_IF}"
ip addr replace ${INET_SELF} dev "${INET_IF}"
ip -6 addr replace ${INET_SELF6} dev "${INET_IF}"
ip link set "${CORE_IF}" up; ip link set "${INET_IF}" up

ip -6 addr replace ${AFTR_ADDR}/128 dev lo
ip -6 route replace 2001:db8:1000::/40 via ${CORE_NGN}

modprobe ip6_tunnel
ip -6 tunnel del dslite0 2>/dev/null || true
ip -6 tunnel add dslite0 mode ip6tnl local ${AFTR_ADDR} remote ${CE_WAN6} encaplimit none
ip link set dslite0 up mtu 1460
ip addr replace 192.0.0.1/29 dev dslite0      # RFC 6333: AFTR=192.0.0.1, B4=192.0.0.2
ip route replace 192.0.0.2/32 dev dslite0

# 網側 NAT: B4 からの RFC1918/共有アドレス空間を INET へ masquerade
nft -f - <<EOF
table ip aftr-nat {
  chain postrouting {
    type nat hook postrouting priority srcnat;
    oifname "${INET_IF}" masquerade
  }
}
EOF

echo "[VNE] DS-Lite AFTR 起動: AFTR=${AFTR_ADDR}, B4=${CE_WAN6}"
echo "      MTU ブラックホール再現 (R5): $0 とは別に以下を実行"
echo "        nft add table ip6 pmtu-break; nft 'add chain ip6 pmtu-break fwd { type filter hook forward priority 0; }'"
echo "        nft add rule ip6 pmtu-break fwd icmpv6 type packet-too-big drop"
