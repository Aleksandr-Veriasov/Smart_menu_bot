import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def extract_audio(video_path: str, output_folder: str) -> str:
    """Извлекает аудио из видео и сохраняет как WAV."""
    # Проверяем, существует ли директория для выходного файла
    if not os.path.exists(output_folder):
        os.makedirs(output_folder, exist_ok=True)

    audio_path: str = os.path.join(
        output_folder,
        os.path.basename(video_path).rsplit('.', 1)[0] + '.wav'
    )

    command: list[str] = [
        'ffmpeg', '-i', video_path,
        '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
        audio_path
    ]
    logger.debug(f'Извлечение аудио из {video_path} в {audio_path}')
    subprocess.run(command, check=True)
    logger.debug(f'Аудио успешно извлечено в {audio_path}')
    return audio_path
