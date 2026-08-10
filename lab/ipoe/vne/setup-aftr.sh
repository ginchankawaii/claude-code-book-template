#!/bin/bash
# VNE: DS-Lite AFTR 模擬 (Ubuntu 24.04)
#   CE(B4) との ip6tnl + 網側 NAT (masquerade)。ポート開放不可はこの構成の仕様どおり。
#   NIC: eth1=PG-CORE, eth2=PG-INET
#   usage: CE_WAN6=<CEのWAN IPv6> setup-aftr.sh   (省略時は PD 方式の CE 想定値)
#          setup-aftr.sh break-pmtu    … R5: MTUブラックホール再現 (ICMPv4 frag-needed を落とす)
#          setup-aftr.sh restore-pmtu  … R5 復旧
set -euo pipefail

# 役割別 MAC から NIC 名を自動解決 (provision.sh で作った VM 向け。未設定の変数だけ埋める)
if [ -f "$(dirname "$0")/../detect-ifs.sh" ]; then . "$(dirname "$0")/../detect-ifs.sh"; fi

case "${1:-}" in
  break-pmtu)
    # このラボの外側パケットは 1460+40=1500 で全リンクに収まるため、落とすべきは
    # VNE 自身がトンネル MTU 超過の inner IPv4(DF) に対して生成する Frag-Needed (output方向)
    # add table / add chain は既存でも成功するので `|| true` は不要 (本物の失敗を隠さない)。
    # rule は追記されるので、毎回 flush してから入れる (2 回叩くと drop が 2 本になる)
    nft add table ip pmtu-break
    nft 'add chain ip pmtu-break out { type filter hook output priority 0; }'
    nft flush chain ip pmtu-break out
    nft add rule ip pmtu-break out icmp type destination-unreachable icmp code frag-needed drop
    echo "[VNE] ICMPv4 Fragmentation-Needed を遮断中 (大きい転送だけ固まる状態)"; exit 0 ;;
  restore-pmtu)
    nft delete table ip pmtu-break 2>/dev/null || true
    echo "[VNE] PMTU 復旧済み"; exit 0 ;;
  stop)
    # 方式を切り替えるときに使う。**残すと切り分けを汚す**:
    # dslite0 は旧 CE の WAN6 宛のまま残り、私設アドレス宛の v4 が
    # 「今は別の機器かもしれないアドレス」へカプセル化され続ける。
    # 192.168.0.0/16 の復路経路が管理網と重なる点も危うい。
    ip -6 tunnel del dslite0 2>/dev/null || true
    nft delete table ip aftr-nat 2>/dev/null || true
    echo "[VNE] DS-Lite AFTR を停止しました (トンネル・経路・NAT を削除)"; exit 0 ;;
esac

# nft は必須。VNE と INET-SIM を分離した構成では setup-inet.sh が入れてくれないため、
# ここでも確認する (同居構成では既に入っている)
command -v nft >/dev/null 2>&1 || \
  DEBIAN_FRONTEND=noninteractive apt-get install -y nftables

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
# IPv4-in-IPv6 なので mode は ipip6
ip -6 tunnel add dslite0 mode ipip6 local ${AFTR_ADDR} remote ${CE_WAN6} encaplimit none
ip link set dslite0 up mtu 1460
ip addr replace 192.0.0.1/29 dev dslite0      # RFC 6333: AFTR=192.0.0.1, B4=192.0.0.2
ip route replace 192.0.0.2/32 dev dslite0
# DS-Lite の B4 は NAT しない (inner IPv4 の src は CE 配下の私設アドレスのまま届く) ため、
# conntrack 逆変換後の復路をトンネルへ向ける経路が必須
ip route replace 10.0.0.0/8     dev dslite0
ip route replace 172.16.0.0/12  dev dslite0
ip route replace 192.168.0.0/16 dev dslite0

# 網側 NAT: DS-Lite 経由の私設アドレスのみ masquerade する。
# 全量 masquerade にすると MAP-E 併用時に共有 IPv4 (198.51.100.x) まで NAT され、
# 出口アドレス確認・ポート制限検証が無意味になるので送信元を限定する
#
# **必ず消してから入れる。** nft -f の table{chain{rule}} 形式は既存チェインに
# ルールを **追記** するため、CE 入れ替え (build-log §4) のたびに同じルールが増える。
# 重複自体は無害だが、後で条件を変えて再実行したときに **旧ルールが先にマッチして
# 修正が効かない**。「直したのに動かない」の典型的な原因になる。
nft delete table ip aftr-nat 2>/dev/null || true
nft -f - <<EOF
table ip aftr-nat {
  chain postrouting {
    type nat hook postrouting priority srcnat;
    ip saddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 192.0.0.0/29 } oifname "${INET_IF}" masquerade
  }
}
EOF

echo "[VNE] DS-Lite AFTR 起動: AFTR=${AFTR_ADDR}, B4=${CE_WAN6}"
echo "      MTU ブラックホール再現 (R5): $0 break-pmtu / 復旧: $0 restore-pmtu"
echo "      MAP-E だけを検証するときは: $0 stop  (トンネル・経路・NAT を消す)"
