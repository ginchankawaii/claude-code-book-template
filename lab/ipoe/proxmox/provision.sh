#!/bin/bash
# Proxmox VE ホスト上で実行する IPoE 検証ラボの自動構築スクリプト
#
#   usage: ./provision.sh            … 事前検証 + ブリッジ作成 + VM 作成 + 起動 (既定)
#          ./provision.sh preflight  … 事前検証だけ実行して環境を報告 (何も変更しない)
#          ./provision.sh bridges    … 事前検証 + ブリッジ (vmbr1-4) だけ作成
#          ./provision.sh destroy    … このスクリプトが作った VM だけを削除
#          ./provision.sh ips        … 各 VM の接続先 (IPv6 リンクローカル) を表示
#
#   主な環境変数:
#     STORAGE=<名前>            VM ディスクの格納先。省略時は自動検出を試みる
#     MGMT_BRIDGE=vmbr0         既存の管理用ブリッジ
#     ACCESS_UPLINK=enp3s0      実機CPE収容用の物理NIC (省略時はブリッジ内部のみ)
#     SSHKEY=/root/.ssh/id_rsa.pub  VM に登録する公開鍵 (sudo 実行なので既定は root の鍵)
#     CIUSER=labadmin           VM のログインユーザ名
#     WITH_CLIENT=1 / WITH_OPENWRT=1   検証クライアント / OpenWrt CE も作る (既定: 作る)
#     SPLIT_INET=1                     INET-SIM を 9005 に分離する (既定: 0 = 9002 に同居)
#                                      DS-Lite の網側 NAT / ポート開放不可 (R4) を検証するなら必須
#     OPENWRT_MGMT=1            OpenWrt に管理NIC (net2) を足す。既定 0。
#                               map / ds-lite パッケージは既定イメージに入っておらず、
#                               ラボ内にインターネットが無いため opkg できない。
#                               1 にすると管理ブリッジ経由で opkg install できる
#     ALLOW_NO_SNAPSHOT=1       スナップショット不可ストレージでも確認なしで続行
#
# 安全設計 (レビュー指摘反映):
#   - VMID 9001-9010 が別用途で使われていたら中断する (destroy が他人の VM を消さない)
#   - 既存の vmbr1-4 が別用途なら中断する (CML 等の L2 に RA/DHCPv6 を漏らさない)
#   - ストレージの存在と種別を検証し、スナップショット不可なら警告する
#   - PVE 7.2 未満では importdisk 方式にフォールバックする
#
# 役割別 MAC の規則 (VM 内の detect-ifs.sh がこれを見て NIC 名を自動解決する):
#   02:AC:* = アクセス網 / 02:C0:* = NGN網内 / 02:1E:* = 模擬インターネット
set -euo pipefail

MODE="${1:-all}"

STORAGE="${STORAGE:-}"
MGMT_BRIDGE="${MGMT_BRIDGE:-vmbr0}"
ACCESS_UPLINK="${ACCESS_UPLINK:-none}"
SSHKEY="${SSHKEY:-/root/.ssh/id_rsa.pub}"
CIUSER="${CIUSER:-labadmin}"
WITH_CLIENT="${WITH_CLIENT:-1}"
WITH_OPENWRT="${WITH_OPENWRT:-1}"
SPLIT_INET="${SPLIT_INET:-0}"   # 1 で INET-SIM を 9005 として分離 (R4 の検証に必要)
OPENWRT_MGMT="${OPENWRT_MGMT:-0}"   # 1 にすると OpenWrt に管理NICを足す (opkg 用)
ALLOW_NO_SNAPSHOT="${ALLOW_NO_SNAPSHOT:-0}"

IMG_DIR="/var/lib/vz/template/iso"
UBUNTU_IMG="${IMG_DIR}/ubuntu-24.04-server-cloudimg-amd64.img"
UBUNTU_URL="https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img"
OPENWRT_VER="${OPENWRT_VER:-24.10.0}"
OPENWRT_IMG="${IMG_DIR}/openwrt-${OPENWRT_VER}-x86-64-generic-ext4-combined.img"
OPENWRT_URL="https://downloads.openwrt.org/releases/${OPENWRT_VER}/targets/x86/64/openwrt-${OPENWRT_VER}-x86-64-generic-ext4-combined.img.gz"

