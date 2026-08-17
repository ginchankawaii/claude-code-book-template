#!/bin/bash
# ラボのモードを 1 コマンドで切り替える (ハンズオンの司会用)
#
#   usage: ./lab-mode.sh <モード> [オプション]
#
#     status            … いま何方式かを表示する
#     ra                … ひかり電話なし相当 (RA 方式 /64) に切り替え
#     pd                … ひかり電話あり相当 (DHCPv6-PD 方式 /56) に切り替え
#     mape              … IPv4 の運び方を MAP-E にする (AFTR は止める)
#     dslite <CE の IPv6> … IPv4 の運び方を DS-Lite にする (BR は止める)
#     prov on|off       … MAP-E のルール配布サーバ (本番と同じ自動設定経路) を起動/停止
#     prov status|log|ca … 状態表示 / CPE から来た要求を見る / ルータ用 CA を出す
#     prov both|mape|dslite … 配る方式を絞る (MAP-E で落ちるときの切り分け)
#     prov rule shared|fixed … 共有IP / 固定IP1相当 を切替 (BR の張り替えも自動)
#     break mtu         … MTU ブラックホールを注入する
#     break dns         … IPv6 だけ死んだサイトを作る
#     restore           … 注入した障害を全部戻す
#
# **なぜこれが要るか**
#   ハンズオンで受講者にサーバ側の管理作業をやらせても学びになりません。
#   受講者は CPE (実機) に同じコマンドを打ち、**司会がこのスクリプトで環境を切り替える**。
#   「いま RA 方式です」「いま PD 方式にしました」と宣言しながら回すための道具です。
#
# **どこで実行するか**
#   各 VM に SSH できる場所ならどこでも (Proxmox / VMware のホスト、作業端末)。
#   VM のアドレスは環境変数か、同じディレクトリの lab-hosts.conf で指定します。
#
#     NGN=labadmin@fe80::xxxx%vmbr0
#     VNE=labadmin@fe80::yyyy%vmbr0
#     INET=labadmin@fe80::zzzz%vmbr0
#
#   リンクローカルを使う場合は `%<ブリッジ名>` を忘れないこと。
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
CONF="${LAB_HOSTS_CONF:-${HERE}/lab-hosts.conf}"

# **環境変数のほうを優先する。**
# 先に環境変数を退避してから conf を読み、あとで書き戻す。
# こうしないと「VNE=... ./lab-mode.sh restore」のような 1 回だけの上書きが
# conf に黙って潰され、**指定したつもりの相手とは違うホストに繋ぎに行く。**
# (フェーズ5 の実走確認中に踏んだ。テストが成立せず、原因も見えなかった)
_env_NGN="${NGN:-}"; _env_VNE="${VNE:-}"; _env_INET="${INET:-}"
[ -f "$CONF" ] && . "$CONF"
NGN="${_env_NGN:-${NGN:-}}"
VNE="${_env_VNE:-${VNE:-}}"
INET="${_env_INET:-${INET:-}}"
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

# 状態はこのファイルに覚えておく (status 表示と、期待値の案内に使う)
STATE="${LAB_MODE_STATE:-${HERE}/.lab-mode}"

die() { echo "ERROR: $*" >&2; exit 1; }

need() {  # need <変数名> <説明>
  local v="${!1:-}"
  [ -n "$v" ] || die "$1 が未設定です。${CONF} に $1=labadmin@fe80::xxxx%vmbr0 の形で書くか、環境変数で渡してください ($2)"
}

# ssh は -n を必ず付ける。付けないと呼び出し元の stdin を吸って、
# ループの中で使ったときに 1 回しか回らない (deploy.sh で実際に踏んだ)
rsh() {  # rsh <接続先> <コマンド...>
  ssh -n "${SSH_OPTS[@]}" "$1" "${@:2}"
}

state_get() { [ -f "$STATE" ] && grep -E "^$1=" "$STATE" 2>/dev/null | cut -d= -f2- || true; }
state_set() {  # state_set <キー> <値>
  touch "$STATE"
  grep -v -E "^$1=" "$STATE" > "${STATE}.tmp" 2>/dev/null || true
  echo "$1=$2" >> "${STATE}.tmp"
  mv "${STATE}.tmp" "$STATE"
}

