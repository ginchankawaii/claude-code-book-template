# FX/株の「頭脳」(Python) をクリーンなコンテナに隔離する。
# MT5本体(EA)はWindowsネイティブのまま。コンテナはMT5の共有フォルダ越しに通信する。
FROM python:3.12-slim

WORKDIR /app

# 依存だけ先に入れてレイヤキャッシュを効かせる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# コードを同梱（compose では ./:/app のマウントが優先され、git pull が即反映される）
COPY . .

EXPOSE 8000
CMD ["python", "-m", "app.server"]
