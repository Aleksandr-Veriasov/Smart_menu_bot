FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# базовые утилиты и init-процесс
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl tini \
 && rm -rf /var/lib/apt/lists/*

# 1) зависимости (кэш слоя)
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install uv && uv pip install --system -r /tmp/requirements.txt

# 2) только нужный код
COPY packages /app/packages
COPY backend  /app/backend

EXPOSE 8000

# healthcheck ждёт /ping
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8000/ping || exit 1

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["uvicorn","backend.app.main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips=*"]
