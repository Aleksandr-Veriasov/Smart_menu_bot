import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def extract_audio(video_path: str, output_folder: str) -> str | None:
    """Извлекает аудио из видео и сохраняет как WAV."""
    # Проверяем, существует ли директория для выходного файла
    if not os.path.exists(output_folder):
        os.makedirs(output_folder, exist_ok=True)

    audio_path: str = os.path.join(output_folder, os.path.basename(video_path).rsplit(".", 1)[0] + ".wav")

    probe_command: list[str] = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        video_path,
    ]
    try:
        probe_result = subprocess.run(
            probe_command,
            check=True,
            capture_output=True,
            text=True,
        )
        if not probe_result.stdout.strip():
            logger.info(f"В видео нет аудио-дорожки: {video_path}")
            return None
    except subprocess.CalledProcessError as exc:
        logger.warning(f"Не удалось проверить аудио-дорожку через ffprobe: {exc}")

    command: list[str] = [
        "ffmpeg",
        "-i",
        video_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        audio_path,
    ]
    logger.debug(f"Извлечение аудио из {video_path} в {audio_path}")
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        logger.error(f"Не удалось извлечь аудио из {video_path}: {exc}")
        return None
    logger.debug(f"Аудио успешно извлечено в {audio_path}")
    return audio_path
