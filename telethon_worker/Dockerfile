FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends tini \
    curl && rm -rf /var/lib/apt/lists/*

COPY telethon_worker/requirements.txt /tmp/requirements.txt
RUN pip install uv && uv pip install --system -r /tmp/requirements.txt

COPY packages/__init__.py /app/packages/__init__.py
COPY packages/common_settings/__init__.py /app/packages/common_settings/__init__.py
COPY packages/common_settings/base.py /app/packages/common_settings/base.py
COPY packages/common_settings/telethon_settings.py /app/packages/common_settings/telethon_settings.py
COPY packages/logging_config.py /app/packages/logging_config.py
COPY telethon_worker /app/telethon_worker

EXPOSE 8090

# healthcheck ждёт /health
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=5 \
  CMD curl -fsS http://localhost:8090/health || exit 1

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["uvicorn", "telethon_worker.main:app", "--host", "0.0.0.0", "--port", "8090"]
