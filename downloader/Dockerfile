FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY downloader/requirements.txt /tmp/requirements.txt
RUN pip install uv && uv pip install --system -r /tmp/requirements.txt \
    && python -m playwright install chromium

# Создаём пользователя с тем же UID/GID, что и бот
RUN groupadd -g 100 users || true \
    && useradd -r -u 10002 -g users appuser \
    && mkdir -p /app/.cache/yt-dlp \
    && chown -R appuser:users /app
USER appuser

COPY downloader /app/downloader

EXPOSE 8082

CMD ["uvicorn", "downloader.main:app", "--host", "0.0.0.0", "--port", "8082"]