BRIDGE_TAG="IPoEラボ"          # 自分が作ったブリッジの目印 (コメント行に埋め込む)
LAB_TAG="ipoe-lab"             # 自分が作った VM の目印 (Proxmox のタグ)
VMIDS=(9001 9002 9003 9004 9005 9010)
# VMID -> このスクリプトが付ける VM 名 (所有者判定に使う)
lab_name_of() {
  case "$1" in
    9001) echo ngn-sim ;;  9002) echo vne-inet ;;  9003) echo bras ;;
    9004) echo lab-client ;; 9005) echo inet-sim ;; 9010) echo openwrt-ce ;; *) echo "" ;;
  esac
}

command -v qm >/dev/null || { echo "ERROR: qm が見つかりません。Proxmox VE ホスト上で実行してください" >&2; exit 1; }

# ============================================================ 所有者判定
vm_name()  { qm config "$1" 2>/dev/null | awk -F': ' '/^name:/{print $2; exit}'; }
vm_tagged(){ qm config "$1" 2>/dev/null | grep -qE "^tags:.*${LAB_TAG}"; }
# このスクリプトの作成物か: 名前が一致 かつ タグがある
vm_is_ours() {
  local vmid="$1" want; want="$(lab_name_of "$vmid")"
  [ -n "$want" ] || return 1
  [ "$(vm_name "$vmid")" = "$want" ] || return 1
  vm_tagged "$vmid"
}

# ============================================================ destroy
if [ "$MODE" = "destroy" ]; then
  echo "[destroy] このスクリプトが作った VM のみ削除します"
  for vmid in "${VMIDS[@]}"; do
    qm status "$vmid" >/dev/null 2>&1 || continue
    if ! vm_is_ours "$vmid"; then
      # 所有印のタグは作成の **最後** に付くため、途中で失敗した VM は「名前は一致するが
      # タグなし」で残る。ここでタグだけを見てスキップすると、作成側が出す
      # 「'$0 destroy' で掃除するか手動確認を」に従っても消えず、堂々巡りになる。
      # 名前が一致するものは作りかけとみなして削除対象に含める。
      if [ "$(vm_name "$vmid")" = "$(lab_name_of "$vmid")" ]; then
        echo "  VM ${vmid} ($(vm_name "$vmid")): タグなし (作成途中とみなして削除します)" >&2
      else
        echo "  VM ${vmid} ($(vm_name "$vmid")): このスクリプトの作成物ではないためスキップ" >&2
        continue
      fi
    fi
    qm stop "$vmid" --timeout 60 >/dev/null 2>&1 || true
    if qm destroy "$vmid" --purge; then
      echo "  VM ${vmid}: 削除"
    else
      echo "  VM ${vmid}: 削除失敗 (ロック中?)。手動で確認してください" >&2
    fi
  done
  echo "[完了] ブリッジ vmbr1-4 は残しています"
  exit 0
fi

