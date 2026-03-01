import asyncio
import json
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from sqlalchemy import func, select, update

from packages.app_state import AppState
from packages.common_settings.settings import settings
from packages.db.models import (
    BroadcastAudienceType,
    BroadcastCampaign,
    BroadcastCampaignStatus,
    BroadcastMessage,
    BroadcastMessageStatus,
)
from packages.db.repository import BroadcastRepository
from packages.redis.keys import RedisKeys
from packages.redis.repository import RedisLockRepository

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Вернуть текущее время в UTC (с timezone)."""
    return datetime.now(timezone.utc)


def _campaign_due_predicate() -> Any:
    """SQL-предикат: кампания готова к запуску (scheduled_at пуст или уже наступил)."""
    now = _utcnow()
    return (BroadcastCampaign.scheduled_at.is_(None)) | (BroadcastCampaign.scheduled_at <= now)


def _parse_json_dict(raw: str | None) -> dict[str, Any] | None:
    """Безопасно распарсить JSON-строку в словарь; иначе вернуть None."""
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


async def _tg_call(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Выполнить вызов Telegram Bot API и вернуть JSON-ответ как словарь."""
    token = settings.telegram.bot_token.get_secret_value().strip()
    url = f"https://api.telegram.org/bot{token}/{method}"
    timeout = settings.broadcast.request_timeout_sec

    def _call() -> dict[str, Any]:
        r = requests.post(url, json=payload, timeout=timeout)
        # Telegram обычно возвращает JSON даже при ошибке, пробуем парсить его в первую очередь.
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "error_code": r.status_code, "description": r.text[:300]}
        return data if isinstance(data, dict) else {"ok": False, "description": "Ответ не в формате JSON"}

    return await asyncio.to_thread(_call)


def _classify_failure(resp: dict[str, Any]) -> tuple[str, int | None, str]:
    """
    Классифицировать ошибку Telegram.

    Возвращает: (kind, retry_after_sec, description), где
    - kind: "permanent" | "retry"
    - retry_after_sec: задержка из Telegram (для 429), если есть
    """
    desc = str(resp.get("description") or "")
    code_raw = resp.get("error_code")
    try:
        code = int(code_raw) if code_raw is not None else 0
    except Exception:
        code = 0

    params = resp.get("parameters") if isinstance(resp.get("parameters"), dict) else {}
    retry_after = params.get("retry_after") if params else None
    retry_after_sec: int | None = None
    try:
        if isinstance(retry_after, (int | float)):
            retry_after_sec = int(retry_after)
        elif isinstance(retry_after, str) and retry_after.strip().isdigit():
            retry_after_sec = int(retry_after.strip())
    except Exception:
        retry_after_sec = None

    if code == 429 and retry_after_sec:
        return ("retry", retry_after_sec, desc or "Слишком много запросов")

    if code in (401, 404):
        # Ошибка токена/эндпоинта: кампанию продолжать нельзя.
        return ("permanent", None, desc or f"Ошибка Telegram API {code}")

    if code in (403,):
        return ("permanent", None, desc or "Доступ запрещен")

    if code in (400,):
        low = desc.lower()
        if "chat not found" in low or "user is deactivated" in low or "bot was blocked" in low:
            return ("permanent", None, desc)
        # Остальные 400 считаем постоянной ошибкой (некорректный payload).
        return ("permanent", None, desc)

    if code >= 500:
        return ("retry", None, desc or f"Ошибка сервера Telegram {code}")

    # Неизвестная ошибка: пробуем повторить несколько раз.
    return ("retry", None, desc or "Неизвестная ошибка")


