from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError as YtDlpDownloadError

from packages.common_settings.settings import settings
from packages.dl_protocol.errors import ErrorCode

Source = Literal['mp4', 'm3u8']

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class YtDlpResult:
    """Результат успешной загрузки через yt-dlp.

    Attributes:
        filepath: Абсолютный путь к локальному файлу (предполагается в tmp_dir)
        source: Тип исходного медиа по данным экстрактора ('mp4' или 'm3u8').
        info: Сырой info-словарь yt-dlp (полезно для логов/диагностики,
        может быть усечённым).
    """
    filepath: str
    source: Source
    info: Dict[str, Any]


class DriverError(Exception):
    """
    Базовая ошибка драйвера. Содержит сопоставленный ErrorCode и признак
    повторяемости.
    """
    def __init__(
        self, code: ErrorCode, detail: str, *, retryable: bool = False
    ):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


async def try_ytdlp(
    url: str,
    tmp_dir: str,
    *,
    retries: int = settings.download.ytdlp_retries,
    timeout_sec: int = settings.download.ytdlp_timeout_sec,
    proxy: Optional[str] = None,
) -> YtDlpResult:
    """Скачать видео через yt-dlp с ретраями и возвратом локального пути.

    Поведение:
    - Пытается до `retries` раз. Между попытками — экспоненциальная пауза с
    джиттером.
    - Таймаут применяется как socket_timeout в yt-dlp.
    - При указании proxy — передаётся напрямую в опции yt-dlp (HTTP/HTTPS).
    - Имя итогового файла строим как `<tmp_dir>/<id>.mp4` с принудительным
    ремаксом в mp4, чтобы упростить дальнейшую нормализацию.

    Исключения:
    - При исчерпании попыток или при «неповторяемой» ошибке — бросает
    DriverError с корректным ErrorCode и detail.
    """
    ensure_dir(tmp_dir)

    last_exc: Optional[DriverError] = None
    base_sleep = 1.0

    for attempt in range(1, max(1, retries) + 1):
        # Небольшая человеческая задержка перед каждой попыткой
        _human_sleep(0.4, 1.2)
        try:
            result = await asyncio.to_thread(
                _ytdlp_download_once, url, tmp_dir, timeout_sec, proxy
            )
            logger.info(
                'yt-dlp: успешно скачано',
                extra={
                    'attempt': attempt,
                    'source': result.source,
                    'file': result.filepath,
                },
            )
            return result
        except DriverError as derr:
            last_exc = derr
            logger.warning(
                'yt-dlp: ошибка попытки %s/%s: %s (%s)',
                attempt,
                retries,
                derr.code,
                derr.detail,
            )
            # Решаем, стоит ли повторять
            if attempt < retries and derr.retryable:
                delay = base_sleep * (2 ** (attempt - 1)) + random.uniform(
                    0.2, 0.9
                )
                delay = min(delay, 6.0)
                await asyncio.sleep(delay)
                continue
            break

    assert last_exc is not None
    raise last_exc