# ============================================================ ips (接続先の表示)
# guest-agent が入らない環境 (snippets 対応ストレージが無い) でも VM に入れるように、
# IPv6 のリンクローカルアドレスで接続先を解決する。
# リンクローカルは MAC から決まるので DHCP に依存せず、常に同じ値になる。
if [ "$MODE" = "ips" ]; then
  echo "[ips] 管理ブリッジ (${MGMT_BRIDGE}) 上の VM を探します"
  # 近隣キャッシュを埋める: 全ノードマルチキャストへ ping して応答させる
  # (IPv4 のブロードキャストを撒かないので、同居している家庭 LAN に影響しない)
  if command -v ping6 >/dev/null 2>&1; then
    ping6 -c 2 -W 1 -I "$MGMT_BRIDGE" ff02::1 >/dev/null 2>&1 || true
  else
    ping -6 -c 2 -W 1 -I "$MGMT_BRIDGE" ff02::1 >/dev/null 2>&1 || true
  fi
  printf '  %-6s %-12s %-19s %s\n' VMID NAME MAC 接続先
  for vmid in "${VMIDS[@]}"; do
    qm status "$vmid" >/dev/null 2>&1 || continue
    vm_is_ours "$vmid" || continue
    # 管理ブリッジに繋がっている NIC を探す。net0 が管理とは限らない
    # (OpenWrt-CE は net0=LAN/vmbr4, net1=WAN/vmbr1 で、管理 NIC を持たない)
    mac="$(qm config "$vmid" | awk -v br="bridge=${MGMT_BRIDGE}" '
             /^net[0-9]+:/ && index($0, br) {
               if (match($0, /[0-9A-Fa-f:]{17}/)) { print tolower(substr($0, RSTART, RLENGTH)); exit }
             }')"
    if [ -z "$mac" ]; then
      printf '  %-6s %-12s %-19s %s\n' "$vmid" "$(lab_name_of "$vmid")" "-" \
        "(${MGMT_BRIDGE} に NIC なし: qm terminal ${vmid} で操作)"
      continue
    fi
    # MAC は "lladdr" の次のトークン。列位置は iproute2 の版で変わるので位置に依存しない
    lladdr="$(ip -6 neigh show dev "$MGMT_BRIDGE" 2>/dev/null \
              | awk -v m="$mac" '$1 ~ /^fe80:/ {
                  for (i = 1; i < NF; i++)
                    if ($i == "lladdr" && tolower($(i+1)) == m) { print $1; exit }
                }')"
    if [ -n "$lladdr" ]; then
      dest="${lladdr}%${MGMT_BRIDGE}"
    else
      dest="(未検出: 起動直後かも。少し待って再実行 / qm terminal ${vmid})"
    fi
    printf '  %-6s %-12s %-19s %s\n' "$vmid" "$(lab_name_of "$vmid")" "$mac" "$dest"
  done
  cat <<EOF

使い方 (IPv6 リンクローカルなので %${MGMT_BRIDGE} を必ず付ける):
  ssh ${CIUSER}@fe80::xxxx%${MGMT_BRIDGE}
  scp -r <ラボのパス>/lab/ipoe ${CIUSER}@[fe80::xxxx%${MGMT_BRIDGE}]:~/

IPv4 で入りたい場合は、家庭 LAN のルータの DHCP リース一覧で上記 MAC を探してください。
guest-agent を使えるようにするなら (任意):
  pvesm set local --content iso,vztmpl,backup,snippets
  ./provision.sh destroy && ./provision.sh     # 作り直しが必要
EOF
  exit 0
fi

# ============================================================ 事前検証
echo "[検証] 環境を確認します"

# --- PVE バージョン ---
PVE_VER="$(pveversion 2>/dev/null | sed -nE 's|^pve-manager/([0-9]+\.[0-9]+).*|\1|p' | head -1)"
[ -n "$PVE_VER" ] || { echo "ERROR: pveversion からバージョンを取得できません" >&2; exit 1; }
USE_IMPORTDISK=0
if awk "BEGIN{exit !($PVE_VER < 7.2)}"; then USE_IMPORTDISK=1; fi
echo "  PVE バージョン: ${PVE_VER} (ディスク取り込み: $([ "$USE_IMPORTDISK" = 1 ] && echo 'qm importdisk' || echo 'import-from'))"

# --- ストレージ ---
if [ -z "$STORAGE" ]; then
  # images を置けてスナップショットが効くものを優先して自動検出
  for want in lvmthin zfspool nfs dir cifs rbd; do
    cand="$(pvesm status --content images 2>/dev/null | awk -v t="$want" 'NR>1 && $2==t && $3=="active"{print $1; exit}')"
    [ -n "$cand" ] && { STORAGE="$cand"; break; }
  done
  [ -n "$STORAGE" ] || STORAGE="$(pvesm status --content images 2>/dev/null | awk 'NR>1 && $3=="active"{print $1; exit}')"
  [ -n "$STORAGE" ] || { echo "ERROR: images を置けるストレージが見つかりません。STORAGE=<名前> で指定してください" >&2; pvesm status >&2; exit 1; }
  echo "  ストレージ: ${STORAGE} (自動検出)"
fi

SLINE="$(pvesm status 2>/dev/null | awk -v s="$STORAGE" 'NR>1 && $1==s{print; exit}')"
if [ -z "$SLINE" ]; then
  echo "ERROR: ストレージ '${STORAGE}' がありません。候補:" >&2; pvesm status >&2; exit 1
