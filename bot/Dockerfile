# Базовый образ
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    ffmpeg \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY bot/requirements.txt /tmp/requirements.txt
RUN pip install uv && uv pip install --system -r /tmp/requirements.txt

# Копируем весь проект
COPY packages /app/packages
COPY bot  /app/bot
COPY ./alembic.ini /app/alembic.ini

# Команда запуска (aiogram)
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["python", "-m", "bot.src.start_bot"]