def _ytdlp_download_once(
    url: str, tmp_dir: str, timeout_sec: int, proxy: Optional[str]
) -> YtDlpResult:
    """Одна попытка скачивания через yt-dlp (синхронно)."""
    # Базовые опции: тянем лучшую видеодорожку + аудио, стараемся получить mp4.
    # merge_output_format гарантирует итоговый mp4 на диске.
    outtmpl = os.path.join(tmp_dir, '%(id)s.%(ext)s')
    ydl_opts: Dict[str, Any] = {
        'outtmpl': outtmpl,
        'format': 'bv*+ba/b[ext=mp4]/b/best',
        'merge_output_format': 'mp4',
        'retries': 0,  # ретраи управляем сами
        'fragment_retries': 0,
        'noprogress': True,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': float(timeout_sec),
        'geo_bypass': True,
        # Иногда полезны HTTP заголовки-имитаторы браузера; добавим минимум
        'http_headers': {
            'User-Agent': _ua_mobile(),
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        # Постпроцессор remux → mp4 (без перекодирования)
        'postprocessors': [
            {
                'key': 'FFmpegVideoRemuxer',
                'preferedformat': 'mp4',  # опечатка из yt-dlp API намеренная
            }
        ],
    }
    if proxy:
        ydl_opts['proxy'] = proxy

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Ожидаем итоговый файл по маске <id>.mp4 (после remux)
            video_id = info.get('id')
            if not video_id:
                raise DriverError(
                    ErrorCode.NO_MEDIA_FOUND, 'Не удалось определить id видео'
                )
            final_path = os.path.join(tmp_dir, f'{video_id}.mp4')
            if not os.path.exists(final_path):
                # В редких случаях имя может отличаться;
                # попробуем взять из info
                alt = _guess_output_from_info(info, tmp_dir)
                if alt and os.path.exists(alt):
                    final_path = alt
                else:
                    raise DriverError(
                        ErrorCode.UNKNOWN_ERROR,
                        f'Файл не найден после загрузки: {final_path}'
                    )

            source = detect_source_from_info(info)
            return YtDlpResult(
                filepath=os.path.abspath(final_path),
                source=source,
                info=_shrink_info(info)
            )

    except YtDlpDownloadError as e:
        raise _map_ytdlp_error(e)
    except OSError as e:
        # Нет места на диске?
        if getattr(e, 'errno', None) == 28:  # ENOSPC
            raise DriverError(
                ErrorCode.FILESYSTEM_FULL,
                f'Недостаточно места: {e}',
                retryable=False
            )
        # Сетевые/таймауты могут прийти как OSError на нижнем уровне
        msg = str(e)
        if _looks_timeout(msg):
            raise DriverError(ErrorCode.TIMEOUT, msg, retryable=True)
        raise DriverError(ErrorCode.UNKNOWN_ERROR, msg, retryable=False)
    except Exception as e:
        msg = str(e)
        raise DriverError(ErrorCode.UNKNOWN_ERROR, msg, retryable=False)


def detect_source_from_info(info: Dict[str, Any]) -> Source:
    """
    Определить тип источника по данным yt-dlp: mp4 или m3u8.

    Смотрим на `protocol` и `url` в info. Если встречается `m3u8` — считаем
    HLS. В остальных случаях по умолчанию считаем `mp4`.
    """
    proto = (info.get('protocol') or '').lower()
    if 'm3u8' in proto:
        return 'm3u8'
    test_url = (info.get('url') or '').lower()
    if 'm3u8' in test_url:
        return 'm3u8'
    # Иногда нужный URL живёт в форматовом списке
    fmts = info.get('formats') or []
    for f in fmts:
        u = (f.get('url') or '').lower()
        if 'm3u8' in u:
            return 'm3u8'
    return 'mp4'


def _map_ytdlp_error(err: YtDlpDownloadError) -> DriverError:
    """
    Преобразование исключения yt-dlp в DriverError с ErrorCode.

    Пытаемся распознать частые случаи: 403/429 (ограничения), приват/логин,
    отсутствие медиа, сетевые таймауты.
    """
    msg = str(err) or ''
    low = msg.lower()

    # Частые HTTP статусы
    if 'http error 429' in low or 'too many requests' in low:
        return DriverError(ErrorCode.RATE_LIMITED, msg, retryable=False)
    if 'http error 403' in low or 'forbidden' in low:
        # Чаще всего это приват/требуется логин/регион-блок
        if _looks_login_required(low):
            return DriverError(
                ErrorCode.PRIVATE_OR_LOGIN_REQUIRED, msg, retryable=False
            )
        # Иначе считаем регион-блок/доступ запрещён
        return DriverError(ErrorCode.REGION_BLOCKED, msg, retryable=False)
    if 'requested format is not available' in low or 'unsupported url' in low:
        return DriverError(ErrorCode.NO_MEDIA_FOUND, msg, retryable=False)

    # Таймауты/сеть
    if _looks_timeout(low):
        return DriverError(ErrorCode.TIMEOUT, msg, retryable=True)
    if any(k in low for k in [
        'temporary failure', 'network is unreachable',
        'connection reset', 'timed out'
    ]):
        return DriverError(ErrorCode.NETWORK_ERROR, msg, retryable=True)

    # Прочее неизвестное — не повторяем агрессивно
    return DriverError(ErrorCode.UNKNOWN_ERROR, msg, retryable=False)


def _looks_login_required(text: str) -> bool:
    return any(k in text for k in [
        'login', 'private', 'signin', 'log in', 'sign in'
    ])  # очень грубая эвристика


def _looks_timeout(text: str) -> bool:
    return any(k in text for k in [
        'timeout', 'timed out', 'time-out', 'read timed out',
        'operation timed out'
    ])  # эвристика


def _ua_mobile() -> str:
    """Минимальный мобильный User-Agent, который не ломает IG/TT."""
    return (
        'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0'
        'Mobile/15E148 Safari/604.1'
    )


def ensure_dir(path: str) -> None:
    """Создать каталог при необходимости (без ошибок при гонках)."""
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        # если параллельные процессы одновременно создают — это ок
        pass


def _human_sleep(a: float, b: float) -> None:
    """Небольшая «человеческая» пауза для маскировки паттернов."""
    time.sleep(random.uniform(a, b))


def _shrink_info(info: Dict[str, Any]) -> Dict[str, Any]:
    """Обрезать info до разумного размера (оставим ключевые поля для логов)."""
    keep = {'id', 'title', 'ext', 'protocol', 'extractor', 'webpage_url'}
    return {k: v for k, v in info.items() if k in keep}


def _guess_output_from_info(
    info: Dict[str, Any], tmp_dir: str
) -> Optional[str]:
    """Попытаться угадать путь итогового файла по данным info.

    На новых версиях yt-dlp в `requested_downloads`/`_filename` может
    быть полный путь.
    Этот метод — подстраховка на случай, если `<id>.mp4` не найден.
    """
    # 1) requested_downloads → filepath
    rds = info.get('requested_downloads') or []
    for rd in rds:
        fp = rd.get('filepath') or rd.get('_filename')
        if fp and os.path.exists(fp):
            return str(fp)

    # 2) общие подсказки
    fn = info.get('_filename') or info.get('filename')
    if fn and os.path.exists(str(fn)):
        return str(fn)

    # 3) последняя попытка — тот же id, но другая экстеншн
    vid = info.get('id')
    ext = info.get('ext') or 'mp4'
    if vid:
        cand = os.path.join(tmp_dir, f'{vid}.{ext}')
        if os.path.exists(cand):
            return cand
    return None