fi
STYPE="$(echo "$SLINE" | awk '{print $2}')"
DISK_OPT=""
SNAP_OK="yes"
case "$STYPE" in
  iscsi|iscsidirect)
    echo "ERROR: ${STORAGE} (type=${STYPE}) は VM ディスクを作成できません。" >&2
    echo "       QNAP を iSCSI で出しているなら、その上に LVM-Thin を作るか NFS でエクスポートしてください" >&2
    exit 1 ;;
  lvm)
    SNAP_OK="no" ;;
  nfs|dir|cifs|glusterfs)
    DISK_OPT=",format=qcow2" ;;   # raw だとファイル系でもスナップショット不可
esac
echo "  ストレージ種別: ${STYPE} / スナップショット: ${SNAP_OK}${DISK_OPT:+ / format=qcow2 を明示}"

if [ "$SNAP_OK" = "no" ] && [ "$ALLOW_NO_SNAPSHOT" != "1" ]; then
  cat >&2 <<EOF

  警告: ${STORAGE} (type=${STYPE}) は **スナップショットが使えません**。
        このラボは「スナップショット取得 → わざと壊す → 数秒で戻す」を前提に
        設計しているため、壊す系の検証ごとに VM 再作成が必要になり価値が半減します。
        推奨: NFS でエクスポートする / iSCSI 上に LVM-Thin を作る / ローカルディスクを使う
EOF
  if [ -t 0 ]; then
    read -r -p "  それでも続行しますか? [y/N] " _ans
    [ "${_ans:-n}" = "y" ] || exit 1
  else
    echo "  (非対話実行のため中断しました。続行するには ALLOW_NO_SNAPSHOT=1 を付けてください)" >&2
    exit 1
  fi
fi

# --- VMID の衝突 ---
CONFLICT=0
FOUND_VM=0
for vmid in "${VMIDS[@]}"; do
  qm status "$vmid" >/dev/null 2>&1 || continue
  FOUND_VM=1
  if vm_is_ours "$vmid"; then
    echo "  VMID ${vmid}: このラボの VM が既存 ($(vm_name "$vmid"))"
  else
    echo "  VMID ${vmid}: **別用途の VM が使用中** ($(vm_name "$vmid"))" >&2
    CONFLICT=1
  fi
done
[ "$FOUND_VM" = "0" ] && echo "  VMID 9001-9010: すべて空き"
if [ "$CONFLICT" = "1" ]; then
  cat >&2 <<'EOF'

  ERROR: VMID 9001-9010 に別用途の VM があります。
         このスクリプトは他人の VM を削除・起動しないため安全側で中断しました。
         対処: 当該 VM を別 ID へ退避するか、スクリプト冒頭の VMIDS / lab_name_of を
               空いている ID 帯に書き換えてください。
EOF
  exit 1
fi

# --- 公開鍵 ---
[ -f "$SSHKEY" ] || { echo "ERROR: 公開鍵が見つかりません: ${SSHKEY}" >&2; echo "  sudo 実行では既定が /root/.ssh/id_rsa.pub です。SSHKEY=<パス> で指定してください" >&2; exit 1; }
echo "  公開鍵: ${SSHKEY}"

# --- GUI 未適用のネットワーク変更 ---
if [ -f /etc/network/interfaces.new ]; then
  echo "ERROR: GUI の未適用ネットワーク変更 (/etc/network/interfaces.new) があります。" >&2
  echo "       このまま追記すると後で GUI の Apply に上書きされます。先に適用または破棄してください" >&2
  exit 1
fi

# --- 既存ブリッジ (vmbr1-4 が別用途で使われていないか) ---
# 別用途のブリッジにラボをぶら下げると NGN-SIM の RA / DHCPv6-PD が既存 L2 に流れ、
# 同居 VM (CML 等) の IPv6 を汚染するため、ここで検出して中断する
BR_CONFLICT=0
BR_EXISTING=""
for br in vmbr1 vmbr2 vmbr3 vmbr4; do
  grep -qE "^iface[[:space:]]+${br}[[:space:]]" /etc/network/interfaces 2>/dev/null || continue
  if grep -A8 -E "^iface[[:space:]]+${br}[[:space:]]" /etc/network/interfaces | grep -q "${BRIDGE_TAG}"; then
    BR_EXISTING="${BR_EXISTING} ${br}(ラボ用)"
  else
    echo "  ${br}: **別用途のブリッジが存在** (CML の External Connector 等の可能性)" >&2
    BR_CONFLICT=1
  fi
