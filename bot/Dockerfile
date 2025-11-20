# Базовый образ
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY bot/requirements.txt /tmp/requirements.txt
RUN pip install uv && uv pip install --system -r /tmp/requirements.txt

# non-root пользователь и права
RUN groupadd -g 100 users || true \
    && useradd -r -u 10002 -g users appuser \
    && mkdir -p /app/.cache \
    && chown -R appuser:users /app
USER appuser

# Куда класть кэш моделей
ENV XDG_CACHE_HOME=/app/.cache

# 🔽 Загружаем модель whisper 'base'
RUN python3 -c "import whisper; whisper.load_model('base')"

# Копируем весь проект
COPY packages /app/packages
COPY bot  /app/bot
COPY ./alembic.ini /app/alembic.ini

# Команда запуска
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["python", "-m", "bot.app.start_bot"]
