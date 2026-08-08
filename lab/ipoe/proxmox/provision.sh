#!/bin/bash
# Proxmox VE ホスト上で実行する IPoE 検証ラボの自動構築スクリプト (PVE 8.x 想定)
#
#   usage: ./provision.sh            … ブリッジ作成 + VM 作成 + 起動 (既定)
#          ./provision.sh bridges    … ブリッジ (vmbr1-4) だけ作成
#          ./provision.sh destroy    … このスクリプトが作った VM を削除 (ブリッジは残す)
#
#   主な環境変数:
#     STORAGE=local-lvm         VM ディスクの格納先 (pvesm status で確認)
#     MGMT_BRIDGE=vmbr0         既存の管理用ブリッジ
#     ACCESS_UPLINK=enp3s0      実機CPE収容用の物理NIC (省略時はブリッジ内部のみ)
#     SSHKEY=~/.ssh/id_rsa.pub  VM に登録する公開鍵
#     CIUSER=labadmin           VM のログインユーザ名
#     WITH_CLIENT=1             CPE配下の検証クライアントVMも作る (既定: 作る)
#     WITH_OPENWRT=1            OpenWrt CE の VM も作る (既定: 作る)
#
# 役割別 MAC の規則 (VM 内の detect-ifs.sh がこれを見て NIC 名を自動解決する):
#     02:AC:* = アクセス網 / 02:C0:* = NGN網内 / 02:1E:* = 模擬インターネット
set -euo pipefail

MODE="${1:-all}"

STORAGE="${STORAGE:-local-lvm}"
MGMT_BRIDGE="${MGMT_BRIDGE:-vmbr0}"
ACCESS_UPLINK="${ACCESS_UPLINK:-none}"
SSHKEY="${SSHKEY:-$HOME/.ssh/id_rsa.pub}"
CIUSER="${CIUSER:-labadmin}"
WITH_CLIENT="${WITH_CLIENT:-1}"
WITH_OPENWRT="${WITH_OPENWRT:-1}"

IMG_DIR="/var/lib/vz/template/iso"
UBUNTU_IMG="${IMG_DIR}/ubuntu-24.04-server-cloudimg-amd64.img"
UBUNTU_URL="https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img"
OPENWRT_VER="${OPENWRT_VER:-24.10.0}"
OPENWRT_IMG="${IMG_DIR}/openwrt-${OPENWRT_VER}-x86-64-generic-ext4-combined.img"
OPENWRT_URL="https://downloads.openwrt.org/releases/${OPENWRT_VER}/targets/x86/64/openwrt-${OPENWRT_VER}-x86-64-generic-ext4-combined.img.gz"

VMIDS=(9001 9002 9003 9004 9010)
NEED_RELOAD=0

command -v qm >/dev/null || { echo "ERROR: qm が見つかりません。Proxmox VE ホスト上で実行してください" >&2; exit 1; }

# ---------------------------------------------------------------- destroy
if [ "$MODE" = "destroy" ]; then
  for vmid in "${VMIDS[@]}"; do
    if qm status "$vmid" >/dev/null 2>&1; then
      qm stop "$vmid" >/dev/null 2>&1 || true
      qm destroy "$vmid" --purge
      echo "  VM ${vmid}: 削除"
    fi
  done
  echo "[完了] VM を削除しました (ブリッジ vmbr1-4 は残しています)"
  exit 0
fi

# ---------------------------------------------------------------- bridges
ensure_bridge() {  # $1=ブリッジ名 $2=用途コメント $3=uplink(省略可)
  local br="$1" note="$2" up="${3:-none}"
  if grep -qE "^iface[[:space:]]+${br}[[:space:]]" /etc/network/interfaces 2>/dev/null; then
    echo "  ${br}: 既存のためスキップ"
    return
  fi
  cat >> /etc/network/interfaces <<EOF

auto ${br}
iface ${br} inet manual
	bridge-ports ${up}
	bridge-stp off
	bridge-fd 0
	bridge-mcsnoop 0
# ${note}
EOF
  echo "  ${br}: 追加 (${note}, uplink=${up})"
  NEED_RELOAD=1
}

echo "[1/4] ブリッジを準備します"
# bridge-mcsnoop 0 は必須: multicast snooping が有効だと RA/NA/DHCPv6 が VM に届かず IPv6 が死ぬ
ensure_bridge vmbr1 "IPoEラボ: アクセス網 (PG-ACCESS相当)" "${ACCESS_UPLINK}"
ensure_bridge vmbr2 "IPoEラボ: NGN網内 (PG-CORE相当)"
ensure_bridge vmbr3 "IPoEラボ: 模擬インターネット (PG-INET相当)"
ensure_bridge vmbr4 "IPoEラボ: CPE配下のクライアント側LAN"

if [ "$NEED_RELOAD" = "1" ]; then
  if command -v ifreload >/dev/null 2>&1; then
    ifreload -a
    echo "  ネットワーク設定を反映しました"
  else
    echo "  注意: ifreload がありません。手動で 'systemctl restart networking' か再起動してください"
  fi
fi

[ "$MODE" = "bridges" ] && { echo "[完了] ブリッジのみ作成しました"; exit 0; }

# ---------------------------------------------------------------- images
[ -f "$SSHKEY" ] || { echo "ERROR: 公開鍵が見つかりません: ${SSHKEY} (SSHKEY=... で指定)" >&2; exit 1; }

echo "[2/4] イメージを準備します"
if [ ! -f "$UBUNTU_IMG" ]; then
  echo "  Ubuntu 24.04 クラウドイメージを取得中..."
  wget -q --show-progress -O "$UBUNTU_IMG" "$UBUNTU_URL"