done
if [ "$BR_CONFLICT" = "1" ]; then
  cat >&2 <<'EOF'

  ERROR: vmbr1-4 に別用途のブリッジがあります。
         ここにラボをぶら下げると NGN-SIM の RA / DHCPv6-PD が既存 L2 に流れ、
         同居 VM の IPv6 を汚染します。安全側で中断しました。
         対処: 既存ブリッジの用途を確認し、空いている番号へ変更してください
               (ensure_bridge の呼び出しと各 VM の bridge= を揃えて書き換え)
EOF
  exit 1
fi
if [ -n "$BR_EXISTING" ]; then
  echo "  既存ブリッジ:${BR_EXISTING}"
else
  echo "  ブリッジ vmbr1-4: すべて未使用 (これから作成)"
fi

# --- 容量 (VM 5 台で概ね 50-60GB 使う) ---
# pvesm status の列は  Name Type Status Total Used Available %  なので空きは $6。
# $5 は Used で、これを空きとして読むと「満杯のストレージほど空きが多い」と
# 誤報告して 70GB 未満の警告をすり抜ける
SAVAIL_KB="$(echo "$SLINE" | awk '{print $6}')"
if [ -n "$SAVAIL_KB" ] && [ "$SAVAIL_KB" -gt 0 ] 2>/dev/null; then
  SAVAIL_GB=$((SAVAIL_KB / 1024 / 1024))
  echo "  ${STORAGE} の空き: 約 ${SAVAIL_GB}GB (VM 5 台で 50-60GB 使用)"
  if [ "$SAVAIL_GB" -lt 70 ]; then
    echo "  警告: 空き容量が少なめです。WITH_OPENWRT=0 / WITH_CLIENT=0 で減らすか、別ストレージを指定してください" >&2
  fi
fi

if [ "$MODE" = "preflight" ]; then
  echo "[完了] 事前検証のみ実行しました (何も変更していません)"
  exit 0
fi

# ============================================================ ブリッジ
echo "[1/4] ブリッジを準備します"
NEED_RELOAD=0
ensure_bridge() {  # $1=ブリッジ名 $2=用途コメント $3=uplink(省略可)
  local br="$1" note="$2" up="${3:-none}"
  if grep -qE "^iface[[:space:]]+${br}[[:space:]]" /etc/network/interfaces 2>/dev/null; then
    # 自分が作ったものか (直後のコメントに目印があるか) を確認
    if ! grep -A8 -E "^iface[[:space:]]+${br}[[:space:]]" /etc/network/interfaces | grep -q "${BRIDGE_TAG}"; then
      cat >&2 <<EOF
ERROR: ${br} は既存の別用途ブリッジです (CML の External Connector 等の可能性)。
       ここにラボをぶら下げると NGN-SIM の RA / DHCPv6-PD が既存 L2 に流れ、
       同居 VM の IPv6 を汚染します。
       対処: 既存 ${br} の用途を確認し、空いているブリッジ名に変更してください
             (このスクリプトの ensure_bridge 呼び出しと各 VM の bridge= を揃えて書き換え)
EOF
      exit 1
    fi
    if [ "$(cat "/sys/class/net/${br}/bridge/multicast_snooping" 2>/dev/null || echo 0)" = "1" ]; then
      echo "  警告: ${br} は multicast snooping 有効。RA/DHCPv6 が VM に届かず IPv6 が死にます" >&2
    fi
    echo "  ${br}: 既存 (ラボ用) のためスキップ"
    return
  fi
  cat >> /etc/network/interfaces <<EOF

auto ${br}
iface ${br} inet manual
	bridge-ports ${up}
	bridge-stp off
	bridge-fd 0
	bridge-mcsnoop 0
# ${BRIDGE_TAG}: ${note}
EOF
  echo "  ${br}: 追加 (${note}, uplink=${up})"
  NEED_RELOAD=1
}

cp -a /etc/network/interfaces "/etc/network/interfaces.bak.$(date +%Y%m%d%H%M%S)"
# bridge-mcsnoop 0 は必須: snooping が有効だと RA/NA/DHCPv6 が VM に届かず IPv6 が死ぬ
ensure_bridge vmbr1 "アクセス網 (PG-ACCESS相当)" "${ACCESS_UPLINK}"
ensure_bridge vmbr2 "NGN網内 (PG-CORE相当)"
ensure_bridge vmbr3 "模擬インターネット (PG-INET相当)"
ensure_bridge vmbr4 "CPE配下のクライアント側LAN"

