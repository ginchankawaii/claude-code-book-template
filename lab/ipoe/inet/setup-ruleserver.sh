#!/bin/bash
# INET-SIM: HB46PP プロビジョニングサーバ模擬の構築
#
#   usage: setup-ruleserver.sh            … HTTP で構築 (最初の捕獲向け。既定)
#          setup-ruleserver.sh https      … HTTPS + 証明書検証あり (本番と同じ形)
#          setup-ruleserver.sh stop       … サーバ停止
#          setup-ruleserver.sh status     … 稼働状況と DNS 応答の確認
#          setup-ruleserver.sh log        … 受け取った要求のログを表示
#          setup-ruleserver.sh ca         … ルータに貼る CA 証明書と設定断片を出力
#          setup-ruleserver.sh selftest   … 自分で CPE の振りをして疎通確認
#          setup-ruleserver.sh response {both|mape|dslite}
#                                         … 配る方式を絞る (切り分け用)
#
# **これが何か**
#   本番の MAP-E / DS-Lite では、CPE はルールを手で設定されない。
#   JAIPA「IPv6 マイグレーション技術の国内標準プロビジョニング方式」= HB46PP
#   に従い、CPE が **プロビジョニングサーバから取得する**。
#   Cisco IOS XE ではこれが `nat64 provisioning mode jp01` にあたる。
#   ラボにこのサーバが無かったため、これまでの MAP-E 検証は
#   **本番に存在しない「手書き BMR」経路**を通していた。その是正。
#
#   仕様: https://github.com/v6pc/v6mig-prov/blob/master/spec.md
#
# **構築されるもの**
#   - 2001:db8:cafe::a1 (プロビジョニングサーバ専用アドレス。既存の ::80 web には触らない)
#   - DNS TXT  4over6.info      → "v=v6mig-1 url=... t=a|b"   ← CPE はここから発見する
#   - DNS AAAA prov.lab.example → 2001:db8:cafe::a1
#   - DNS AAAA aftr.lab.example → 2001:db8:8888::1            ← DS-Lite 用
#   - ラボ CA + サーバ証明書 (https モードのみ)
#   - systemd サービス mape-ruleserver
set -euo pipefail

MODE="${1:-http}"