# いまの方式から、受講者が見るべき「出口アドレス」を出す。
# **ハンズオンではこれが答え合わせの唯一の根拠**なので、切り替えるたびに表示する。
expected_src4() {
  local v6mode ipv4mode
  v6mode="$(state_get v6mode)"
  ipv4mode="$(state_get ipv4mode)"
  case "${ipv4mode}:${v6mode}" in
    mape:pd)   echo "198.51.100.10" ;;
    mape:ra)   echo "198.51.100.20" ;;
    dslite:*)  echo "203.0.113.1" ;;
    pppoe:*)   echo "203.0.113.2" ;;
    *)         echo "(不明)" ;;
  esac
}

# **状態は覚えているだけでは信用できない。**
# lab-mode.sh を使わずに手で切り替えたり、VM を再起動したりするので、
# 表示する前に実機を見て確かめる。**嘘をつく status なら無いほうがマシ。**
detect() {
  local t p
  if [ -n "$VNE" ]; then
    # **トンネルが 1 本も無いときに ipv4mode を消す枝が要る。**
    # 無いと、BR/AFTR の起動に失敗して die したあとも古い ipv4mode が残り続け、
    # status が「MAP-E です」と言いながら実際には転送経路が無い状態になる (監査 R7 #3)。
    # `OK:` を必ず出させて、到達不能 (OK 行なし) と「トンネル無し」を区別する。
    t="$(rsh "$VNE" "echo \"OK:\$(ip -6 tunnel show 2>/dev/null | cut -d: -f1 | tr '\n' ',')\"" 2>/dev/null)"
    case "$t" in
      *dslite0*) state_set ipv4mode dslite ;;
      *map0*)    state_set ipv4mode mape ;;
      OK:*)      state_set ipv4mode "" ;;   # 届いた上でトンネルが無い = 未設定
      *)         : ;;                        # 到達不能。前回の値には触れない
    esac
  fi
  if [ -n "$NGN" ]; then
    # radvd の設定に prefix が書かれていれば RA 方式、無ければ PD 方式
    #
    # **`grep -c ... || echo 0` と書いてはいけない。**
    # grep -c はマッチ 0 件のとき「0」を出力した上で終了コード 1 を返すので、
    # `|| echo 0` も走って出力が "0\n0" の 2 行になる。すると下の case が
    # `0)` ではなく `*)` に落ちて、**PD 方式を必ず RA と誤判定する**。
    # (フェーズ5 レビューで発覚。RA 側しか実走していなかったため見逃していた)
    p="$(rsh "$NGN" "grep -c '^[[:space:]]*prefix 2001:' /etc/radvd.conf 2>/dev/null" 2>/dev/null || true)"
    p="${p%%[!0-9]*}"          # 念のため先頭の数字だけ取る (CR や余計な行への保険)
    case "${p:-0}" in
      0) state_set v6mode pd ;;
      *) state_set v6mode ra ;;
    esac
  fi
}

