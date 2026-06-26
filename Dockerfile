# keiba 分析層(解析専用)コンテナ。
# JV-Link(取得)は Windows 専用 COM のためここには含まない。
# 取得層(jrvltsql 等)が作った keiba.db をマウントして解析する。
FROM python:3.11-slim

# LightGBM の実行に必要(OpenMP ランタイム)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存解決を先に(レイヤキャッシュ)
COPY pyproject.toml README.md requirements.txt ./
COPY keiba ./keiba
COPY horse_racing ./horse_racing
RUN pip install --no-cache-dir -e .

# data/plots はマウントポイント
VOLUME ["/data", "/app/plots"]

# `docker run <img> --db /data/keiba.db` のように引数を渡せる
ENTRYPOINT ["python", "-m", "keiba"]
# 引数なしなら合成データのデモ
CMD ["--days", "360", "--quiet"]
