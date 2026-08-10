#!/bin/bash
# 作業機 (SSH できる PC) から、リポジトリの lab/ipoe を Proxmox ホストと各 VM に配る。
#
#   usage: ./lab/ipoe/deploy.sh              … ホスト + Linux VM 全台に配布
#          ./lab/ipoe/deploy.sh host         … Proxmox ホストだけに配布
#          ./lab/ipoe/deploy.sh vms          … ホスト経由で VM だけに配布 (ホストは既に最新の前提)
#
#   環境変数:
#     PVE_HOST=192.168.11.20    Proxmox ホスト
#     PVE_USER=root             ホストのログインユーザ
#     HOST_DIR=/root/ipoe-lab   ホスト側の展開先 (lab/ipoe がこの下に入る)
#     CIUSER=labadmin           VM のログインユーザ
#
# 正本はリポジトリ (git) です。ホストと VM は **配布先** であって編集場所ではありません。
# ホストや VM で直接直した変更は、次回の配布で上書きされて消えます。
# 直すときは必ずリポジトリ側を直し、commit してから配布してください。
#
# rsync は Proxmox に入っていない場合があるため、tar を ssh に流す方式にしています
# (tar と ssh はどちらの環境にも必ずある)。
set -euo pipefail

MODE="${1:-all}"
PVE_HOST="${PVE_HOST:-192.168.11.20}"
PVE_USER="${PVE_USER:-root}"
HOST_DIR="${HOST_DIR:-/root/ipoe-lab}"
CIUSER="${CIUSER:-labadmin}"
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

# リポジトリのルートを特定して、そこからの相対で lab/ipoe を掴む
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
[ -d "${REPO_ROOT}/lab/ipoe" ] || { echo "ERROR: ${REPO_ROOT}/lab/ipoe が見つかりません" >&2; exit 1; }

# 未コミットの変更があるなら警告する (ホストだけ新しい状態を作らないため)
if command -v git >/dev/null 2>&1 && git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  if ! git -C "$REPO_ROOT" diff --quiet -- lab/ipoe || \
     ! git -C "$REPO_ROOT" diff --cached --quiet -- lab/ipoe; then
    echo "警告: lab/ipoe に未コミットの変更があります。" >&2
    echo "      配布は続行しますが、動いた時点で必ず commit / push してください" >&2
    echo "      (ホストと VM だけが新しい状態は、後から再現できません)" >&2
  fi
  echo "[deploy] リポジトリ: $(git -C "$REPO_ROOT" rev-parse --short HEAD) ($(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD))"
fi

deploy_host() {
  echo "[deploy] ${PVE_USER}@${PVE_HOST}:${HOST_DIR}/lab/ipoe へ配布"
  tar cz -C "${REPO_ROOT}/lab" ipoe \
    | ssh "${SSH_OPTS[@]}" "${PVE_USER}@${PVE_HOST}" \
        "mkdir -p '${HOST_DIR}/lab' && tar xz -C '${HOST_DIR}/lab' && chmod +x '${HOST_DIR}'/lab/ipoe/*/*.sh 2>/dev/null || true"
  echo "  ホスト: OK"
}

deploy_vms() {
  echo "[deploy] ホスト経由で VM へ配布 (IPv6 リンクローカル)"
  # ホスト側で ips を実行して接続先を取得する。リンクローカルは destroy→再作成で変わるので毎回取る
  local lls
  lls="$(ssh "${SSH_OPTS[@]}" "${PVE_USER}@${PVE_HOST}" \
          "cd '${HOST_DIR}/lab/ipoe/proxmox' && ./provision.sh ips" \
        | awk '$1 ~ /^[0-9][0-9][0-9][0-9]$/ { for (i=1;i<=NF;i++) if ($i ~ /^fe80::/) print $i }')"
  if [ -z "$lls" ]; then
    echo "ERROR: VM のリンクローカルアドレスが取得できません。VM が起動しているか確認してください" >&2
    exit 1
  fi
  local n=0
  while read -r ll; do
    [ -n "$ll" ] || continue
    # ホスト上で tar を展開して VM に流す (作業機から VM のリンクローカルには届かないため)
    # -n は必須: 付けないと ssh が while の stdin (<<< "$lls") を読み尽くし、
    # 2 台目以降のループが回らず「1 台だけ配って正常終了」する
    if ssh -n "${SSH_OPTS[@]}" "${PVE_USER}@${PVE_HOST}" \
         "tar cz -C '${HOST_DIR}/lab' ipoe | ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 ${CIUSER}@'${ll}' 'tar xz -C ~ && chmod +x ~/ipoe/*/*.sh 2>/dev/null || true'"; then
      echo "  ${ll}: OK"
      n=$((n+1))
    else
      echo "  ${ll}: 失敗 (起動直後か鍵未登録の可能性)" >&2
    fi
  done <<< "$lls"
  echo "  VM ${n} 台に配布しました"
  echo
  echo "注意: OpenWrt-CE (9010) は管理NICが無いため対象外です。qm terminal 9010 で操作してください"
}

case "$MODE" in
  host) deploy_host ;;
  vms)  deploy_vms ;;
  all)  deploy_host; deploy_vms ;;
  *)    echo "usage: $0 [all|host|vms]" >&2; exit 1 ;;
esac