# ── 配布ルールの実測 ────────────────────────────────────────────────
# **記帳 (state に書く) はしない。表示のたびに実物を読む。**
# 記帳方式は「部分失敗で記録が実態とズレて status が嘘をつく」を監査で
# 3 ラウンド連続 (R3〜R6) 生んだ。実測なら言えるのは 一致/不一致/確認不可 だけで、
# 古い記録を断言する嘘が構造的に起こらない。
#
# server_rule: サーバが「いま配っている」ルール。配布 JSON の eaBitLength を読む
#   (この JSON はサーバが要求のたびに読み直す実物そのもの)
# br_rule:     BR が「いま構成されている」ルール。setup-map-br.sh が成功直後に
#   自分で書く /run/map-br.state を読む (tmpfs なので再起動で実態ごと消える)
# **「測れなかった」を「測った結果」と混同しない。**
# リモートに必ず `OK:` 行を出させ、それが無ければ到達不能 = 確認不可 と確定する。
# 以前は rsh の失敗もファイル不在も同じ空文字に潰れ、ホストが落ちているだけなのに
# 「未構築」「停止中」と断定していた (監査 R7 #4/#5)。
#
# server_rule: **サービスが生きているかまで見る。**JSON がディスクにあっても
#   mape-ruleserver が止まっていれば何も配っていない (R7 #1: prov off 後に
#   「一致を実測」と断言していた)。配布実体 = プロセス + JSON の両方。
server_rule() {
  [ -n "${INET:-}" ] || { echo unknown; return; }
  local out
  out="$(rsh "$INET" "if systemctl is-active --quiet mape-ruleserver; then a=up; else a=down; fi; \
e=\$(sed -n 's/.*\"eaBitLength\": \"\([0-9]*\)\".*/\1/p' /etc/mape-ruleserver/response-jp01.json 2>/dev/null | head -1); \
echo \"OK:\$a:\$e\"" 2>/dev/null)"
  case "$out" in
    OK:down:*)  echo stopped ;;      # プロセスが無い = 配っていない
    OK:up:16)   echo shared ;;
    OK:up:0)    echo fixed ;;
    OK:up:)     echo unbuilt ;;      # 生きているが JSON が無い
    OK:up:*)    echo "ea=${out##*:}" ;;
    *)          echo unreachable ;;  # OK 行が来ない = 届いていない
  esac
}
# br_rule: **len だけでなく psid も照合する。**マーカーには psid/ce も書いてあるのに
#   len しか見ていなかったため、別モード用に張った BR (PSID 5) を「一致」と
#   断言していた (R7 #2)。ルール種別と PSID の両方を返す。
br_rule() {
  [ -n "${VNE:-}" ] || { echo unknown; return; }
  local out len psid
  out="$(rsh "$VNE" "l=\$(sed -n 's/^len=//p' /run/map-br.state 2>/dev/null | head -1); \
p=\$(sed -n 's/^psid=//p' /run/map-br.state 2>/dev/null | head -1); echo \"OK:\$l:\$p\"" 2>/dev/null)"
  case "$out" in
    OK:*) len="${out#OK:}"; psid="${len#*:}"; len="${len%%:*}" ;;
    *)    echo unreachable; return ;;
  esac
  case "$len" in
    8)  echo "shared:${psid}" ;;
    0)  echo "fixed:${psid}" ;;
    "") echo none ;;
    *)  echo "len=${len}" ;;
  esac
}
rule_jp() {
  case "$1" in
    shared)      echo "共有IP (240 ポート)" ;;
    fixed)       echo "固定IP1 相当 (64512 ポート)" ;;
    stopped)     echo "停止中 (配っていない)" ;;
    unbuilt)     echo "未構築" ;;
    none)        echo "BR 停止中/記録なし" ;;
    unknown)     echo "確認不可 (接続先未設定)" ;;
    unreachable) echo "確認不可 (到達できず)" ;;
    *)           echo "$1" ;;
  esac
}
# その v6mode で BR が持つべき PSID (共有IP: RA=3 / PD=5、固定IP: 0)
expected_psid() {
  case "$1" in
    fixed) echo 0 ;;
    shared) [ "$(state_get v6mode)" = "ra" ] && echo 3 || echo 5 ;;
    *) echo "" ;;
  esac
}

