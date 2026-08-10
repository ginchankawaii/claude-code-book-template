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
#   終了コード: 0=成功 / 3=時間内にマーカーが返らなかった / 1=ソケットが無い
#
# なぜ qm terminal ではないか:
#   qm terminal は socat の PTY 端点を使うため tty を要求し、パイプで駆動すると
#     socat[...] E tcgetattr(0, ...): Inappropriate ioctl for device
#   で即座に落ちる。人間が対話で使う分には qm terminal でよいが、スクリプトからは
#   Proxmox が VM ごとに作る unix ソケットに直接つなぐ必要がある。
#
#   人間が手作業でやる場合 (会社環境・runbook 向け) はこちら:
#     qm terminal 9010        # 抜けるのは Ctrl-O
set -euo pipefail

VMID="${1:?usage: $0 <vmid> [command]   (command 省略時は stdin から読む)}"
CMD="${2:-}"
[ -n "$CMD" ] || CMD="$(cat)"

SOCK="/var/run/qemu-server/${VMID}.serial0"
[ -S "$SOCK" ] || { echo "ERROR: $SOCK がありません (VM $VMID は起動していますか)" >&2; exit 1; }

WAIT="${OWRT_WAIT:-180}"
MARKER="__OWRT_DONE_${VMID}__"

# --- 設計メモ: パイプではなくファイル + ポーリングにしている理由 -------------------
#
# 素直に  送信 | socat | awk  と繋ぐと、**必ず WAIT 秒かかる**。
# 「awk がマーカーを見て exit すれば socat が SIGPIPE で死ぬ」という想定が成り立たず、
# socat が SIGPIPE を受けるのは「次に書き込もうとしたとき」だから。
# コンソールはマーカー以降なにも喋らないので、socat は timeout まで生き残る。
#
# 併せて踏んだ罠 (どれも「速くならない」形で現れるので原因が見えにくい):
#   - socat は stdin が EOF になると接続を畳む。送信側を開いたままにする必要がある
#     (socat -t は EOF 後の待ち時間として効かず、1 秒台で切れて空振りした)
#   - 送信側を `{...} | socat` のパイプライン一員にすると、bash が全メンバーの
#     終了を待つので、やはり毎回 WAIT 秒ブロックする
#   - プロセス置換にしても、残った sleep が ssh の stderr を握るため ssh 越しだと遅い
#
# → socat の出力を**ファイルに落とし**、マーカーが現れたかを 0.5 秒間隔で見る。
#   見えたら socat を kill して wait で回収する。EOF も SIGPIPE も関与しないので、
#   速いコマンドは速く、遅いコマンド (opkg 等) は WAIT まで待てる。
# --------------------------------------------------------------------------------

TMPD="$(mktemp -d -t owrt-console.XXXXXX)"
SOCAT=""
cleanup() {
  if [ -n "$SOCAT" ]; then
    kill "$SOCAT" 2>/dev/null || true
    wait "$SOCAT" 2>/dev/null || true      # 回収しないと ssh 越しで戻れなくなる
  fi
  rm -rf "$TMPD"
}
trap cleanup EXIT

IN="${TMPD}/in"
LOG="${TMPD}/log"
mkfifo "$IN"
: > "$LOG"

# 書き込み端を自分で保持する。これで socat の stdin が EOF にならず、
# 開いたままにするための常駐プロセスが要らない。
exec 3<>"$IN"

timeout "$WAIT" socat - "UNIX-CONNECT:${SOCK}" < "$IN" > "$LOG" 2>/dev/null &
SOCAT=$!

# マーカーは必ずクォート付きで送る。こうすると端末エコーされる行は
#   root@OpenWrt:~# echo "__OWRT_DONE_9010__"
# となり行頭がマーカーにならないので、行頭一致の判定が
# 「コマンドのエコー」ではなく「実際の出力」だけに当たる。
printf '\n' >&3
sleep 1
printf '%s\n' "$CMD" >&3
printf 'echo "%s"\n' "$MARKER" >&3

rc=3
deadline=$(( WAIT * 2 ))
for _ in $(seq "$deadline"); do
  if grep -q "^${MARKER}" "$LOG" 2>/dev/null; then rc=0; break; fi
  kill -0 "$SOCAT" 2>/dev/null || break      # timeout に殺された = 時間切れ
  sleep 0.5
done

# マーカー行の手前までを出力する (マーカー自身とそれ以降は捨てる)
sed "/^${MARKER}/,\$d" "$LOG"

if [ "$rc" != "0" ]; then
  echo "ERROR: ${WAIT}秒以内に完了マーカーが返りませんでした (OWRT_WAIT を伸ばしてください)" >&2
fi
exit "$rc"
