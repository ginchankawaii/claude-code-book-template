#!/bin/bash
# VNE: MAP-E BR 模擬 (Ubuntu 24.04)
#   単一テスト CE 向けの静的 ip6tnl で BR を再現する。
#   CE 側が共有 IPv4 + 制限ポートで NAT する前提なので BR では NAT しない。
#   NIC: eth1=PG-CORE, eth2=PG-INET
#
# MAP ルール (CPE に設定する値):
#   rule-ipv6-prefix 2001:db8:1000::/40 / rule-ipv4-prefix 198.51.100.0/24
#   ea-len 16 / psid-offset 4
# モード別の既定値 (NGN-SIM の配布プレフィックスと整合):
#   PD 方式 (/56 = 2001:db8:100a:500::/56): IPv4=198.51.100.10, PSID=5 → そのまま実行
#   RA 方式 (/64 = 2001:db8:1014:300::/64): IPv4=198.51.100.20, PSID=3 →
#     CE_MAP_ADDR=2001:db8:1014:300:0:c633:6414:3 CE_SHARED_V4=198.51.100.20 $0
#
# **入口検査 (map-enforce) について**
#   実 BR は「共有 IPv4 の、割り当て外のポートから来た通信」を落とす。
#   ラボの BR がこれをやらないと **何でも通ってしまい**、CE 側の導出誤りや
#   ポート集合を守らない実装が **顕在化しないまま PASS する**。
#   「ラボで PASS したのに現場で弾かれる」は、この甘さが原因で起きる。
#   なので **既定で ON** にしてある。切るときは MAP_ENFORCE=0。
#
#   落とした通信は nft のログに出る (dmesg / journalctl -k で見える):
#     MAP-ENFORCE-DROP: ...
#   **MAP-E が繋がらないときは、まずここを見ること。**割当外ポートを使っていれば
#   ここに出る。出ていなければ入口検査以外が原因。
#
#   ポート集合は PSID / PSID長 / オフセットで決まる。**PSID はアドレスから
#   抽出せず、CE_PSID で明示的に渡す** (アドレスの並びが 2 種類あり抽出は誤るため)。
#   既定は共有IP のルール (PSID 5 / PSID長 8 / オフセット 4 → 15 レンジ x 16 = 240)。
#     RA 共有: CE_PSID=3 CE_PSID_LEN=8 CE_PSID_OFFSET=4
#     固定IP (share-ratio 1): CE_PSID=0 CE_PSID_LEN=0 CE_PSID_OFFSET=6
#   lab-mode.sh (mape / prov rule) はこれらを自動で渡す。
set -euo pipefail

# 役割別 MAC から NIC 名を自動解決 (provision.sh で作った VM 向け。未設定の変数だけ埋める)
if [ -f "$(dirname "$0")/../detect-ifs.sh" ]; then . "$(dirname "$0")/../detect-ifs.sh"; fi

case "${1:-}" in
  stop)
    # DS-Lite だけを検証するときに使う。残すと map0 が旧 CE の MAP アドレス宛のまま
    # 生き続け、共有 IPv4 宛の復路がそちらへ流れて切り分けを汚す
    ip -6 tunnel del map0 2>/dev/null || true
    # **入口検査も必ず消す。**残すと次の検証で「原因の分からない断続失敗」になる
    nft delete table ip map-enforce 2>/dev/null || true
    echo "[VNE] MAP-E BR を停止しました (トンネル・復路・入口検査を削除)"; exit 0 ;;
esac

BR_ADDR="2001:db8:9999::1"
CE_MAP_ADDR="${CE_MAP_ADDR:-2001:db8:100a:500:0:c633:640a:5}"  # RFC7597 IID: 0000:IPv4:PSID
CE_SHARED_V4="${CE_SHARED_V4:-198.51.100.10}"
MAP_ENFORCE="${MAP_ENFORCE:-1}"          # 入口検査。実 BR に合わせて既定 ON
# **PSID はアドレスから抽出しない。呼び出し側が明示的に渡す。**
# 以前は CE_MAP_ADDR のバイト位置から取り出していたが、アドレスには 2 つの並びがあり
# (OpenWrt=RFC7597: 0000:IPv4:PSID / Cisco=draft-03: 00:IPv4:PSID:00)、
# 抽出は必ずどちらかで PSID を誤り、**BR が CE の割当ポートを自分で落とす**。
# 監査 (サイクル 15) で実測: PD 既定 (RFC7597) で enforce が PSID 5 を 2560 と誤り、
# 割当内ポートと交差ゼロ → サイレント全断。
# 既定 5 は既定 CE_MAP_ADDR (PD RFC7597, PSID 5) と整合させてある。
CE_PSID="${CE_PSID:-5}"
CE_PSID_LEN="${CE_PSID_LEN:-8}"          # 共有IP のルール (ea-len 16 - IPv4サフィックス 8)
CE_PSID_OFFSET="${CE_PSID_OFFSET:-4}"    # 同上。固定IP のときは 0 / 6 を渡すこと
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

ip -6 addr replace ${CORE_SELF} dev "${CORE_IF}"
ip addr replace ${INET_SELF} dev "${INET_IF}"
ip -6 addr replace ${INET_SELF6} dev "${INET_IF}"
ip link set "${CORE_IF}" up; ip link set "${INET_IF}" up

# BR アドレスと、ユーザプレフィックス帯の復路 (NGN 経由)
ip -6 addr replace ${BR_ADDR}/128 dev lo
ip -6 route replace 2001:db8:1000::/40 via ${CORE_NGN}