PROV_ADDR="2001:db8:cafe::a1"
PROV_FQDN="prov.lab.example"
# HTTP を 80 にしないのは、**nginx が `listen [::]:80 default_server` で
# ワイルドカード待受しているため**。専用アドレスを足しても IPv6 の 80 番は
# nginx が先に掴んでいて bind できない (Errno 98)。
# 443 は nginx が使っていないので素直に取れる。
# HB46PP の発見用 TXT は URL をそのまま配れるので、ポートが既定でなくても問題ない。
PROV_HTTP_PORT=8080
PROV_HTTPS_PORT=443
AFTR_FQDN="aftr.lab.example"
AFTR_ADDR="2001:db8:8888::1"
ETC="/etc/mape-ruleserver"
CA_DIR="${ETC}/ca"
LOGFILE="/var/log/mape-ruleserver.log"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── 情報系のモードは構築せずに終わる ────────────────────────────────
case "$MODE" in
  stop)
    systemctl stop mape-ruleserver 2>/dev/null || true
    systemctl disable mape-ruleserver 2>/dev/null || true
    echo "[INET-SIM] プロビジョニングサーバを停止しました"
    echo "  DNS の TXT レコードは残っています。消すには:"
    echo "    rm /etc/dnsmasq.d/lab-prov.conf && systemctl restart dnsmasq"
    exit 0 ;;
  status)
    echo "=== サービス ==="
    systemctl --no-pager --lines=0 status mape-ruleserver 2>&1 | head -5 || true
    echo
    echo "=== 待受ポート ==="
    ss -lntp 2>/dev/null | grep -E "ruleserver|:${PROV_HTTP_PORT} |:${PROV_HTTPS_PORT} " || echo "  (なし)"
    echo
    # dnsmasq は bind-dynamic + interface=<INET側> なので **ループバックでは待ち受けていない**。
    # 127.0.0.1 に投げると systemd-resolved に当たって空振りする。必ず INET 側へ投げること。
    echo "=== DNS 応答 (CPE が最初に引くもの) ==="
    dig +short -t TXT 4over6.info @203.0.113.53
    echo "=== ${PROV_FQDN} ==="
    dig +short -t AAAA "${PROV_FQDN}" @203.0.113.53
    echo "=== ${AFTR_FQDN} ==="
    dig +short -t AAAA "${AFTR_FQDN}" @203.0.113.53
    echo
    echo "=== 直近の要求 ==="
    tail -n 20 "${LOGFILE}" 2>/dev/null || echo "  (まだ要求はありません)"
    exit 0 ;;
  log)
    tail -n 200 -f "${LOGFILE}"
    exit 0 ;;
  ca)
    [ -f "${CA_DIR}/ca.pem" ] || { echo "CA がまだありません。先に setup-ruleserver.sh https を実行してください" >&2; exit 1; }
    echo "─────────────────────────────────────────────────────────────"
    echo " ルータ (IOS XE) に貼り付ける CA 証明書"
    echo "─────────────────────────────────────────────────────────────"
    echo "crypto pki trustpoint LAB-PROV-CA"
    echo " enrollment terminal"
    echo " revocation-check none"
    echo "exit"
    echo "crypto pki authenticate LAB-PROV-CA"
    echo "(以下を貼り、最後に quit と入力)"
    echo
    cat "${CA_DIR}/ca.pem"
    echo "quit"
    exit 0 ;;
  selftest)
    URL="$(sed -n 's/^txt-record=4over6.info,v=v6mig-1 url=\([^ ]*\).*/\1/p' /etc/dnsmasq.d/lab-prov.conf)"
    [ -n "$URL" ] || { echo "TXT レコードが見つかりません。先に構築してください" >&2; exit 1; }
    echo "[selftest] TXT から得た URL: ${URL}"
    echo "[selftest] CPE を装って要求します"
    # 実機 CPE が送るのと同じ形のクエリ (仕様の例に準拠)
    Q="vendorid=acde48-lab&product=LAB-SELFTEST&version=1_0&capability=map_e,dslite"
    # この VM 自身の名前解決は systemd-resolved 経由で、ラボの dnsmasq を見ていない。
    # 素で curl すると prov.lab.example が引けずに落ちるので --resolve で固定する。
    # (CPE 側は RA/DHCPv6 で配られたラボ DNS を使うので、この小細工は要らない)
    if [ "${URL#https://}" != "${URL}" ]; then
      curl -sS --cacert "${CA_DIR}/ca.pem" \
        --resolve "${PROV_FQDN}:${PROV_HTTPS_PORT}:[${PROV_ADDR}]" "${URL}?${Q}" && echo
    else
      curl -sS --resolve "${PROV_FQDN}:${PROV_HTTP_PORT}:[${PROV_ADDR}]" "${URL}?${Q}" && echo
    fi
    echo "[selftest] 上に JSON が出ていれば配布経路は成立しています"
    echo "           (配る方式を絞っている場合は map_e が無いこともあります: $0 response both で戻せます)"
    exit 0 ;;
  response)
    # **切り分け用。** MAP-E を配ると CPE が落ちる場合に、DS-Lite だけを配って
    # 「プロビジョニングの仕組み自体は生きているか」を分離して判定できる。
    #   both   … map_e と dslite の両方 (既定)
    #   mape   … map_e だけ
    #   dslite … dslite だけ   ← MAP-E のデータパスを完全に外して試す
    [ "$(id -u)" = "0" ] || { echo "root で実行してください (sudo)" >&2; exit 1; }
    WHICH="${2:-both}"
    case "$WHICH" in both|mape|dslite) ;; *)
      echo "response のあとは both / mape / dslite です" >&2; exit 1 ;; esac
    python3 - "${SRC_DIR}/ruleserver-response.json" "${ETC}/response.json" "$WHICH" <<'PY'
