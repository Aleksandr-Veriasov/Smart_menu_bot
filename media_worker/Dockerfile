FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    HF_HOME=/app/.cache

WORKDIR /app

# ffmpeg нужен для конвертации и извлечения аудио
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        tini \
    && rm -rf /var/lib/apt/lists/*

COPY media_worker/requirements.txt /tmp/requirements.txt
RUN pip install uv && uv pip install --system -r /tmp/requirements.txt

# Общие пакеты (все: services тянет schemas, recipes_core тянет integrations и т.д.)
COPY packages/ /app/packages/

# Воркер
COPY media_worker/                 /app/media_worker/

# Скачиваем веса faster-whisper при сборке — при старте контейнера модель уже в кэше
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"

# Рабочие папки для временных файлов
RUN mkdir -p /app/videos /app/audio

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "media_worker.main"]
