from __future__ import annotations

from enum import Enum
from typing import Dict


class ErrorCode(str, Enum):
    PRIVATE_OR_LOGIN_REQUIRED = 'PRIVATE_OR_LOGIN_REQUIRED'
    REGION_BLOCKED = 'REGION_BLOCKED'
    RATE_LIMITED = 'RATE_LIMITED'
    NO_MEDIA_FOUND = 'NO_MEDIA_FOUND'
    NETWORK_ERROR = 'NETWORK_ERROR'
    TIMEOUT = 'TIMEOUT'
    TRANSCODE_FAILED = 'TRANSCODE_FAILED'
    FILESYSTEM_FULL = 'FILESYSTEM_FULL'
    UNKNOWN_ERROR = 'UNKNOWN_ERROR'


class Stage(str, Enum):
    DOWNLOAD = 'download'
    CONVERT = 'convert'
    POSTPROCESS = 'postprocess'
    PROBE = 'probe'


USER_MESSAGES: Dict[ErrorCode, str] = {
    ErrorCode.PRIVATE_OR_LOGIN_REQUIRED: (
        'Видео приватное или требует вход — без доступа скачать нельзя.'
    ),
    ErrorCode.REGION_BLOCKED: (
        'Источник временно недоступен из нашего региона.'
    ),
    ErrorCode.RATE_LIMITED: (
        'Источник ограничил частоту обращений. Попробуйте позже.'
    ),
    ErrorCode.NO_MEDIA_FOUND: 'По ссылке не удалось найти видео.',
    ErrorCode.NETWORK_ERROR: 'Сетевая ошибка при скачивании.',
    ErrorCode.TIMEOUT: 'Скачивание заняло слишком долго.',
    ErrorCode.TRANSCODE_FAILED: 'Ошибка на этапе обработки видео.',
    ErrorCode.FILESYSTEM_FULL: 'Недостаточно места на сервере.',
    ErrorCode.UNKNOWN_ERROR: 'Непредвиденная ошибка при скачивании.',
}
