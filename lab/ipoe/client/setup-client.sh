#!/bin/bash
# 検証クライアント (CPE 配下) の LAN 側を設定する (Ubuntu 24.04)
#   NIC: 02:c1:* = CPE 配下の LAN (PG-CLIENT / vmbr4)
#
#   usage: setup-client.sh          … LAN 側を DHCP + RA 受信で構成し、既定経路を CPE 側に向ける
#          setup-client.sh revert   … 設定を削除して管理NIC側の既定経路に戻す
#          setup-client.sh show     … 現在のアドレス・経路・DNS を表示するだけ
#
# なぜ必要か:
#   cloud-init は管理NIC (eth0) しか設定しないため、LAN 側 NIC は DOWN のまま放置される。
#   さらに既定経路が管理NIC側 (家庭/社内 LAN) を向いたままだと、run-checks.sh の
#   通信が CPE を通らずに抜けてしまい、検証にならない。
#
# 注意:
#   既定経路を CPE 側に向けるため、このスクリプト実行後はクライアントから
#   本物のインターネットに出られなくなる (ラボとしては正しい状態)。
#   管理は IPv6 リンクローカル (ssh labadmin@fe80::...%vmbr0) で続けられる
#   — リンクローカルは既定経路を使わないため影響を受けない。
set -euo pipefail

MODE="${1:-setup}"
CLIENT_LAN_MAC="${CLIENT_LAN_MAC:-02:c1:00:00:00:04}"
NETPLAN_FILE="/etc/netplan/60-ipoe-lab-lan.yaml"
# 管理NIC (cloud-init 管理) より小さい metric にして、既定経路を CPE 側に寄せる
LAN_ROUTE_METRIC="${LAN_ROUTE_METRIC:-50}"

# 役割別 MAC から NIC 名を自動解決 (LAN_IF が埋まる)
if [ -f "$(dirname "$0")/../detect-ifs.sh" ]; then . "$(dirname "$0")/../detect-ifs.sh"; fi

show_state() {
  echo "--- アドレス ---"
  ip -br addr show | grep -v '^lo'
  echo "--- 既定経路 (metric が小さいほうが優先) ---"
  ip route show default || true
  ip -6 route show default || true
  echo "--- DNS ---"
  resolvectl status 2>/dev/null | grep -E 'Link |DNS Servers' || cat /etc/resolv.conf
}

case "$MODE" in
  show)
    show_state; exit 0 ;;
  revert)
    rm -f "$NETPLAN_FILE"
    netplan apply
    echo "[client] LAN 側の設定を削除しました (既定経路は管理NIC側に戻ります)"
    exit 0 ;;
esac

LAN_IF="${LAN_IF:-}"
if [ -z "$LAN_IF" ]; then
  echo "ERROR: LAN 側 NIC (MAC ${CLIENT_LAN_MAC%%:*}:${CLIENT_LAN_MAC#*:} 系) が見つかりません" >&2
  echo "       この VM に vmbr4 (CPE 配下) の NIC が付いているか確認してください:" >&2
  ip -br link >&2
  exit 1
fi
echo "[client] LAN 側 NIC: ${LAN_IF} (MAC ${CLIENT_LAN_MAC})"

# 既定経路を CPE 側に向けると外に出られなくなるので、必要なコマンドは **先に** 揃える
MISSING=""
for cmd in curl ping getent; do command -v "$cmd" >/dev/null 2>&1 || MISSING="${MISSING} $cmd"; done
if [ -n "$MISSING" ]; then
  echo "[client] 不足コマンドを先に導入します:${MISSING} (既定経路を切り替える前に実施)"
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y curl iputils-ping
fi

# MAC で一致させる。NIC 名は環境で変わる (実測: ens19) が MAC は provision.sh が固定している
cat > "$NETPLAN_FILE" <<EOF
# IPoE 検証ラボ: CPE 配下の LAN 側 (setup-client.sh が生成)
network:
  version: 2
  ethernets:
    ipoe-lab-lan:
      match:
        macaddress: "${CLIENT_LAN_MAC}"
      dhcp4: true
      dhcp4-overrides:
        route-metric: ${LAN_ROUTE_METRIC}
      dhcp6: false
      accept-ra: true
EOF
chmod 600 "$NETPLAN_FILE"   # netplan は他ユーザから読める設定ファイルを警告する

netplan generate
netplan apply

echo "[client] RA / DHCP の受信を待ちます (最大 30 秒)"
for _ in $(seq 30); do
  if ip -4 addr show dev "$LAN_IF" | grep -q 'inet '; then break; fi
  sleep 1
done

echo
show_state
echo
if ip route show default | grep -q "dev ${LAN_IF}"; then
  echo "[client] OK: 既定経路が CPE 側 (${LAN_IF}) を向いています"
else
  echo "[client] 注意: 既定経路が ${LAN_IF} を向いていません。" >&2
  echo "         CPE (OpenWrt) 側の DHCP が動いているか、metric を確認してください" >&2
  echo "         (LAN_ROUTE_METRIC=<より小さい値> で再実行できます)" >&2
fi
if ip -6 addr show dev "$LAN_IF" scope global | grep -q inet6; then
  echo "[client] OK: LAN 側にグローバル IPv6 が付いています (RA 受信できている)"
else
  echo "[client] 注意: グローバル IPv6 がありません。CPE 側の RA / PD を確認してください" >&2
fi
echo
echo "次: ./ipoe/tests/run-checks.sh | tee \$(date +%Y%m%d-%H%M)-checks.log"