if [ "$NEED_RELOAD" = "1" ]; then
  if command -v ifreload >/dev/null 2>&1; then
    if ! ifreload -a; then
      echo "ERROR: ifreload に失敗しました。/etc/network/interfaces.bak.* から復元してください" >&2
      exit 1
    fi
    echo "  ネットワーク設定を反映しました"
  else
    echo "  注意: ifreload がありません。手動で反映してください (systemctl restart networking 等)" >&2
  fi
fi

[ "$MODE" = "bridges" ] && { echo "[完了] ブリッジのみ作成しました"; exit 0; }

# ============================================================ イメージ
echo "[2/4] イメージを準備します"
mkdir -p "$IMG_DIR"
fetch() {  # $1=URL $2=保存先 ($2.part 経由で落とすので中断しても壊れない)
  local url="$1" dst="$2"
  wget -q --show-progress -O "${dst}.part" "$url"
  mv "${dst}.part" "$dst"
}
if [ ! -f "$UBUNTU_IMG" ]; then
  echo "  Ubuntu 24.04 クラウドイメージを取得中..."
  fetch "$UBUNTU_URL" "$UBUNTU_IMG"
else
  echo "  Ubuntu イメージ: 既存を使用"
fi
if [ "$WITH_OPENWRT" = "1" ]; then
  if [ ! -f "$OPENWRT_IMG" ]; then
    echo "  OpenWrt ${OPENWRT_VER} イメージを取得中..."
    fetch "$OPENWRT_URL" "${OPENWRT_IMG}.gz"
    # gzip は展開に成功しても警告があると終了コード 2 を返す
    # (OpenWrt の配布 .gz は "trailing garbage ignored" が出る)。
    # set -e のままだとここで黙って停止してしまうため、2 だけは許容する。
    # 終了コードは `|| rc=$?` で受ける。`if ! cmd; then rc=$?` は否定後の 0 を拾うので使えない
    gz_rc=0
    gunzip -f "${OPENWRT_IMG}.gz" || gz_rc=$?
    case "$gz_rc" in
      0) ;;
      2) echo "  (gzip の警告は無視しました: 展開自体は成功しています)" ;;
      *) echo "ERROR: OpenWrt イメージの展開に失敗しました (gzip 終了コード ${gz_rc})" >&2
         exit "$gz_rc" ;;
    esac
    [ -s "$OPENWRT_IMG" ] || {
      echo "ERROR: 展開後の ${OPENWRT_IMG} が空です。取得し直してください" >&2; exit 1; }
  else
    echo "  OpenWrt イメージ: 既存を使用"
  fi
  # 空き領域を予約するだけ (rootfs の拡張は OpenWrt 側で別途。ラボ用途なら未拡張でも足りる)
  # ダウンロード分岐の外に置く: 中で失敗して再実行したときに resize だけ飛ばされるのを防ぐ
  # raw イメージなのでファイルサイズ = 仮想サイズ。qemu-img info の JSON を解析する必要はない
  if [ "$(stat -c %s "$OPENWRT_IMG")" -lt 2147483648 ]; then
    qemu-img resize -f raw "$OPENWRT_IMG" 2G >/dev/null
    echo "  OpenWrt イメージを 2G に拡張しました"
  fi
fi

# cloud-init で qemu-guest-agent を入れる (snippets が使えるストレージがある場合のみ)
VENDOR_OPT=""
SNIP_STORE="$(pvesm status --content snippets 2>/dev/null | awk 'NR>1 && $3=="active"{print $1; exit}')"
if [ -n "$SNIP_STORE" ]; then
  SNIP_PATH="$(pvesm path "${SNIP_STORE}:snippets/ipoe-vendor.yaml" 2>/dev/null || true)"
  if [ -n "$SNIP_PATH" ]; then
    mkdir -p "$(dirname "$SNIP_PATH")"
    cat > "$SNIP_PATH" <<'EOF'
#cloud-config
packages:
  - qemu-guest-agent
runcmd:
  - [ systemctl, enable, --now, qemu-guest-agent ]
EOF
    VENDOR_OPT="${SNIP_STORE}:snippets/ipoe-vendor.yaml"
    echo "  guest-agent 導入用 snippet を配置: ${VENDOR_OPT}"
  fi
