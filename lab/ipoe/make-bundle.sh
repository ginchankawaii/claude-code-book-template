#!/bin/bash
# 会社に持ち込む一式をまとめる (Box 等で共有する想定)。
#
#   usage: ./lab/ipoe/make-bundle.sh [出力先ディレクトリ]
#
# 会社環境では AI が使えず、GitHub にも繋がらない前提です。
# **このバンドルだけを持ち込めば構築できる**状態を目標にしています。
#
# 大きいもの (Ubuntu クラウドイメージ 600MB / OpenWrt 13MB / VM エクスポート数十GB) は
# **含めません**。回線とストレージを食う割に、会社側で取得できることが多いためです。
# 必要なら §注意 の手順で別途持ち込んでください。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="${1:-${REPO_ROOT}/bundle}"
STAMP="$(date +%Y%m%d-%H%M)"
NAME="ipoe-lab-bundle-${STAMP}"
WORK="${OUT_DIR}/${NAME}"

[ -d "${REPO_ROOT}/lab/ipoe" ] || { echo "ERROR: ${REPO_ROOT}/lab/ipoe が見つかりません" >&2; exit 1; }

mkdir -p "${WORK}"
echo "[bundle] ${WORK} に集めます"

# --- 1. スクリプトと設定 (これが本体) ---
rm -rf "${WORK}/lab"          # 同じ分内に再実行したとき lab/lab に入れ子コピーされるのを防ぐ
cp -r "${REPO_ROOT}/lab" "${WORK}/lab"
# 実環境の接続先と状態ファイルは配らない (中身は環境ごとに違うし、持ち出す意味がない)
rm -f "${WORK}/lab/ipoe/lab-hosts.conf" "${WORK}/lab/ipoe/.lab-mode"

# --- 2. 手順書・設計・記録 ---
mkdir -p "${WORK}/docs"
cp -r "${REPO_ROOT}/docs/ipoe-lab" "${WORK}/docs/ipoe-lab"

# --- 3. 版の記録 (どのコミットから作ったか) ---
{
  echo "bundle 作成日時: $(date '+%F %T %Z')"
  if command -v git >/dev/null 2>&1 && git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    echo "コミット: $(git -C "$REPO_ROOT" rev-parse HEAD)"
    echo "ブランチ: $(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
    # --cached も見る。ステージ済みの変更だけだと diff --quiet は 0 を返すため、
    # 「未コミットを含む」警告がすり抜ける (deploy.sh と同じ判定に揃えた)
    if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
      echo "警告: 未コミットの変更を含んだ状態で作成されています"
    fi
  else
    echo "コミット: (git 情報なし)"
  fi
} > "${WORK}/VERSION.txt"

# --- 4. 読む順番の案内 ---
cat > "${WORK}/README.txt" <<'EOF'
IPoE 検証ラボ 持ち込みバンドル

【まずこれを見る】
  docs/ipoe-lab/topology.png        検証ラボ 構成図 (svg 版も同じ場所にあります)
      上の枠が仮想基盤 (VMware/Proxmox の中)、枠の下が物理 (物理スイッチ・
      実機 CPE・検証 PC)。方式ごとにどこを通るかと、出口アドレスも図中にあります。

【まずこれを読む】
  docs/ipoe-lab/runbook-vmware.md
      会社 VMware での構築手順。上から順に実行すれば完成します。
      詰まったら §9 のトラブルシューティング (自宅で実際に踏んだもの) を見てください。

【会社の AI(Copilot 等)に手伝ってもらうとき】
  docs/ipoe-lab/ai-context.md
      これ 1 ファイルをチャットに丸ごと貼ってください。設計・アドレス・
      実際に踏んだトラブルの一覧が入っています。貼ってはいけないもの
      (お客様情報・実 IP・パスワード) の注意も先頭にあります。

【設計を知りたいとき】
  docs/ipoe-lab/README.md           全体設計・アドレス計画・できること/できないこと
  docs/ipoe-lab/build.md            各 VM の構築手順と考え方
  docs/ipoe-lab/test-matrix.md      検証マトリクス・切替シナリオ・トラブル再現レシピ

【なぜそうなっているか知りたいとき】
  docs/ipoe-lab/build-log.md        実走の一次記録。症状と原因が全部ここにあります
  docs/ipoe-lab/research-notes.md   事例調査ノート

【勉強会をやるとき】
  docs/ipoe-lab/study-guide.md      教科書 × ラボ 連動学習ガイド (3回シリーズ)
  docs/ipoe-lab/slides/setsumeikai.md  説明会 1時間版 (座学)。pptx もあります
  docs/ipoe-lab/slides/handson.md      ハンズオン 150分 (触って壊して直す)。pptx もあります
      ※ ハンズオンは講師自身が一度全部やってから使ってください

【スクリプト】
  lab/ipoe/                         各 VM にディレクトリごとコピーして実行します
                                    VM 上のパスは ~/ipoe/... になります

【このバンドルに含まれないもの】
  - Ubuntu Server 24.04 クラウドイメージ (約 600MB)
  - OpenWrt x86/64 イメージ (約 13MB)
  - VM のエクスポート (数十 GB)

  いずれも会社側でダウンロードするか、別途 USB 等で持ち込んでください。
  取得元 URL は docs/ipoe-lab/runbook-vmware.md §0 に記載しています。
EOF

# --- 5. アーカイブ化 ---
( cd "${OUT_DIR}" && tar czf "${NAME}.tar.gz" "${NAME}" )
SIZE="$(du -h "${OUT_DIR}/${NAME}.tar.gz" | cut -f1)"

echo "[bundle] 完成: ${OUT_DIR}/${NAME}.tar.gz (${SIZE})"
echo "         展開後のディレクトリも残してあります: ${WORK}"
echo
echo "会社へは tar.gz を持ち込み、"
echo "  tar xzf ${NAME}.tar.gz"
echo "  cd ${NAME} && cat README.txt"
echo "から始めてください。"
