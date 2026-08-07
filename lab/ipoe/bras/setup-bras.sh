#!/bin/bash
# BRAS (PPPoE 終端) 構築スクリプト (Ubuntu 24.04)
#   NIC: eth1=PG-ACCESS (PPPoE 待受), eth2=PG-INET
set -euo pipefail
LABDIR="$(cd "$(dirname "$0")" && pwd)"

INET_SELF="203.0.113.2/24"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y accel-ppp nftables tcpdump || {
  echo "accel-ppp がリポジトリにない場合: https://github.com/accel-ppp/accel-ppp を参照しビルド" >&2
  exit 1
}

cat > /etc/sysctl.d/90-bras.conf <<'EOF'
net.ipv4.ip_forward=1
EOF
sysctl --system >/dev/null

ip link set eth1 up
ip addr replace ${INET_SELF} dev eth2
ip link set eth2 up
ip route replace default via 203.0.113.80   # 模擬インターネット側は INET-SIM を上流とみなす

mkdir -p /var/log/accel-ppp
install -m 644 "${LABDIR}/accel-ppp.conf" /etc/accel-ppp.conf
install -m 600 "${LABDIR}/chap-secrets" /etc/ppp/chap-secrets

# PPPoE プールを INET へ NAT (実網の ISP NAT なし構成を再現するなら削ること)
nft -f - <<'EOF'
table ip bras-nat {
  chain postrouting {
    type nat hook postrouting priority srcnat;
    ip saddr 100.64.1.0/24 oifname "eth2" masquerade
  }
}
EOF

systemctl enable --now accel-ppp
systemctl restart accel-ppp
echo "[BRAS] PPPoE 待受開始 (eth1, AC=LAB-BRAS)。セッション確認: accel-cmd show sessions"