banner() {
  local v6mode ipv4mode fault v6note v4note
  v6mode="$(state_get v6mode)"; ipv4mode="$(state_get ipv4mode)"; fault="$(state_get fault)"
  case "$v6mode" in
    ra) v6note="RA 方式  … ひかり電話なし相当。/64 が 1 本だけ来る" ;;
    pd) v6note="PD 方式  … ひかり電話あり相当。/56 がまとめて降りる" ;;
    *)  v6note="(未設定)" ;;
  esac
  case "$ipv4mode" in
    mape)   v4note="MAP-E    … NAT するのは CPE 自身。使えるポートが決まる" ;;
    dslite) v4note="DS-Lite  … NAT するのは網側の AFTR。ポート開放はできない" ;;
    pppoe)  v4note="PPPoE    … 従来方式" ;;
    *)      v4note="(未設定)" ;;
  esac
  echo
  echo "================================================================"
  echo "  いまのラボの状態"
  echo "----------------------------------------------------------------"
  printf "  IPv6 の配り方 : %s\n" "$v6note"
  printf "  IPv4 の運び方 : %s\n" "$v4note"
  if [ "$ipv4mode" = "mape" ]; then
    # **実測して表示する** (記帳を読むのではなく)。理由は server_rule のコメント参照。
    # 「一致」と言うのは **ルール種別と PSID の両方**が揃ったときだけ。
    # 片方しか測らずに全部を断言するのが R7 #2 の指摘だった。
    local sr brr brkind brpsid exp
    sr="$(server_rule)"; brr="$(br_rule)"
    brkind="${brr%%:*}"; brpsid="${brr#*:}"; [ "$brpsid" = "$brr" ] && brpsid=""
    if { [ "$sr" = "shared" ] || [ "$sr" = "fixed" ]; } && \
       { [ "$brkind" = "shared" ] || [ "$brkind" = "fixed" ]; }; then
      exp="$(expected_psid "$sr")"
      if [ "$sr" != "$brkind" ]; then
        printf "  配布ルール    : ⚠ 不一致 (サーバ=%s / BR=%s)。prov rule で揃えてください\n" \
          "$(rule_jp "$sr")" "$(rule_jp "$brkind")"
      elif [ -n "$exp" ] && [ "$brpsid" != "$exp" ]; then
        printf "  配布ルール    : ⚠ %s だが **BR の PSID が %s (この方式では %s のはず)**。prov rule で張り直してください\n" \
          "$(rule_jp "$sr")" "${brpsid:-不明}" "$exp"
      else
        printf "  配布ルール    : %s (サーバ・BR とも実測。PSID=%s)\n" "$(rule_jp "$sr")" "$brpsid"
      fi
    else
      printf "  配布ルール    : サーバ=%s / BR=%s\n" "$(rule_jp "$sr")" "$(rule_jp "$brkind")"
    fi
  fi
  printf "  障害の注入    : %s\n" "${fault:-なし}"
  echo "----------------------------------------------------------------"
  printf "  受講者が見るべき出口アドレス : %s\n" "$(expected_src4)"
  echo
  echo "  受講者は CPE 配下でこれを打ちます:"
  echo "      curl http://203.0.113.80/"
  echo "  src: の行が上の値になっていれば、意図した経路を通っています。"
  echo "================================================================"
  echo
}