async def _send_to_chat(c: BroadcastCampaign, *, chat_id: int) -> dict[str, Any]:
    """Отправить кампанию в чат: sendPhoto (если есть фото) или sendMessage."""
    reply_markup = _parse_json_dict(c.reply_markup_json)
    if c.photo_file_id or c.photo_url:
        photo = c.photo_file_id or c.photo_url
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo,
            "caption": c.text,
            "parse_mode": c.parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await _tg_call("sendPhoto", payload)

    payload = {
        "chat_id": chat_id,
        "text": c.text,
        "parse_mode": c.parse_mode,
        "disable_web_page_preview": bool(c.disable_web_page_preview),
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await _tg_call("sendMessage", payload)


async def _init_due_campaigns(state: AppState, *, limit: int = 20) -> None:
    """Перевести готовые queued-кампании в running и при необходимости построить outbox."""
    now = _utcnow()
    async with state.db.session() as session:
        res = await session.execute(
            select(BroadcastCampaign)
            .where(
                BroadcastCampaign.status == BroadcastCampaignStatus.queued,
                _campaign_due_predicate(),
            )
            .order_by(BroadcastCampaign.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True),
        )
        due = list(res.scalars().all())
        if not due:
            return

        for c in due:
            if c.audience_type != BroadcastAudienceType.all_users:
                c.status = BroadcastCampaignStatus.failed
                c.last_error = f"Неподдерживаемый audience_type: {c.audience_type}"
                c.finished_at = now
                continue

            if c.reply_markup_json and _parse_json_dict(c.reply_markup_json) is None:
                c.status = BroadcastCampaignStatus.failed
                c.last_error = "Некорректный reply_markup_json (должен быть JSON-объектом как в Telegram Bot API)"
                c.finished_at = now
                continue

            if c.outbox_created_at is None:
                await BroadcastRepository.build_outbox_all_users(session, campaign_id=int(c.id))
                c.outbox_created_at = now

            # Количество получателей: считаем строки в outbox.
            cnt = await session.execute(
                select(func.count(BroadcastMessage.id)).where(BroadcastMessage.campaign_id == int(c.id))
            )
            c.total_recipients = int(cnt.scalar() or 0)

            c.status = BroadcastCampaignStatus.running
            if c.started_at is None:
                c.started_at = now


async def _claim_messages_for_campaign(
    state: AppState,
    *,
    campaign_id: int,
    batch_size: int,
) -> list[tuple[int, int, int]]:
    """
    Атомарно «забрать» пачку сообщений в обработку.

    Возвращает список кортежей:
    (message_id, chat_id, attempts_after_claim)
    """
    now = _utcnow()
    lock_for = timedelta(seconds=120)
    async with state.db.session() as session:
        res = await session.execute(
            select(BroadcastMessage)
            .where(
                BroadcastMessage.campaign_id == int(campaign_id),
                BroadcastMessage.status.in_(
                    [BroadcastMessageStatus.pending, BroadcastMessageStatus.retry, BroadcastMessageStatus.sending]
                ),
                (BroadcastMessage.locked_until.is_(None)) | (BroadcastMessage.locked_until <= now),
                (BroadcastMessage.next_retry_at.is_(None)) | (BroadcastMessage.next_retry_at <= now),
            )
            .order_by(BroadcastMessage.id.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True),
        )
        rows = list(res.scalars().all())
        if not rows:
            return []

        claimed: list[tuple[int, int, int]] = []
        for m in rows:
            m.status = BroadcastMessageStatus.sending
            m.attempts = int(m.attempts or 0) + 1
            m.next_retry_at = None
            m.locked_until = now + lock_for
            m.last_error = None
            claimed.append((int(m.id), int(m.chat_id), int(m.attempts)))
        return claimed


async def _mark_message_sent(state: AppState, *, campaign_id: int, message_id: int) -> None:
    """Пометить сообщение отправленным и увеличить sent_count у кампании."""
    now = _utcnow()
    async with state.db.session() as session:
        await session.execute(
            update(BroadcastMessage)
            .where(BroadcastMessage.id == int(message_id))
            .values(status=BroadcastMessageStatus.sent, sent_at=now, next_retry_at=None, locked_until=None),
        )
        await session.execute(
            update(BroadcastCampaign)
            .where(BroadcastCampaign.id == int(campaign_id))
            .values(sent_count=BroadcastCampaign.sent_count + 1),
        )


async def _mark_message_failed(state: AppState, *, campaign_id: int, message_id: int, error: str) -> None:
    """Пометить сообщение как failed и увеличить failed_count у кампании."""
    async with state.db.session() as session:
        await session.execute(
            update(BroadcastMessage)
            .where(BroadcastMessage.id == int(message_id))
            .values(
                status=BroadcastMessageStatus.failed, last_error=error[:2000], next_retry_at=None, locked_until=None
            ),
        )
        await session.execute(
            update(BroadcastCampaign)
            .where(BroadcastCampaign.id == int(campaign_id))
            .values(failed_count=BroadcastCampaign.failed_count + 1),
        )


def _compute_backoff(attempt: int) -> int:
    """Экспоненциальная задержка (сек) с верхней границей 300."""
    # 1, 2, 4, 8, 16, 32, ... с ограничением сверху.
    return min(300, 2 ** max(0, attempt - 1))


def _lock_retry_delay(attempt: int) -> float:
    """
    Задержка перед повторным захватом lock с небольшим случайным разбросом.
    """
    base = min(30.0, float(2 ** min(6, max(0, attempt - 1))))
    jitter = random.uniform(0.0, min(1.0, base * 0.2))
    return base + jitter


async def _schedule_retry(
    state: AppState,
    *,
    message_id: int,
    error: str,
    retry_after_sec: int | None,
    attempt: int,
) -> None:
    """Перевести сообщение в retry и назначить next_retry_at."""
    delay = int(retry_after_sec or _compute_backoff(attempt))
    next_at = _utcnow() + timedelta(seconds=delay)
    async with state.db.session() as session:
        await session.execute(
            update(BroadcastMessage)
            .where(BroadcastMessage.id == int(message_id))
            .values(
                status=BroadcastMessageStatus.retry,
                next_retry_at=next_at,
                locked_until=None,
                last_error=error[:2000],
            ),
        )


async def _complete_finished_campaigns(state: AppState, *, limit: int = 50) -> None:
    """Закрыть running-кампании, у которых не осталось pending/retry/sending сообщений."""
    now = _utcnow()
    async with state.db.session() as session:
        res = await session.execute(
            select(BroadcastCampaign.id)
            .where(BroadcastCampaign.status == BroadcastCampaignStatus.running)
            .order_by(BroadcastCampaign.id.asc())
            .limit(limit),
        )
        ids = [int(x) for x in res.scalars().all()]
        if not ids:
            return
        for cid in ids:
            pending = await session.execute(
                select(func.count(BroadcastMessage.id)).where(
                    BroadcastMessage.campaign_id == cid,
                    BroadcastMessage.status.in_(
                        [BroadcastMessageStatus.pending, BroadcastMessageStatus.retry, BroadcastMessageStatus.sending]
                    ),
                )
            )
            left = int(pending.scalar() or 0)
            if left == 0:
                await session.execute(
                    update(BroadcastCampaign)
                    .where(BroadcastCampaign.id == cid, BroadcastCampaign.status == BroadcastCampaignStatus.running)
                    .values(status=BroadcastCampaignStatus.completed, finished_at=now),
                )


async def _load_campaign(state: AppState, *, campaign_id: int) -> BroadcastCampaign | None:
    """Загрузить кампанию по id."""
    async with state.db.session() as session:
        res = await session.execute(select(BroadcastCampaign).where(BroadcastCampaign.id == int(campaign_id)))
        return res.scalar_one_or_none()


async def _list_active_campaign_ids(state: AppState, *, limit: int = 50) -> list[int]:
    """Вернуть id активных (running) кампаний."""
    async with state.db.session() as session:
        res = await session.execute(
            select(BroadcastCampaign.id)
            .where(BroadcastCampaign.status == BroadcastCampaignStatus.running)
            .order_by(BroadcastCampaign.id.asc())
            .limit(limit)
        )
        return [int(x) for x in res.scalars().all()]


async def run_broadcast_worker(state: AppState) -> None:
    """
    Основной цикл воркера массовых рассылок.

    Шаги цикла:
    1) поднимает queued-кампании и строит outbox,
    2) отправляет сообщения пачками с rate-limit,
    3) обрабатывает retry/failed,
    4) завершает кампании без оставшихся сообщений.
    """
    if not settings.broadcast.enabled:
        logger.info("Воркер рассылки отключен настройками")
        return

    # В окружении должен работать только один активный воркер (при нескольких uvicorn workers/инстансах).
    lock_key = RedisKeys.broadcast_worker_lock()
    lock = None
    acquire_attempt = 0
    had_lock_before = False
    last_wait_log_ts = 0.0

    try:
        last_send_ts = 0.0
        min_interval = 1.0 / float(settings.broadcast.max_messages_per_second)

        while True:
            if lock is None:
                acquire_attempt += 1
                token = f"{int(time.time())}:{id(state)}:{acquire_attempt}"
                lock = await RedisLockRepository.acquire(
                    state.redis,
                    key=lock_key,
                    token=token,
                    ttl_sec=settings.broadcast.lock_ttl_sec,
                )
                if lock is None:
                    now_mono = time.monotonic()
                    if (now_mono - last_wait_log_ts) >= 30.0:
                        logger.info("Воркер рассылки ожидает lock: %s", lock_key)
                        last_wait_log_ts = now_mono
                    await asyncio.sleep(_lock_retry_delay(acquire_attempt))
                    continue

                if had_lock_before:
                    logger.warning("Lock воркера рассылки повторно захвачен: %s", lock_key)
                else:
                    logger.info("Воркер рассылки запущен")
                had_lock_before = True
                acquire_attempt = 0
                last_wait_log_ts = 0.0

            # Продлеваем lock.
            ok = await RedisLockRepository.refresh(state.redis, lock, ttl_sec=settings.broadcast.lock_ttl_sec)
            if not ok:
                logger.warning("Lock рассылки потерян; переходим в режим повторного захвата")
                lock = None
                await asyncio.sleep(_lock_retry_delay(1))
                continue

            # 1) Переводим queued-кампании в running и создаём outbox.
            await _init_due_campaigns(state)

            # 2) Обрабатываем running-кампании.
            campaign_ids = await _list_active_campaign_ids(state)
            for cid in campaign_ids:
                c = await _load_campaign(state, campaign_id=cid)
                if c is None:
                    continue
                if c.status != BroadcastCampaignStatus.running:
                    continue
                if c.status in (BroadcastCampaignStatus.paused, BroadcastCampaignStatus.cancelled):
                    continue

                batch = await _claim_messages_for_campaign(
                    state,
                    campaign_id=int(c.id),
                    batch_size=int(settings.broadcast.batch_size),
                )
                if not batch:
                    continue

                for mid, chat_id, attempt in batch:
                    # Глобальный rate-limit.
                    now_mono = time.monotonic()
                    wait = min_interval - (now_mono - last_send_ts)
                    if wait > 0:
                        await asyncio.sleep(wait)

                    resp = await _send_to_chat(c, chat_id=int(chat_id))
                    last_send_ts = time.monotonic()

                    if bool(resp.get("ok")):
                        await _mark_message_sent(state, campaign_id=int(c.id), message_id=int(mid))
                        continue

                    kind, retry_after, desc = _classify_failure(resp)
                    if kind == "permanent" or attempt >= int(settings.broadcast.max_attempts):
                        await _mark_message_failed(
                            state, campaign_id=int(c.id), message_id=int(mid), error=desc or "Постоянная ошибка"
                        )
                    else:
                        await _schedule_retry(
                            state,
                            message_id=int(mid),
                            error=desc or "Повторная попытка",
                            retry_after_sec=retry_after,
                            attempt=int(attempt),
                        )

            # 3) Завершаем кампании, где не осталось сообщений в обработке.
            await _complete_finished_campaigns(state)

            await asyncio.sleep(float(settings.broadcast.tick_seconds))
    except asyncio.CancelledError:
        logger.info("Воркер рассылки отменен")
        raise
    except Exception:
        logger.exception("Воркер рассылки аварийно завершился")
        raise
    finally:
        if lock is not None:
            await RedisLockRepository.release(state.redis, lock)
        logger.info("Воркер рассылки остановлен")
