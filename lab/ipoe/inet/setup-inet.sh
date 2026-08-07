#!/bin/bash
# INET-SIM: 模擬インターネット (Web + DNS) 構築 (Ubuntu 24.04)
#   NIC: eth1=PG-INET
#   usage: setup-inet.sh            … 初期構築
#          setup-inet.sh break-v6   … IPv6 だけ死んだサイトを再現 (R6: DNSフォールバック)
#          setup-inet.sh restore    … 復旧
set -euo pipefail
MODE="${1:-install}"

case "$MODE" in
  break-v6)
    nft -f - <<'EOF'
table ip6 break-v6 {
  chain input {
    type filter hook input priority 0;
    tcp dport { 80, 443 } drop
  }
}
EOF
    echo "[INET-SIM] IPv6 の HTTP(S) を遮断中 (AAAA は返答し続ける)"; exit 0 ;;
  restore)
    nft delete table ip6 break-v6 2>/dev/null || true
    echo "[INET-SIM] 復旧済み"; exit 0 ;;
esac

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx dnsmasq nftables

ip addr replace 203.0.113.80/24 dev eth1
ip addr replace 203.0.113.53/24 dev eth1
ip -6 addr replace 2001:db8:cafe::80/64 dev eth1
ip -6 addr replace 2001:db8:cafe::53/64 dev eth1
ip link set eth1 up
ip route replace 100.64.0.0/10 via 203.0.113.2      # PPPoE プールの復路 → BRAS
ip route replace 198.51.100.0/24 via 203.0.113.1    # MAP-E 共有 IPv4 の復路 → VNE
ip -6 route replace default via 2001:db8:cafe::1    # v6 の戻りは VNE 経由

# 接続元アドレスを表示する確認ページ (CPE がどの方式・アドレスで出てきたか一目で分かる)
cat > /etc/nginx/sites-available/default <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    location / {
        default_type text/plain;
        return 200 "lab-inet OK\nsrc: $remote_addr\nhost: $host\n";
    }
}
EOF
systemctl enable --now nginx && systemctl restart nginx

cat > /etc/dnsmasq.d/lab.conf <<'EOF'
no-resolv
interface=eth1
bind-interfaces
address=/www.lab.example/203.0.113.80
address=/www.lab.example/2001:db8:cafe::80
address=/v4only.lab.example/203.0.113.80
EOF
systemctl enable --now dnsmasq && systemctl restart dnsmasq

echo "[INET-SIM] http://203.0.113.80 / http://[2001:db8:cafe::80] / DNS 203.0.113.53"
