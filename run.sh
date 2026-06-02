#!/usr/bin/env bash
# 投資シミュレーターを起動するスクリプト
set -euo pipefail

cd "$(dirname "$0")"

# 仮想環境が無ければ作成
if [ ! -d ".venv" ]; then
  echo "==> 仮想環境を作成します (.venv)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> 依存関係をインストールします"
pip install -q -r requirements.txt

echo "==> サーバを起動します: http://127.0.0.1:8000"
exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
