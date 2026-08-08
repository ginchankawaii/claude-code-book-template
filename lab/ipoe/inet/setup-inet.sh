#!/bin/bash
# INET-SIM: 模擬インターネット (Web + DNS) 構築 (Ubuntu 24.04)
#   NIC: eth1=PG-INET
#   usage: setup-inet.sh            … 初期構築
#          setup-inet.sh break-v6   … IPv6 だけ死んだサイトを再現 (R6: DNSフォールバック)
#          setup-inet.sh restore    … 復旧
#          setup-inet.sh spoof-aftr … 市販ルータのDS-Lite自動設定向けに transix系AFTRの
#                                     FQDNをラボAFTRへ向ける (ラボ内DNSのみの偽装)
set -euo pipefail

# 役割別 MAC から NIC 名を自動解決 (provision.sh で作った VM 向け。未設定の変数だけ埋める)
if [ -f "$(dirname "$0")/../detect-ifs.sh" ]; then . "$(dirname "$0")/../detect-ifs.sh"; fi

MODE="${1:-install}"

case "$MODE" in
  spoof-aftr)
    cat > /etc/dnsmasq.d/lab-aftr-spoof.conf <<'EOF'
# 市販ルータのAFTR自動発見をラボAFTRへ誘導 (transix / クロスパス相当)
address=/gw.transix.jp/2001:db8:8888::1
address=/dgw.xpass.jp/2001:db8:8888::1
EOF
    systemctl restart dnsmasq
    echo "[INET-SIM] AFTR FQDN 偽装を有効化 (解除: rm /etc/dnsmasq.d/lab-aftr-spoof.conf && systemctl restart dnsmasq)"
    exit 0 ;;
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

INET_IF="${INET_IF:-eth1}"

# dnsmasq は systemd-resolved のスタブ (127.0.0.53:53) と衝突しインストール直後の起動に
# 失敗することがあるため、先に設定を置き resolved のスタブを止めてから導入する
mkdir -p /etc/systemd/resolved.conf.d
printf '[Resolve]\nDNSStubListener=no\n' > /etc/systemd/resolved.conf.d/lab.conf
systemctl restart systemd-resolved || true
mkdir -p /etc/dnsmasq.d
cat > /etc/dnsmasq.d/lab.conf <<EOF
no-resolv
interface=${INET_IF}
bind-interfaces
local-ttl=3600
address=/www.lab.example/203.0.113.80
address=/www.lab.example/2001:db8:cafe::80
address=/v4only.lab.example/203.0.113.80
EOF

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx dnsmasq nftables

ip addr replace 203.0.113.80/24 dev "${INET_IF}"
ip addr replace 203.0.113.53/24 dev "${INET_IF}"
ip -6 addr replace 2001:db8:cafe::80/64 dev "${INET_IF}"
ip -6 addr replace 2001:db8:cafe::53/64 dev "${INET_IF}"
ip link set "${INET_IF}" up
# 復路 (VNE と同居している場合は自アドレス宛 via となり失敗するが、その時は経路自体不要)
ip route replace 100.64.0.0/10 via 203.0.113.2 || true    # PPPoE プールの復路 → BRAS
ip route replace 198.51.100.0/24 via 203.0.113.1 || true  # MAP-E 共有 IPv4 の復路 → VNE
ip -6 route replace default via 2001:db8:cafe::1 || true  # v6 の戻りは VNE 経由

# 接続元アドレスを表示する確認ページ + MTU/MSS 検証用の大サイズファイル
mkdir -p /var/www/html
head -c 5M /dev/urandom > /var/www/html/big.bin
cat > /etc/nginx/sites-available/default <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    root /var/www/html;
    location = / {
        default_type text/plain;
        return 200 "lab-inet OK\nsrc: $remote_addr\nhost: $host\n";
    }
    location / {
        try_files $uri =404;
    }
}
EOF
systemctl enable --now nginx && systemctl restart nginx
systemctl enable --now dnsmasq && systemctl restart dnsmasq

echo "[INET-SIM] http://203.0.113.80 / http://[2001:db8:cafe::80] / DNS 203.0.113.53"
echo "  MTU/MSS 検証用: /big.bin (5MB)"