import json, sys
src, dst, which = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src, encoding="utf-8") as f:
    doc = json.load(f)
doc = {k: v for k, v in doc.items() if not k.startswith("_comment")}
if which == "mape":
    doc.pop("dslite", None)
elif which == "dslite":
    doc.pop("map_e", None)
# order は残っている方式だけにする。無い方式を先頭に置くと CPE が迷う
doc["order"] = [m for m in doc.get("order", []) if m in doc]
with open(dst, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("[INET-SIM] 配る方式を %s にしました (order=%s)" % (which, doc["order"]))
PY
    echo "  サーバの再起動は不要です (要求のたびに読み直します)"
    exit 0 ;;
  http|https) ;;
  *)
    echo "不明なモード: ${MODE}" >&2; exit 1 ;;
esac

# ── ここから構築 ────────────────────────────────────────────────────
[ "$(id -u)" = "0" ] || { echo "root で実行してください (sudo)" >&2; exit 1; }

# 役割別 MAC から NIC 名を自動解決 (provision.sh で作った VM 向け)
if [ -f "$(dirname "$0")/../detect-ifs.sh" ]; then . "$(dirname "$0")/../detect-ifs.sh"; fi
INET_IF="${INET_IF:-eth1}"

command -v dnsmasq >/dev/null 2>&1 || {
  echo "dnsmasq がありません。先に setup-inet.sh を実行してください" >&2; exit 1; }
command -v dig >/dev/null 2>&1 || DEBIAN_FRONTEND=noninteractive apt-get install -y dnsutils

mkdir -p "${ETC}" "${CA_DIR}"

# プロビジョニングサーバ専用アドレス。
# 既存の web (2001:db8:cafe::80) と DNS (::53) には触らないため別アドレスにする。
ip -6 addr replace "${PROV_ADDR}/64" dev "${INET_IF}"

# ── 応答 JSON を配置 ────────────────────────────────────────────────
# リポジトリ側のファイルには説明用の "_comment_*" キーが入っている。
# 仕様上 CPE は未知のキーを無視してよいが、実装によっては嫌う可能性があるので
# **配置時に落として、厳密に仕様どおりの JSON にする。**
python3 - "${SRC_DIR}/ruleserver-response.json" "${ETC}/response.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as f:
    doc = json.load(f)