# ── 転送を先に落としてから、入口検査 → トンネルの順で組む (fail-closed) ──
# 実 BR は「共有 IPv4 の、割り当て外のポートから来た通信」を落とす。
# ラボがこれをやらないと、CE 側の導出誤りやポート集合を守らない実装が
# **顕在化しないまま PASS する**。それが「ラボで PASS → 現場で弾かれる」の正体。
#
# **順序 = fail-closed の要。**監査 (サイクル 15, I2) で fail-open を 2 経路で確認した。
#   (1) まず map0 を消す      … 再構成中は転送経路が無い
#   (2) 次に enforce を組む    … 計算/nft が失敗したら set -e でここで死ぬ
#   (3) 最後に map0 を作る      … enforce が通ったときだけ転送が復活する
#   こうすると「enforce 無しでトンネルだけ生きている」窓が生じない。
#   **初回だけでなく再実行でも fail-closed。**(1) を (2) より先に置くのがその肝。
#   古い順序 (トンネル→enforce) や、enforce削除→計算失敗→古いmap0が残る、はどちらも
#   BR 全開を残す。iifname は文字列一致なので map0 未作成でも enforce は投入できる。
modprobe ip6_tunnel
ip -6 tunnel del map0 2>/dev/null || true          # (1) 転送を先に落とす
nft delete table ip map-enforce 2>/dev/null || true
if [ "${MAP_ENFORCE}" = "1" ]; then
  # ポート集合は RFC 7597 5.1:
  #   a=オフセット, p=PSID長, m=16-a-p
  #   各 j (1..2^a-1) について (j << (16-a)) | (PSID << m) から 2^m 個
  #   j=0 を外すのは、その範囲にウェルノウンポートが入るため
  # **PSID は CE_PSID をそのまま使う (アドレスから抽出しない)。**
  ENF_RULES="$(python3 - "${CE_PSID}" "${CE_PSID_LEN}" "${CE_PSID_OFFSET}" <<'PY'
import sys
psid, p, a = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
if p == 0:
    psid = 0                        # share-ratio 1 のときは PSID を持たない
m = 16 - a - p
if m < 0:
    sys.exit("psid_offset(%d) + psid_len(%d) が 16 を超えています" % (a, p))
rng = []
for j in range(0 if a == 0 else 1, 1 << a):
    s = (j << (16 - a)) | (psid << m)
    hi = s + (1 << m) - 1
    # **16 ビットに収まらない値は必ず弾く。**nft は 65535 超のポートを拒否するが、
    # ここで先に落とせば「なぜ BR が上がらないか」が読める形で出る。
    if s < 0 or hi > 65535:
        sys.exit("計算したポート %d-%d が 16 ビットを超えます "
                 "(PSID=%d offset=%d len=%d)。CE_PSID/LEN/OFFSET が不整合です"
                 % (s, hi, psid, a, p))
    rng.append("%d-%d" % (s, hi))
print("PSID=%d" % psid)
print("PORTS=%d" % (len(rng) * (1 << m)))
print("SET=%s" % ", ".join(rng))
PY
)"
  # ↑ この $() が失敗すると set -e でここで死ぬ。トンネルはまだ無いので fail-closed。
  ENF_PSID="$(printf '%s\n' "${ENF_RULES}" | sed -n 's/^PSID=//p')"
  ENF_PORTS="$(printf '%s\n' "${ENF_RULES}" | sed -n 's/^PORTS=//p')"
  ENF_SET="$(printf '%s\n' "${ENF_RULES}" | sed -n 's/^SET=//p')"

  # 許可を先に置き、最後に「共有 IPv4 からのそれ以外」を落とす。
  # ICMP はポートを持たない (識別子で分ける) ため、ここでは検査しない。
  # 実 BR は ICMP 識別子も見るが、ラボでは切り分けを濁らせるほうが害が大きい。
  nft -f - <<EOF
table ip map-enforce {
  chain check {
    # **チェーン名に fwd は使えない。**nft の予約語 (fwd ステートメント) と衝突して
    # 「syntax error, unexpected fwd」になる
    type filter hook forward priority -10;
    iifname "map0" ip saddr ${CE_SHARED_V4} tcp sport { ${ENF_SET} } accept
    iifname "map0" ip saddr ${CE_SHARED_V4} udp sport { ${ENF_SET} } accept
    iifname "map0" ip saddr ${CE_SHARED_V4} meta l4proto icmp accept
    iifname "map0" ip saddr ${CE_SHARED_V4} log prefix "MAP-ENFORCE-DROP: " drop
  }
}
EOF
fi

# ── (3) MAP-E トンネルを作る。enforce が通ったときだけここに到達する ──
# IPv4-in-IPv6 なので mode は ipip6。inner IPv4 MTU 1460
ip -6 tunnel add map0 mode ipip6 local ${BR_ADDR} remote ${CE_MAP_ADDR} encaplimit none
ip link set map0 up mtu 1460
ip route replace ${CE_SHARED_V4}/32 dev map0   # 共有 IPv4 宛の復路をトンネルへ

echo "[VNE] MAP-E BR 起動: BR=${BR_ADDR}, CE=${CE_MAP_ADDR}, 共有IPv4=${CE_SHARED_V4}"
echo "      CE のアドレスが異なる場合: CE_MAP_ADDR=<addr> $0 で再実行"
if [ "${MAP_ENFORCE}" = "1" ]; then
  echo "      入口検査: 有効 (PSID=${ENF_PSID} / 許可ポート ${ENF_PORTS} 個。トンネルより先に張る fail-closed)"
  echo "        割当外から来た通信は落として dmesg に MAP-ENFORCE-DROP を出します"
  echo "        **MAP-E が通らないときは journalctl -k | grep MAP-ENFORCE を先に見ること**"
  echo "        切るとき: MAP_ENFORCE=0 $0"
else
  echo "      入口検査: **無効** (実 BR より甘い状態です。CE の誤りを見逃します)"
fi
