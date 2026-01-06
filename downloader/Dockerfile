FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ffmpeg tini \
    && rm -rf /var/lib/apt/lists/*

COPY downloader/requirements.txt /tmp/requirements.txt
RUN pip install uv && uv pip install --system -r /tmp/requirements.txt

COPY packages/__init__.py /app/packages/__init__.py
COPY packages/logging_config.py /app/packages/logging_config.py
COPY downloader /app/downloader

EXPOSE 8082

# healthcheck ждёт /health
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=5 \
  CMD curl -fsS http://localhost:8082/health || exit 1

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["uvicorn", "downloader.main:app", "--host", "0.0.0.0", "--port", "8082"]
