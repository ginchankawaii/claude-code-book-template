# voice-logger — コンテナイメージ (Phase 0 パイプライン + Phase 1 ingest API)
#
# ホストに Python も依存ライブラリも入れずに動かすための最小イメージ。
# GPU は使わない前提 (Surface 等の iGPU 機)。faster-whisper は PyAV の wheel が
# FFmpeg を同梱するため、apt での追加パッケージは不要。
FROM python:3.11-slim

# whisper モデルのダウンロード先を固定 (compose で named volume を当てて再DLを防ぐ)
ENV HF_HOME=/cache \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# 設定はコンテナ内 /app/config.toml を読む (compose がバインドマウントする)
ENTRYPOINT ["voice-logger"]
CMD ["watch"]
