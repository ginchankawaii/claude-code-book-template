#!/bin/bash
# BRAS (PPPoE 終端) 構築スクリプト (Ubuntu 24.04)
#   NIC: eth1=PG-ACCESS (PPPoE 待受), eth2=PG-INET
set -euo pipefail
LABDIR="$(cd "$(dirname "$0")" && pwd)"

INET_SELF="203.0.113.2/24"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nftables tcpdump

# accel-ppp は Debian/Ubuntu 公式リポジトリに無いためソースからビルドする
if ! command -v accel-pppd >/dev/null 2>&1; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential cmake git \
    libpcre2-dev libssl-dev liblua5.1-0-dev linux-headers-generic
  git clone --depth 1 https://github.com/accel-ppp/accel-ppp.git /usr/local/src/accel-ppp
  cmake -S /usr/local/src/accel-ppp -B /usr/local/src/accel-ppp/build \
    -DCMAKE_INSTALL_PREFIX=/usr -DBUILD_IPOE_DRIVER=FALSE -DBUILD_VLAN_MON_DRIVER=FALSE \
    -DCPACK_TYPE=Ubuntu24 -DRADIUS=TRUE -DSHAPER=FALSE
  make -C /usr/local/src/accel-ppp/build -j"$(nproc)"
  make -C /usr/local/src/accel-ppp/build install
  cat > /etc/systemd/system/accel-ppp.service <<'EOF'
[Unit]
Description=accel-ppp (lab BRAS)
After=network.target

[Service]
Type=simple
ExecStart=/usr/sbin/accel-pppd -c /etc/accel-ppp.conf
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
fi

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
