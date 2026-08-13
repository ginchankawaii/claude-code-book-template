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
    t="$(rsh "$VNE" "ip -6 tunnel show 2>/dev/null | cut -d: -f1" 2>/dev/null || true)"
    case "$t" in
      *dslite0*) state_set ipv4mode dslite ;;
      *map0*)    state_set ipv4mode mape ;;
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
    detect
    map_env=""
    if [ "$(state_get v6mode)" = "ra" ]; then
      map_env="CE_MAP_ADDR=2001:db8:1014:300:0:c633:6414:3 CE_SHARED_V4=198.51.100.20 "
      echo "[lab-mode] IPv4 の運び方を MAP-E にします (RA 方式用のパラメータで起動)..."
    else
      echo "[lab-mode] IPv4 の運び方を MAP-E にします (PD 方式用のパラメータで起動)..."
    fi
    rsh "$VNE" "sudo ./ipoe/vne/setup-aftr.sh stop 2>/dev/null; sudo ${map_env}./ipoe/vne/setup-map-br.sh" \
      || die "MAP-E BR の起動に失敗しました"
    state_set ipv4mode mape
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
      on|https)
        echo "[lab-mode] ルール配布サーバを起動します (TXT は HTTPS を案内)..."
        rsh "$INET" "sudo ./ipoe/inet/setup-ruleserver.sh https" \
          || die "ルール配布サーバの起動に失敗しました"
        echo
        echo "  → CPE は 4over6.info の DNS TXT でサーバを発見します。"
        echo "     ルータ側の手順は docs/ipoe-lab/mape-provisioning.md §3"
        ;;
      http)
        echo "[lab-mode] ルール配布サーバを起動します (TXT は HTTP を案内)..."
        rsh "$INET" "sudo ./ipoe/inet/setup-ruleserver.sh http" \
          || die "ルール配布サーバの起動に失敗しました"
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
      *)
        die "prov のサブコマンドは on / off / status / log / ca です"
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