clean = {k: v for k, v in doc.items() if not k.startswith("_comment")}
with open(dst, "w", encoding="utf-8") as f:
    json.dump(clean, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("[INET-SIM] 応答 JSON を配置: %s (説明コメント %d 個を除去)"
      % (dst, len(doc) - len(clean)))
PY

install -m 0755 "${SRC_DIR}/ruleserver.py" /usr/local/sbin/mape-ruleserver

# ── 証明書 ─────────────────────────────────────────────────────────
# **HTTP と HTTPS は常に両方上げる。**
# ルータ側が rule-server に http:// を受け付けるかどうかは公開情報から確定できない。
# 片方だけ上げていると、朝の切り分けでサーバを建て直す羽目になる。
# モード引数は「発見用 TXT がどちらを案内するか」だけを決める。
TXT_T="a"          # a=証明書検証なし / b=検証あり
SCHEME="http"
URL_PORT=":${PROV_HTTP_PORT}"
if [ "$MODE" = "https" ]; then
  SCHEME="https"; TXT_T="b"
  URL_PORT=""   # 443 は https の既定ポートなので URL に書かない
fi
EXEC_PORTS="--port ${PROV_HTTP_PORT} --tls-port ${PROV_HTTPS_PORT}"

if [ ! -f "${CA_DIR}/ca.pem" ]; then
  echo "[INET-SIM] ラボ CA とサーバ証明書を作成します"
  openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout "${CA_DIR}/ca.key" -out "${CA_DIR}/ca.pem" \
    -subj "/C=JP/O=IPoE Lab/CN=IPoE Lab Provisioning CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
  openssl req -newkey rsa:2048 -sha256 -nodes \
    -keyout "${CA_DIR}/server.key" -out "${CA_DIR}/server.csr" \
    -subj "/C=JP/O=IPoE Lab/CN=${PROV_FQDN}" 2>/dev/null
  # SAN には FQDN と リテラル IPv6 の両方を入れる。
  # rule-server に URL を直接書く運用 (DNS を経由しない切り分け) でも
  # 証明書検証が通るようにするため。
  openssl x509 -req -in "${CA_DIR}/server.csr" -sha256 -days 3650 \
    -CA "${CA_DIR}/ca.pem" -CAkey "${CA_DIR}/ca.key" -CAcreateserial \
    -out "${CA_DIR}/server.pem" \
    -extfile <(printf 'subjectAltName=DNS:%s,IP:%s\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' \
               "${PROV_FQDN}" "${PROV_ADDR}") 2>/dev/null
  chmod 600 "${CA_DIR}/ca.key" "${CA_DIR}/server.key"
else
  echo "[INET-SIM] 既存の CA を再利用します (作り直すなら rm -rf ${CA_DIR})"
fi
EXEC_TLS="--cert ${CA_DIR}/server.pem --key ${CA_DIR}/server.key"
chmod 644 "${CA_DIR}/ca.pem"   # ca サブコマンドを一般ユーザでも読めるように

PROV_URL="${SCHEME}://${PROV_FQDN}${URL_PORT}/rule.cgi"

# ── DNS: CPE が最初に引く TXT レコード ─────────────────────────────
# **これが本番の入口。** CPE は 4over6.info の TXT を引いてサーバを発見する。
# dnsmasq は txt-record の値をカンマで分割するので、値にカンマを入れないこと。
cat > /etc/dnsmasq.d/lab-prov.conf <<EOF
# HB46PP (国内標準プロビジョニング方式) の発見用レコード
txt-record=4over6.info,v=v6mig-1 url=${PROV_URL} t=${TXT_T}
address=/${PROV_FQDN}/${PROV_ADDR}
address=/${AFTR_FQDN}/${AFTR_ADDR}
EOF
systemctl restart dnsmasq

# ── systemd ────────────────────────────────────────────────────────
cat > /etc/systemd/system/mape-ruleserver.service <<EOF
[Unit]
Description=HB46PP provisioning server (lab simulation)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/mape-ruleserver --bind ${PROV_ADDR} ${EXEC_PORTS} \\
  --response ${ETC}/response.json --log ${LOGFILE} ${EXEC_TLS}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now mape-ruleserver
systemctl restart mape-ruleserver

sleep 1
systemctl is-active --quiet mape-ruleserver || {
  echo "!! サービスが起動していません。journalctl -u mape-ruleserver -n 30 を確認してください" >&2
  journalctl -u mape-ruleserver -n 20 --no-pager >&2 || true
  exit 1; }

echo
echo "[INET-SIM] HB46PP プロビジョニングサーバを構築しました (TXT は ${MODE} を案内)"
echo "  発見用 TXT : 4over6.info → v=v6mig-1 url=${PROV_URL} t=${TXT_T}"
echo "  待受は両方 : http://${PROV_FQDN}:${PROV_HTTP_PORT}/rule.cgi"
echo "               https://${PROV_FQDN}/rule.cgi"
echo "               (IP 直指定も可: [${PROV_ADDR}] 証明書の SAN に入れてある)"
echo "  応答 JSON  : ${ETC}/response.json  ← 要求のたびに読み直すので編集は即反映"
echo "  ログ       : ${LOGFILE}"
echo
echo "  疎通確認   : $0 selftest"
echo "  要求を見る : $0 log"
if [ "$MODE" = "https" ]; then
  echo "  ルータ用CA : $0 ca"
fi
