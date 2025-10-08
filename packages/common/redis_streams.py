from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from redis.typing import EncodableT, FieldT, KeyT, StreamIdT

StreamId = str
ReadFields = Dict[str, str]
Message = Tuple[StreamId, ReadFields]


async def ensure_group(
    redis: Redis, stream: str, group: str, *, create_from: str = '$'
) -> None:
    """
    Создайте группу потребителей, если она ещё не существует.

    Аргументы:
    redis: Асинхронный клиент Redis.
    stream: Имя потока (например, 'dl:tasks').
    group: Имя группы (например, 'dl:workers').
    create_from: Идентификатор, с которого группа начнёт чтение
    (по умолчанию: '$'). Используйте '$', чтобы начать только с новых записей,
    или '0-0' для получения истории.
    """
    try:
        # MKSTREAM обеспечивает создание потока, если он отсутствует
        await redis.xgroup_create(stream, group, id=create_from, mkstream=True)
    except ResponseError as e:
        # BUSYGROUP означает, что группа уже существует
        if 'BUSYGROUP' in str(e):
            return
        # Если поток уже существует, но не группа, это ошибка
        if 'stream already exists' in str(e).lower():
            return
        raise


async def xadd(
    redis: Redis,
    stream: str,
    fields: Dict[FieldT, EncodableT],
    maxlen: Optional[int] = None,
    *,
    approximate: bool = True
) -> StreamId:
    """
    Добавить запись в поток.

    Аргументы:
    redis: Асинхронный клиент Redis.
    stream: Имя потока.
    fields: Сопоставление поля->значения (str->str). При необходимости значения
    будут преобразованы в тип str с помощью redis-py.
    maxlen: Если указано, обрезает поток примерно до этой длины.
    approximity: Используйте `~` для приблизительной обрезки (рекомендуется для
    повышения производительности).
    Returns:
    Идентификатор сгенерированной записи.
    """
    if maxlen is not None:
        return str(await redis.xadd(
            stream, fields, maxlen=maxlen, approximate=approximate
        ))
    return str(await redis.xadd(stream, fields))


async def xreadgroup_loop(
    redis: Redis,
    stream: str,
    group: str,
    consumer: str,
    count: int = 10,
    block_ms: int = 5000,
    *,
    noack: bool = False,
) -> AsyncGenerator[Message, None]:
    """
    Непрерывно считывать записи из потока в составе группы потребителей.

    Возвращает кортежи (id, fields) для запрошенного `stream`. Это цикл с
    длинным опросом; отмените задачу, чтобы остановить её. Подтверждайте
    каждое сообщение с помощью `xack`, если `noack=True`.

    Аргументы:
    redis: Асинхронный клиент Redis.
    stream: Имя потока.
    group: Имя группы потребителей.
    consumer: Имя потребителя (уникальное для каждого экземпляра рабочего
    процесса).
    count: Максимальное количество сообщений за одну выборку.
    block_ms: Время блокировки в миллисекундах (длинный опрос на стороне
    сервера).
    noack: Если True, не требовать XACK (сообщения не попадут в PEL). Не
    рекомендуется для семантики «atleast-once».
    """
    streams: Dict[KeyT, StreamIdT] = {stream: '>'}
    while True:
        try:
            data = await redis.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams=streams,
                count=count,
                block=block_ms,
                noack=noack,
            )
        except ResponseError as e:
            # Если группа не существует, создайте её и продолжайте
            if 'NOGROUP' in str(e):
                await ensure_group(redis, stream, group)
                continue
            raise

        if not data:
            # Тайм-аут ожидания, повторить
            continue

        # redis-py возвращает список (stream, [(id, {field: value, ...}), ...])
        for stream_name, messages in data:
            if stream_name != stream:
                # Выход только из запрошенного потока
                continue
            for msg_id, fields in messages:
                yield msg_id, fields  # ack с xack() снаружи

        # Позволяет другим задачам выполняться
        await asyncio.sleep(0)


async def xack(
    redis: Redis, stream: str, group: str, entry_id: StreamId
) -> int:
    """
    Подтверждение обработки сообщения.

    Возвращает количество подтверждённых записей (0 или 1).
    """
    try:
        return int(await redis.xack(stream, group, entry_id))
    except ResponseError as e:
        # Если группа/запись исчезла, считать, что она подтверждена,
        # чтобы избежать бесконечных циклов.
        if 'NOGROUP' in str(e) or 'no such key' in str(e).lower():
            return 0
        raise


async def xautoclaim_or_xclaim(
    redis: Redis,
    stream: str,
    group: str,
    consumer: str,
    *,
    min_idle_ms: int = 600000,  # 10 minutes
    count: int = 50,
) -> List[Message]:
    """
    Заявка зависла в ожидании записей для указанного потребителя.

    Предпочитает XAUTOCLAIM (Redis >= 6.2). В противном случае возвращается к
    XPENDING+XCLAIM.

    Возвращает список (id, fields) запрошенных записей.
    """
    # Первая попытка XAUTOCLAIM
    try:
        # начните с «0-0», чтобы просканировать все ожидающие
        next_start, claimed = await redis.xautoclaim(
            stream, group, consumer, min_idle_ms, start_id='0-0', count=count
        )
        # заявлено в список[Tuple[bytes/str id, Dict[...]]]
        return [(msg_id, fields) for msg_id, fields in claimed]
    except ResponseError as e:
        # Резервный вариант для Redis < 6.2, который не поддерживает XAUTOCLAIM
        if 'unknown command' not in str(e).lower():
            raise

    # Резервный путь с использованием XPENDING и XCLAIM
    try:
        # ДИАПАЗОН ОЖИДАНИЯ: подсчитайте самые старые ожидающие записи
        pend = await redis.xpending_range(
            stream, group, min='-', max='+', count=count
        )
        ids = [p[0] if isinstance(
            p, (list, tuple)
        ) else p['message_id'] for p in pend]
        if not ids:
            return []
        # XCLAIM их этому потребителю
        # (force = True для переопределения неотвечающих потребителей)
        claimed_ids = await redis.xclaim(
            stream, group, consumer, min_idle_ms, message_ids=ids,
            idle=min_idle_ms, retrycount=1, force=True
        )
        # XCLAIM возвращает список (id, fields)
        return [(msg_id, fields) for msg_id, fields in claimed_ids]
    except ResponseError:
        # Если группа или поток отсутствуют, просто верните пустое значение.
        return []


async def xtrim_maxlen(
    redis: Redis, stream: str, maxlen: int, *, approximate: bool = True
) -> int:
    """
    Обрезать поток до (приблизительно) `maxlen` записей.

    Возвращает количество удалённых записей (приблизительное,
    если `approximate=True`).
    """
    try:
        return int(await redis.xtrim(
            stream, maxlen=maxlen, approximate=approximate
        ))
    except ResponseError as e:
        if 'no such key' in str(e).lower():
            return 0
        raise
