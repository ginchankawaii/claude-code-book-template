#!/bin/bash
# BRAS (PPPoE 終端) 構築スクリプト (Ubuntu 24.04)
#   NIC: eth1=PG-ACCESS (PPPoE 待受), eth2=PG-INET
set -euo pipefail
LABDIR="$(cd "$(dirname "$0")" && pwd)"

# 役割別 MAC から NIC 名を自動解決 (provision.sh で作った VM 向け。未設定の変数だけ埋める)
if [ -f "${LABDIR}/../detect-ifs.sh" ]; then . "${LABDIR}/../detect-ifs.sh"; fi

ACCESS_IF="${ACCESS_IF:-eth1}"
INET_IF="${INET_IF:-eth2}"
INET_SELF="203.0.113.2/24"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nftables tcpdump

# accel-ppp は Debian/Ubuntu 公式リポジトリに無いためソースからビルドする
if ! command -v accel-pppd >/dev/null 2>&1; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential cmake git \
    libpcre2-dev libssl-dev linux-headers-generic
  git clone --depth 1 https://github.com/accel-ppp/accel-ppp.git /usr/local/src/accel-ppp
  cmake -S /usr/local/src/accel-ppp -B /usr/local/src/accel-ppp/build \
    -DCMAKE_INSTALL_PREFIX=/usr -DBUILD_IPOE_DRIVER=FALSE -DBUILD_VLAN_MON_DRIVER=FALSE \
    -DRADIUS=TRUE -DSHAPER=FALSE
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

ip link set "${ACCESS_IF}" up
ip addr replace ${INET_SELF} dev "${INET_IF}"
ip link set "${INET_IF}" up
# 注意: INET-SIM はパケット転送しない終端ホスト。この default はプールNAT後の
# 通信が同一セグメントの INET-SIM に届くための形式的なルート(先に網はない)
ip route replace default via 203.0.113.80

mkdir -p /var/log/accel-ppp
sed "s/^interface=eth1/interface=${ACCESS_IF}/" "${LABDIR}/accel-ppp.conf" > /etc/accel-ppp.conf
# -D で /etc/ppp ごと作る。accel-ppp をソースからビルドしていると ppp パッケージが
# 入らないため /etc/ppp が存在せず、-D 無しだと install が No such file or directory で落ちる
install -D -m 600 "${LABDIR}/chap-secrets" /etc/ppp/chap-secrets

# PPPoE プールを INET へ NAT (実網の ISP NAT なし構成を再現するなら削ること)
nft -f - <<EOF
table ip bras-nat {
  chain postrouting {
    type nat hook postrouting priority srcnat;
    ip saddr 100.64.1.0/24 oifname "${INET_IF}" masquerade
  }
}
EOF

systemctl enable --now accel-ppp
systemctl restart accel-ppp
echo "[BRAS] PPPoE 待受開始 (${ACCESS_IF}, AC=LAB-BRAS)。セッション確認: accel-cmd show sessions"
echo "  MSS clamp を BNG 側で行う ISP を模擬する場合 (検証変数。既定は clamp なし):"
echo "    nft 'add chain ip bras-nat fwd { type filter hook forward priority 0; }'"
echo "    nft add rule ip bras-nat fwd tcp flags syn tcp option maxseg size set rt mtu"