fi
[ -n "$VENDOR_OPT" ] || echo "  注意: snippets 対応ストレージがないため guest-agent は入りません (qm guest cmd は使えない)"

# ============================================================ VM
import_boot_disk() {  # $1=vmid $2=イメージパス
  if [ "$USE_IMPORTDISK" = 1 ]; then
    qm importdisk "$1" "$2" "$STORAGE" >/dev/null
    local vol; vol="$(qm config "$1" | awk -F': ' '/^unused0:/{print $2; exit}')"
    [ -n "$vol" ] || { echo "ERROR: VM $1 のディスク取り込みに失敗しました" >&2; exit 1; }
    qm set "$1" --scsi0 "$vol" >/dev/null
  else
    qm set "$1" --scsi0 "${STORAGE}:0,import-from=$2${DISK_OPT}" >/dev/null
  fi
}

create_ubuntu_vm() {  # $1=vmid $2=name $3=memory $4=cores $5=net1 $6=net2(省略可)
  local vmid="$1" name="$2" mem="$3" cores="$4" net1="$5" net2="${6:-}"
  if qm status "$vmid" >/dev/null 2>&1; then
    if vm_is_ours "$vmid"; then echo "  VM ${vmid} (${name}): 既存のためスキップ"; return; fi
    echo "ERROR: VMID ${vmid} に未完成または別用途の VM があります。'$0 destroy' で掃除するか手動確認を" >&2
    exit 1
  fi
  local args=(--net0 "virtio,bridge=${MGMT_BRIDGE}" --net1 "$net1")
  [ -n "$net2" ] && args+=(--net2 "$net2")

  qm create "$vmid" --name "$name" --memory "$mem" --cores "$cores" --ostype l26 \
    --scsihw virtio-scsi-single --serial0 socket --agent 1 "${args[@]}"
  import_boot_disk "$vmid" "$UBUNTU_IMG"
  qm set "$vmid" --ide2 "${STORAGE}:cloudinit" --boot order=scsi0 >/dev/null
  qm set "$vmid" --ciuser "$CIUSER" --sshkeys "$SSHKEY" --ipconfig0 ip=dhcp >/dev/null
  [ -n "$VENDOR_OPT" ] && qm set "$vmid" --cicustom "vendor=${VENDOR_OPT}" >/dev/null
  qm resize "$vmid" scsi0 +6G >/dev/null
  qm set "$vmid" --tags "$LAB_TAG" >/dev/null   # 完成マーカー (所有者判定に使う)
  echo "  VM ${vmid} (${name}): 作成"
}

echo "[3/4] VM を作成します"
create_ubuntu_vm 9001 ngn-sim  2048 2 \
  "virtio=02:AC:00:00:00:01,bridge=vmbr1" "virtio=02:C0:00:00:00:01,bridge=vmbr2"
create_ubuntu_vm 9002 vne-inet 2048 2 \
  "virtio=02:C0:00:00:00:02,bridge=vmbr2" "virtio=02:1E:00:00:00:02,bridge=vmbr3"
create_ubuntu_vm 9003 bras     2048 2 \
  "virtio=02:AC:00:00:00:03,bridge=vmbr1" "virtio=02:1E:00:00:00:03,bridge=vmbr3"
[ "$WITH_CLIENT" = "1" ] && create_ubuntu_vm 9004 lab-client 1024 1 "virtio=02:C1:00:00:00:04,bridge=vmbr4"
# SPLIT_INET=1 で INET-SIM を別 VM (9005) に分ける。
# **DS-Lite のポート開放不可 (test-matrix R4) を検証するなら必須。**
# 同居 (9002 に相乗り) だと、INET-SIM 宛がローカル配送になり AFTR の
# masquerade (oifname 条件) が当たらず、網側 NAT が効かない。
# 「PASS するのに出口がクライアントの私設アドレスのまま」という形で現れる。
[ "$SPLIT_INET" = "1" ] && create_ubuntu_vm 9005 inet-sim 1024 1 "virtio=02:1E:00:00:00:05,bridge=vmbr3"