else
  echo "  Ubuntu イメージ: 既存を使用"
fi

if [ "$WITH_OPENWRT" = "1" ] && [ ! -f "$OPENWRT_IMG" ]; then
  echo "  OpenWrt ${OPENWRT_VER} イメージを取得中..."
  wget -q --show-progress -O "${OPENWRT_IMG}.gz" "$OPENWRT_URL"
  gunzip -f "${OPENWRT_IMG}.gz"
  qemu-img resize -f raw "$OPENWRT_IMG" 2G   # 元イメージは ~100MB なので先に拡張
fi

# ---------------------------------------------------------------- VMs
create_ubuntu_vm() {  # $1=vmid $2=name $3=memory $4=cores $5=net1指定 $6=net2指定(省略可)
  local vmid="$1" name="$2" mem="$3" cores="$4" net1="$5" net2="${6:-}"
  if qm status "$vmid" >/dev/null 2>&1; then
    echo "  VM ${vmid} (${name}): 既存のためスキップ"
    return
  fi
  local args=(--net0 "virtio,bridge=${MGMT_BRIDGE}" --net1 "$net1")
  [ -n "$net2" ] && args+=(--net2 "$net2")

  qm create "$vmid" --name "$name" --memory "$mem" --cores "$cores" --ostype l26 \
    --scsihw virtio-scsi-single --serial0 socket --agent 1 "${args[@]}"
  qm set "$vmid" --scsi0 "${STORAGE}:0,import-from=${UBUNTU_IMG}" >/dev/null
  qm set "$vmid" --ide2 "${STORAGE}:cloudinit" --boot order=scsi0 >/dev/null
  qm set "$vmid" --ciuser "$CIUSER" --sshkeys "$SSHKEY" --ipconfig0 ip=dhcp >/dev/null
  qm resize "$vmid" scsi0 +6G >/dev/null
  echo "  VM ${vmid} (${name}): 作成"
}

echo "[3/4] VM を作成します"
create_ubuntu_vm 9001 ngn-sim  2048 2 \
  "virtio=02:AC:00:00:00:01,bridge=vmbr1" "virtio=02:C0:00:00:00:01,bridge=vmbr2"
create_ubuntu_vm 9002 vne-inet 2048 2 \
  "virtio=02:C0:00:00:00:02,bridge=vmbr2" "virtio=02:1E:00:00:00:02,bridge=vmbr3"
create_ubuntu_vm 9003 bras     2048 2 \
  "virtio=02:AC:00:00:00:03,bridge=vmbr1" "virtio=02:1E:00:00:00:03,bridge=vmbr3"

if [ "$WITH_CLIENT" = "1" ]; then
  create_ubuntu_vm 9004 lab-client 1024 1 "virtio=02:C1:00:00:00:04,bridge=vmbr4"
fi

if [ "$WITH_OPENWRT" = "1" ] && ! qm status 9010 >/dev/null 2>&1; then
  # OpenWrt x86 の既定は eth0=LAN / eth1=WAN なので net0 を LAN 側にする
  qm create 9010 --name openwrt-ce --memory 512 --cores 1 --ostype l26 \
    --scsihw virtio-scsi-single --serial0 socket \
    --net0 "virtio,bridge=vmbr4" \
    --net1 "virtio=02:AC:00:00:00:10,bridge=vmbr1"
  qm set 9010 --scsi0 "${STORAGE}:0,import-from=${OPENWRT_IMG}" >/dev/null
  qm set 9010 --boot order=scsi0 >/dev/null
  echo "  VM 9010 (openwrt-ce): 作成 (net0=LAN/vmbr4, net1=WAN/vmbr1)"
elif [ "$WITH_OPENWRT" = "1" ]; then
  echo "  VM 9010 (openwrt-ce): 既存のためスキップ"
fi

echo "[4/4] VM を起動します"
for vmid in "${VMIDS[@]}"; do
  if qm status "$vmid" 2>/dev/null | grep -q stopped; then
    qm start "$vmid"
    echo "  VM ${vmid}: 起動"
  fi
done

cat <<EOF

========================================================================
[完了] 検証ラボの土台ができました

  9001 ngn-sim    NGN網模擬     (ACCESS + CORE)
  9002 vne-inet   VNE+模擬INET  (CORE + INET)
  9003 bras       PPPoE終端     (ACCESS + INET)
  9004 lab-client 検証クライアント (CPE配下)
  9010 openwrt-ce リファレンスCPE (LAN=vmbr4 / WAN=vmbr1)

次の手順:
  1. 各VMのIPを確認    qm guest cmd <vmid> network-get-interfaces
                       (または qm terminal <vmid> でコンソール)
  2. lab/ipoe をコピー  scp -r lab/ipoe ${CIUSER}@<VMのIP>:~/
  3. セットアップ実行   sudo ./ipoe/ngn/setup-ngn.sh pd        (ngn-sim)
                       sudo ./ipoe/vne/setup-map-br.sh        (vne-inet)
                       sudo ./ipoe/vne/setup-aftr.sh          (vne-inet)
                       sudo ./ipoe/inet/setup-inet.sh         (vne-inet)
                       sudo ./ipoe/bras/setup-bras.sh         (bras)
     ※ NIC名は detect-ifs.sh が MAC から自動判別するので指定不要
  4. 全VMのスナップショットを取得 (メモリ込み)

実機CPE(892FJ等)を繋ぐ場合: ACCESS_UPLINK=<物理NIC名> で再実行すると
vmbr1 に物理NICがアップリンクされ、実機が同じL2に乗ります。

やり直したいとき: $0 destroy → もう一度 $0
========================================================================
EOF
