#!/bin/bash
# 管理NICを持たない VM (OpenWrt-CE) のシリアルコンソールにコマンドを送り、出力を取る。
# **Proxmox ホスト上で実行する。**
#
#   usage: ./owrt-console.sh 9010 'uci show network'
#          echo 'uci show network' | ./owrt-console.sh 9010
#
#   環境変数:
#     OWRT_WAIT=180   マーカーが返るまでの最大待ち時間 (秒)。opkg など遅い処理で伸ばす
#
# なぜ qm terminal ではないか:
#   qm terminal は socat の PTY 端点を使うため tty を要求し、パイプで駆動すると
#     socat[...] E tcgetattr(0, ...): Inappropriate ioctl for device
#   で即座に落ちる。人間が対話で使う分には qm terminal でよいが、スクリプトからは
#   Proxmox が VM ごとに作る unix ソケットに直接つなぐ必要がある。
#
#   人間が手作業でやる場合 (会社環境・runbook 向け) はこちら:
#     qm terminal 9010        # 抜けるのは Ctrl-O
#
# 仕組み: コマンドの後ろに終了マーカーの echo を送り、awk がマーカー行を見たら exit する。
# awk が閉じると socat が SIGPIPE で死ぬので、遅いコマンドでも速いコマンドでも
# 「終わった時点で」戻る (固定 sleep で待たなくて済む)。
set -euo pipefail

VMID="${1:?usage: $0 <vmid> [command]   (command 省略時は stdin から読む)}"
CMD="${2:-}"
[ -n "$CMD" ] || CMD="$(cat)"

SOCK="/var/run/qemu-server/${VMID}.serial0"
[ -S "$SOCK" ] || { echo "ERROR: $SOCK がありません (VM $VMID は起動していますか)" >&2; exit 1; }

WAIT="${OWRT_WAIT:-180}"
MARKER="__OWRT_DONE_${VMID}__"

# マーカーは必ずクォート付きで送る。こうすると端末エコーされる行は
#   root@OpenWrt:~# echo "__OWRT_DONE_9010__"
# となり行頭がマーカーにならないので、awk の ^マーカー 判定が
# 「コマンドのエコー」ではなく「実際の出力」だけに当たる。
{
  printf '\n'
  sleep 1
  printf '%s\n' "$CMD"
  printf 'echo "%s"\n' "$MARKER"
  sleep "$WAIT"
} | timeout "$WAIT" socat - "UNIX-CONNECT:${SOCK}" 2>/dev/null \
  | awk -v m="$MARKER" 'index($0, m) == 1 { found=1; exit } { print } END { if (!found) exit 3 }'

rc="${PIPESTATUS[2]}"
if [ "$rc" = "3" ]; then
  echo "ERROR: ${WAIT}秒以内に完了マーカーが返りませんでした (OWRT_WAIT を伸ばしてください)" >&2
  exit 3
fi