case "${1:-status}" in

  status)
    detect
    banner
    ;;

  ra|pd)
    need NGN "NGN-SIM"
    echo "[lab-mode] NGN-SIM を $1 方式に切り替えます..."
    # **Kea は止めてから消す。** 動いたまま消すと、消した直後の Renew で
    # memfile が旧リースを書き戻すことがある (test-matrix R9 が要求する順序)
    rsh "$NGN" "sudo systemctl stop isc-kea-dhcp6-server 2>/dev/null; sudo rm -f /var/lib/kea/kea-leases6.csv*; sudo ./ipoe/ngn/setup-ngn.sh $1" \
      || die "NGN-SIM の切り替えに失敗しました"
    state_set v6mode "$1"
    echo
    echo "  → 切り替えました。**受講者に CPE の再接続を指示してください。**"
    echo "       OpenWrt : ifdown wan6 && ifup wan6"
    echo "       892FJ   : conf t → interface GigabitEthernet0 → shutdown / no shutdown"
    # **MAP-E 中に IPv6 の配り方を変えたら BR も張り直しが要る。**
    # CE のプレフィックスが変われば MAP アドレスも変わるので、BR のトンネル
    # 終点が古いままだと IPv4 が全断する (バナーは期待値を出し続けるので気づけない)
    if [ "$(state_get ipv4mode)" = "mape" ]; then
      echo
      echo "  ⚠ いまは MAP-E です。**CE のアドレスが変わるので BR を張り直してください:**"
      echo "       ./lab-mode.sh mape"
    fi
    banner
    ;;

  mape)
    need VNE "VNE"
    # **BR のトンネル終点は NGN-SIM の方式で変わる** (build.md §3 の表)。
    #   pd → CE=2001:db8:100a:500:0:c633:640a:5 / 共有 IPv4=198.51.100.10 (既定値)
    #   ra → CE=2001:db8:1014:300:0:c633:6414:3 / 共有 IPv4=198.51.100.20
    # 既定値のまま RA 方式で起動すると、案内だけ出て IPv4 は絶対に通らない
    #
    # **ここの値は RFC 7597 の並び (0000:IPv4:PSID) で、OpenWrt CE 向け。**
    # Cisco を draft-ietf-softwire-map-03 で動かすと **並びが 1 バイトずれる**ので、
    # 実機 Cisco を CE にするときはこのコマンドではなく `prov rule` を使うこと
    # (そちらは draft-03 の値を渡し、入口検査のポート集合も合わせる)。
    detect
    # 入口検査の PSID も方式に合わせて明示的に渡す (共有IP: RA=3 / PD=5, PSID長 8 / オフセット 4)。
    # アドレスは RFC7597 だが、enforce はアドレスから抽出せず CE_PSID を使うので整合する。
    if [ "$(state_get v6mode)" = "ra" ]; then
      map_env="CE_MAP_ADDR=2001:db8:1014:300:0:c633:6414:3 CE_SHARED_V4=198.51.100.20 CE_PSID=3 CE_PSID_LEN=8 CE_PSID_OFFSET=4 "
      echo "[lab-mode] IPv4 の運び方を MAP-E にします (RA 方式用のパラメータで起動)..."
    else
      map_env="CE_PSID=5 CE_PSID_LEN=8 CE_PSID_OFFSET=4 "
      echo "[lab-mode] IPv4 の運び方を MAP-E にします (PD 方式用のパラメータで起動)..."
    fi
    # **mape は shared 前提で BR を張る。**もしルール配布サーバが fixed を配ったまま
    # だと、サーバ (fixed) と BR (shared) が食い違って CE が全断する (監査 I3)。
    rsh "$VNE" "sudo ./ipoe/vne/setup-aftr.sh stop 2>/dev/null; sudo ${map_env}./ipoe/vne/setup-map-br.sh" \
      || die "MAP-E BR の起動に失敗しました"
    state_set ipv4mode mape
    echo
    # **ルール状態の記帳はしない。status が表示時に実測する** (server_rule のコメント参照)。
    # サーバとの整合は毎回冪等に取りにいく。破壊的変更の告知は「実測した現在値」に基づく
    # (記録に基づく告知は、実行しない操作を告知する嘘を生んだ: 監査 R6 #3)。
    if [ -n "${INET:-}" ]; then
      # **読めなかったときも告知する。**「fixed のときだけ告知」だと、読みが失敗した
      # ときに告知が消えたまま次の rsh が上書きに成功しうる = 告知が最も必要な場面で
      # 外れる向きに倒れる (監査 R7 #6)。安全側 = 分からなければ告知する。
      case "$(server_rule)" in
        shared) ;;                       # 上書きしても失うものが無い
        fixed)
          echo "  ⚠ サーバは現在 固定IP ルールを配っています。"
          echo "     **shared テンプレートで上書きします** (prov rule fixed のカスタム値は失われます)。" ;;
        *)
          echo "  ⚠ サーバの現在のルールを確認できませんでした。"
          echo "     **これから shared テンプレートで上書きします** (固定IP を配っていた場合、その値は失われます)。" ;;
      esac
      # RULE_IF_BUILT=1: 未構築なら「差し替え不要」で正常終了してよい文脈 (冪等 reconcile)
      rsh "$INET" "sudo RULE_IF_BUILT=1 ./ipoe/inet/setup-ruleserver.sh rule shared" \
        || echo "  ⚠ サーバを shared に揃えられませんでした。下の status の実測を確認してください。"
    else
      echo "  ※ INET 未設定のため、ルール配布サーバの状態は確認・変更していません。"
    fi
    echo "  ※ この経路は shared (240 ポート) 前提です。Cisco + ルール配布サーバを"
    echo "     使うなら ./lab-mode.sh prov rule を使ってください。"
    echo
    echo "  → **受講者に CPE 側を MAP-E に設定させてください。**"
    echo "     CPE に入れる値は build.md §3 の表のとおりです (方式ごとに違います)。"
    echo
    echo "  参考: **本番の CPE はこの値を手で入れません。**ルール配布サーバから取得します。"
    echo "        その経路を試すときは:  ./lab-mode.sh prov on"
    banner
    ;;

  prov)
    # MAP-E のルール配布サーバ (HB46PP = 国内標準プロビジョニング方式) の操作。
    # **本番の CPE はルールを手で設定されない。**サーバから取得する。
    # ラボにこれが無かったため、長らく本番に無い「手書き BMR」経路だけを検証していた。
    need INET "INET-SIM"
    case "${2:-status}" in
      on|https|http)
        scheme="https"; [ "$2" = "http" ] && scheme="http"
        echo "[lab-mode] ルール配布サーバを起動します (TXT は ${scheme} を案内)..."
        # **構築はルールを共有IP テンプレートに初期化する** (setup-ruleserver.sh の仕様)。
        # 直前に fixed を配っていたかどうかの記帳・追随はしない —
        # status が配布 JSON と BR マーカーを実測して一致/不一致を表示する
        # (部分失敗しても実測なので嘘にならない。監査 R5 #2 / R6 #1 の解)。
        rsh "$INET" "sudo ./ipoe/inet/setup-ruleserver.sh ${scheme}" \
          || die "ルール配布サーバの起動に失敗しました (status の実測で現状を確認できます)"
        echo
        echo "  ※ 構築によりルールは **共有IP テンプレートに初期化**されています。"
        echo "     固定IP を配っていた場合は ./lab-mode.sh prov rule fixed で入れ直してください。"
        echo
        echo "  → CPE は 4over6.info の DNS TXT でサーバを発見します。"
        echo "     ルータ側の手順は docs/ipoe-lab/mape-provisioning.md §3"
        ;;
      off|stop)
        rsh "$INET" "sudo ./ipoe/inet/setup-ruleserver.sh stop" \
          || die "ルール配布サーバの停止に失敗しました"
        ;;
      log)
        # CPE が何を要求してきたかを見る。切り分けはここが起点になる
        rsh "$INET" "sudo tail -n 200 -f /var/log/mape-ruleserver.log"
        ;;
      status)
        rsh "$INET" "./ipoe/inet/setup-ruleserver.sh status"
        ;;
      ca)
        rsh "$INET" "./ipoe/inet/setup-ruleserver.sh ca"
        ;;
      rule)
        # jp01 で配るルールを 共有IP / 固定IP1相当 で切り替える。
        # **IPv4 は変わらないが PSID が変わるので CE の MAP アドレスが変わる。**
        # ラボの BR は終点を静的に持つので、ここで一緒に張り替える。
        # 張り替えを忘れると「ルールは新しくなったのに IPv4 が全断」になり、
        # バナーは期待値を出し続けるので気づけない (サイクル 12 で踏んだのと同じ形)。
        need VNE "VNE"
        detect
        case "${3:-}" in shared|fixed) ;; *)
          die "prov rule のあとは shared / fixed です" ;; esac
        # 委譲プレフィックス × ルール で決まる CE の MAP アドレス (draft-03 の並び)。
        # 値の出どころは lab/ipoe/ce/hb46pp-client.py の計算 (--selftest で照合できる)。
        #
        # **MAP アドレスの前半は End-user プレフィックス** (ルールの ipv6PrefixLength
        # + eaBitLength)。**委譲された /64 ではない。**
        # 固定IP のルールは委譲プレフィックスと同じ長さ (/64 or /56) を名指しするので、
        # End-user プレフィックス = 委譲プレフィックスになり、両者は一致する。
        # 共有IP のルールは /40 + 16 = /56 で、RA の /64 とは偶然一致しているだけ。
        # ここを取り違えて BR を張ると、CE は送っているのに戻りが 0 になる
        # (サイクル 13 で実際に踏んだ)。
        # PSID も明示的に渡す (shared: RA=3 / PD=5, fixed: 0)。
        # **アドレスから抽出させない (監査 I3。抽出はレイアウト依存で誤る)。**
        if [ "$(state_get v6mode)" = "ra" ]; then
          v4="198.51.100.20"; ceprefix="2001:db8:1014:300::/64"
          case "$3" in
            shared) ce="2001:db8:1014:300:c6:3364:1400:300"; psid=3 ;;
            fixed)  ce="2001:db8:1014:300:c6:3364:1400:0";   psid=0 ;;
          esac
        else
          v4="198.51.100.10"; ceprefix="2001:db8:100a:500::/56"
          case "$3" in
            shared) ce="2001:db8:100a:500:c6:3364:a00:500"; psid=5 ;;
            fixed)  ce="2001:db8:100a:500:c6:3364:a00:0";   psid=0 ;;
          esac
        fi
        # 固定IP は「その顧客の委譲プレフィックスと IPv4」を名指しするルールなので、
        # モードに応じた値を渡す (共有IP のルールは CE に依存しないので渡さない)
        # **入口検査のポート集合もルールに合わせて渡す。**
        # ここがズレると、正しい CE の通信を BR が落として
        # 「原因の分からない断続失敗」になる (自分で作った罠を自分で踏む形)
        # **ルール状態の記帳はしない** — 部分失敗しても status が配布 JSON と
        # BR マーカーを実測して一致/不一致を表示する (監査 R3〜R6 の教訓)。
        # die の文言も「再実行で解消」とは約束しない — 原因がサーバ未構築なら
        # 再実行しても直らない (R6 #4)。実測 status に誘導する。
        if [ "$3" = "fixed" ]; then
          rsh "$INET" "sudo ./ipoe/inet/setup-ruleserver.sh rule fixed ${ceprefix} ${v4}" \
            || die "ルールの差し替えに失敗しました (上のエラーが原因。./lab-mode.sh status で実態を確認)"
          enf="CE_PSID=${psid} CE_PSID_LEN=0 CE_PSID_OFFSET=6"     # share-ratio 1
        else
          rsh "$INET" "sudo ./ipoe/inet/setup-ruleserver.sh rule shared" \
            || die "ルールの差し替えに失敗しました (上のエラーが原因。./lab-mode.sh status で実態を確認)"
          enf="CE_PSID=${psid} CE_PSID_LEN=8 CE_PSID_OFFSET=4"     # ea-len 16 → 240 ポート
        fi
        echo "[lab-mode] BR を新しい CE アドレスに張り替えます: ${ce}"
        # **prov rule は MAP-E 前提の経路。**mape と同じく AFTR を止め、モードも揃える。
        # 止めないと dslite 中に打ったとき AFTR と MAP BR が同居して経路が汚れる (R6 #5)
        rsh "$VNE" "sudo ./ipoe/vne/setup-aftr.sh stop 2>/dev/null; sudo CE_MAP_ADDR=${ce} CE_SHARED_V4=${v4} ${enf} ./ipoe/vne/setup-map-br.sh" \
          || die "BR の張り替えに失敗しました (サーバは ${3} に切替済みの可能性。./lab-mode.sh status で実態を確認)"
        state_set ipv4mode mape
        echo
        case "$3" in
          shared) echo "  → 共有IP (256 分割 / 240 ポート) を配ります" ;;
          fixed)  echo "  → 固定IP1 相当 (分割なし / 全ポート) を配ります"
                  echo "     ⚠ この設定は実機で未検証です (2026-08-15 時点)" ;;
        esac
        echo "  CPE が取り直すまで最大 8 分。すぐ試すならルータ側で:"
        echo "      delete /force bootflash:/mape/mape-rule.json"
        echo "      conf t → interface <WAN> → shutdown → no shutdown → end"
        ;;
      both|mape|dslite)
        # 配る方式を絞る。**MAP-E で CPE が落ちるときの切り分けに使う。**
        # dslite だけを配って正常に動けば、プロビジョニングの仕組み自体は
        # 生きていて、問題は MAP-E のデータパスにあると分離できる
        rsh "$INET" "sudo ./ipoe/inet/setup-ruleserver.sh response ${2}" \
          || die "配布方式の切り替えに失敗しました"
        ;;
      *)
        die "prov のサブコマンドは on / off / status / log / ca / rule / both / mape / dslite です"
        ;;
    esac
    ;;

  dslite)
    need VNE "VNE"
    local_ce="${2:-}"
    [ -n "$local_ce" ] || die "CE の WAN IPv6 アドレスが要ります: ./lab-mode.sh dslite 2001:db8:...
  **RA 方式のアドレスは EUI-64 で決まるので事前には分かりません。**
  受講者に CPE で確認させてから渡してください:
      OpenWrt : ip -6 addr show dev <WAN>
      892FJ   : show ipv6 interface GigabitEthernet0"
    echo "[lab-mode] IPv4 の運び方を DS-Lite にします (BR は止めます)..."
    rsh "$VNE" "sudo ./ipoe/vne/setup-map-br.sh stop 2>/dev/null; sudo CE_WAN6='$local_ce' ./ipoe/vne/setup-aftr.sh" \
      || die "AFTR の起動に失敗しました"
    state_set ipv4mode dslite
    echo
    echo "  → **受講者に CPE 側を DS-Lite に設定させてください。**"
    banner
    ;;

  break)
    case "${2:-}" in
      mtu)
        need VNE "VNE"
        echo "[lab-mode] MTU ブラックホールを注入します..."
        rsh "$VNE" "sudo ./ipoe/vne/setup-aftr.sh break-pmtu" || die "注入に失敗しました"
        state_set fault mtu
        echo
        echo "  ⚠ **これだけでは再現しません。**あと 2 つ要ります (実走で確定):"
        echo "     ① CPE の MSS clamp を切る"
        echo "        OpenWrt: uci set firewall.@zone[1].mtu_fix='0'; uci commit firewall; /etc/init.d/firewall reload"
        echo "     ② 両端で PMTU キャッシュを消す"
        echo "        クライアントと INET-SIM で: sudo ip route flush cache"
        echo
        echo "  **「①②をやる前は PASS する」ところを先に見せてください。**そこが演習の肝です。"
        ;;
      dns)
        need INET "INET-SIM"
        echo "[lab-mode] IPv6 だけ死んだサイトを作ります..."
        rsh "$INET" "sudo ./ipoe/inet/setup-inet.sh break-v6" || die "注入に失敗しました"
        state_set fault dns
        echo
        echo "  → 受講者に **curl と wget の両方**を叩かせてください。症状が違います:"
        echo "       curl … 207ms 程度。体感できません"
        echo "       wget … 15 秒でタイムアウト。完全にハングします"
        ;;
      *)
        die "break の対象は mtu か dns です" ;;
    esac
    banner
    ;;

  restore)
    echo "[lab-mode] 注入した障害を戻します..."
    # **戻せたかどうかを必ず確かめる。**
    # 昔はここで終了コードを捨てていたので、SSH が届かなくても「障害の注入: なし」と
    # 表示され、実機には drop ルールが残ったままになった。次の演習が原因不明で FAIL する
    restore_ng=""
    if [ -n "$VNE" ]; then
      rsh "$VNE" "sudo ./ipoe/vne/setup-aftr.sh restore-pmtu" || restore_ng="${restore_ng} VNE"
    fi
    if [ -n "$INET" ]; then
      rsh "$INET" "sudo ./ipoe/inet/setup-inet.sh restore" || restore_ng="${restore_ng} INET-SIM"
    fi
    if [ -n "$restore_ng" ]; then
      echo
      echo "  ⚠ **戻しに失敗しました:${restore_ng}**"
      echo "     障害は入ったままです。状態も『戻していない』ままにします。"
      echo "     SSH が届くか確認して、もう一度 ./lab-mode.sh restore を実行してください。"
      banner
      exit 1
    fi
    state_set fault ""
    echo
    echo "  → **CPE 側の戻しは受講者にやらせてください。**戻し忘れが次の演習を壊します:"
    echo "       OpenWrt: uci set firewall.@zone[1].mtu_fix='1'; uci commit firewall; /etc/init.d/firewall reload"
    echo
    echo "  戻ったことの確認 (クライアントで):"
    echo "       SKIP_V6=1 EXPECT_SRC4=$(expected_src4) ./ipoe/tests/run-checks.sh"
    banner
    ;;

  -h|--help|help)
    # ヘッダのコメントをそのまま usage として出す。
    # 行数を直書きすると、ヘッダを 1 行足しただけで末尾が切れる (実際に切れた)。
    # `set -u` の手前までを出す形にして、ヘッダの増減に追従させる。
    sed -n '2,/^set -u/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
    ;;

  *)
    die "不明なモード: $1  (./lab-mode.sh --help)" ;;
esac
