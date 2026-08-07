#!/bin/bash
# VNE: DS-Lite AFTR 模擬 (Ubuntu 24.04)
#   CE(B4) との ip6tnl + 網側 NAT (masquerade)。ポート開放不可はこの構成の仕様どおり。
#   NIC: eth1=PG-CORE, eth2=PG-INET
#   usage: CE_WAN6=<CEのWAN IPv6> setup-aftr.sh   (省略時は PD 方式の CE 想定値)
set -euo pipefail

AFTR_ADDR="2001:db8:8888::1"
CE_WAN6="${CE_WAN6:-2001:db8:100a:500::1}"   # B4 側トンネル終点 (CE の WAN/LAN 側 GUA)
CORE_SELF="2001:db8:ff00::2/64"
CORE_NGN="2001:db8:ff00::1"

cat > /etc/sysctl.d/90-vne.conf <<'EOF'
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
EOF
sysctl --system >/dev/null

ip -6 addr replace ${CORE_SELF} dev eth1
ip link set eth1 up; ip link set eth2 up

ip -6 addr replace ${AFTR_ADDR}/128 dev lo
ip -6 route replace 2001:db8:1000::/40 via ${CORE_NGN}

modprobe ip6_tunnel
ip -6 tunnel del dslite0 2>/dev/null || true
ip -6 tunnel add dslite0 mode ip6tnl local ${AFTR_ADDR} remote ${CE_WAN6} encaplimit none
ip link set dslite0 up mtu 1460
ip addr replace 192.0.0.1/29 dev dslite0      # RFC 6333: AFTR=192.0.0.1, B4=192.0.0.2
ip route replace 192.0.0.2/32 dev dslite0

# 網側 NAT: B4 からの RFC1918/共有アドレス空間を INET へ masquerade
nft -f - <<'EOF'
table ip aftr-nat {
  chain postrouting {
    type nat hook postrouting priority srcnat;
    oifname "eth2" masquerade
  }
}
EOF

echo "[VNE] DS-Lite AFTR 起動: AFTR=${AFTR_ADDR}, B4=${CE_WAN6}"
echo "      MTU ブラックホール再現 (R5): $0 とは別に以下を実行"
echo "        nft add table ip6 pmtu-break; nft 'add chain ip6 pmtu-break fwd { type filter hook forward priority 0; }'"
echo "        nft add rule ip6 pmtu-break fwd icmpv6 type packet-too-big drop"