if [ "$WITH_OPENWRT" = "1" ]; then
  if qm status 9010 >/dev/null 2>&1; then
    if vm_is_ours 9010; then
      echo "  VM 9010 (openwrt-ce): 既存のためスキップ"
    else
      echo "ERROR: VMID 9010 に別用途の VM があります" >&2; exit 1
    fi
  else
    # OpenWrt x86 の既定は eth0=LAN / eth1=WAN。net0 を LAN 側にする
    qm create 9010 --name openwrt-ce --memory 512 --cores 1 --ostype l26 \
      --scsihw virtio-scsi-single --serial0 socket \
      --net0 "virtio,bridge=vmbr4" \
      --net1 "virtio=02:AC:00:00:00:10,bridge=vmbr1"
    # map / ds-lite は既定イメージに入っておらず、ラボ内にインターネットも無いので
    # opkg install できない。管理NICを足して外に出られるようにする (既定は無効)
    if [ "$OPENWRT_MGMT" = "1" ]; then
      qm set 9010 --net2 "virtio,bridge=${MGMT_BRIDGE}" >/dev/null
    fi
    import_boot_disk 9010 "$OPENWRT_IMG"
    qm set 9010 --boot order=scsi0 >/dev/null
    qm set 9010 --tags "$LAB_TAG" >/dev/null
    if [ "$OPENWRT_MGMT" = "1" ]; then
      echo "  VM 9010 (openwrt-ce): 作成 (net0=LAN/vmbr4, net1=WAN/vmbr1, net2=管理/${MGMT_BRIDGE})"
    else
      echo "  VM 9010 (openwrt-ce): 作成 (net0=LAN/vmbr4, net1=WAN/vmbr1)"
      echo "    注意: 管理NICなし。map/ds-lite の opkg install には OPENWRT_MGMT=1 が必要です"
    fi
  fi
fi

echo "[4/4] VM を起動します"
for vmid in "${VMIDS[@]}"; do
  qm status "$vmid" 2>/dev/null | grep -q stopped || continue
  vm_is_ours "$vmid" || continue          # 他人の VM は起動しない
  qm start "$vmid"
  echo "  VM ${vmid}: 起動"
done

cat <<EOF

========================================================================
[完了] 検証ラボの土台ができました   (ストレージ: ${STORAGE} / ${STYPE} / snapshot=${SNAP_OK})

  9001 ngn-sim    NGN網模擬      (ACCESS + CORE)
  9002 vne-inet   VNE+模擬INET   (CORE + INET)
  9003 bras       PPPoE終端      (ACCESS + INET)
  9004 lab-client 検証クライアント (CPE配下)
  9010 openwrt-ce リファレンスCPE (net0=LAN/vmbr4, net1=WAN/vmbr1)

次の手順:
  1. 各VMの接続先を確認
       ./provision.sh ips                 # IPv6 リンクローカルで一覧表示 (DHCP に依存しない)
       qm terminal <vmid>                 # 上で出ないときはシリアルコンソール (抜けるのは Ctrl-O)
$([ -n "$VENDOR_OPT" ] && echo "       qm guest cmd <vmid> network-get-interfaces   # 起動後しばらくすると使える" || echo "       ※ guest-agent 未導入のため qm guest cmd は使えません (ips モードを使ってください)")
  2. lab/ipoe をコピー (リンクローカルは [] で囲み %${MGMT_BRIDGE} を付ける)
       scp -r lab/ipoe ${CIUSER}@[fe80::xxxx%${MGMT_BRIDGE}]:~/
  3. セットアップ実行 (NIC名は MAC から自動判別されるので指定不要)
       sudo ./ipoe/ngn/setup-ngn.sh pd        # 9001
       sudo ./ipoe/vne/setup-map-br.sh        # 9002
       sudo ./ipoe/vne/setup-aftr.sh          # 9002
       sudo ./ipoe/inet/setup-inet.sh         # 9002
       sudo ./ipoe/bras/setup-bras.sh         # 9003
  4. 全VMのスナップショットを取得 (メモリ込み)$([ "$SNAP_OK" = "no" ] && echo " ← このストレージでは不可" || true)

実機CPE(892FJ等)を繋ぐ場合: ACCESS_UPLINK=<物理NIC名> で再実行すると
vmbr1 に物理NICがアップリンクされ、実機が同じL2に乗ります。

やり直したいとき: $0 destroy → もう一度 $0
環境確認だけしたいとき: $0 preflight
========================================================================
EOF
