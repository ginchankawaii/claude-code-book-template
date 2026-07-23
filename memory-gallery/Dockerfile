FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY tests/ tests/

# デフォルトは安全側（書き込みなし）。実行時に上書き可。
CMD ["python", "-m", "src.main", "run", "--dry-run"]
