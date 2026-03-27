FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY main.py scheduler.py exporter.py ./

RUN useradd -m -u 1000 tekken && chown -R tekken:tekken /app
USER tekken

HEALTHCHECK --interval=1h --timeout=10s --retries=2 \
  CMD python -c "import sqlite3,os; sqlite3.connect(os.environ.get('DB_PATH','data/battles.db')).close()" || exit 1

CMD ["python", "scheduler.py"]
