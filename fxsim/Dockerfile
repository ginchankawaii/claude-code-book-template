# FX/株の「頭脳」(Python) をクリーンなコンテナに隔離する。
# MT5本体(EA)はWindowsネイティブのまま。コンテナはMT5の共有フォルダ越しに通信する。
FROM python:3.12-slim

WORKDIR /app

# 依存だけ先に入れてレイヤキャッシュを効かせる。constraints.txt で間接依存まで
# 固定する（再ビルドで中身が変わらない＝テスト済みの組み合わせ。Round-10B）
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# コードを同梱（compose では ./:/app のマウントが優先され、git pull が即反映される）。
# .env（APIキー・パスワード）は .dockerignore で除外：実行時はマウントと env_file から読む
COPY . .

EXPOSE 8000
CMD ["python", "-m", "app.server"]
