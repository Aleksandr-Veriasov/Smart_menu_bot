import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def extract_audio(video_path: str, output_folder: str) -> str:
    """Извлекает аудио из видео и сохраняет как WAV."""
    # Проверяем, существует ли директория для выходного файла
    if not os.path.exists(output_folder):
        os.makedirs(output_folder, exist_ok=True)
    try:
        os.chmod(output_folder, 0o777)
    except PermissionError:
        logger.warning(
            'Не удалось выставить права 777 на каталог %s — продолжаем', output_folder
        )

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
    try:
        os.chmod(audio_path, 0o666)
    except PermissionError:
        logger.warning(
            'Не удалось выставить права 666 на файл %s — возможно, дальнейшие операции не смогут удалить файл',
            audio_path,
        )
    logger.debug(f'Аудио успешно извлечено в {audio_path}')
    return audio_path
