# voice-logger — コンテナイメージ (Phase 0 パイプライン + Phase 1 ingest API)
#
# ホストに Python も依存ライブラリも入れずに動かすための最小イメージ。
# GPU は使わない前提 (Surface 等の iGPU 機)。faster-whisper は PyAV の wheel が
# FFmpeg を同梱するため、音声まわりの追加パッケージは不要。
FROM python:3.11-slim

# TZ 環境変数 (compose で指定) はゾーン定義ファイルが無いと黙って UTC になる。
# slim イメージに入っていることを当てにせず、明示的に入れておく。
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# whisper モデルのダウンロード先を固定 (compose で named volume を当てて再DLを防ぐ)。
# huggingface_hub の利用統計は送らない。
ENV HF_HOME=/cache \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# 設定はコンテナ内 /app/config.toml を読む (compose がバインドマウントする)
ENTRYPOINT ["voice-logger"]
CMD ["watch"]
