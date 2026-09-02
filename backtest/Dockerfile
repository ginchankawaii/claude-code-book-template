FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dev]"

COPY config.yaml ./
COPY tests ./tests

# データと結果はホストからマウントする（docker-compose.yml 参照）
VOLUME ["/app/data", "/app/results"]

ENTRYPOINT ["erb"]
CMD ["--help"]
