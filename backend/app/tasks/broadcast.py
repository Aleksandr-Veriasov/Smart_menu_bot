import asyncio
import logging
import random
import time

from packages.app_state import AppState
from packages.common_settings.settings import settings
from packages.enums import BroadcastFailureKind as FailureKind
from packages.integrations.telegram_api import classify_failure
from packages.redis.keys import RedisKeys
from packages.redis.lock_repository import RedisLockRepository
from packages.services.broadcast_worker_service import BroadcastWorkerService

logger = logging.getLogger(__name__)


def _lock_retry_delay(attempt: int) -> float:
    base = min(30.0, float(2 ** min(6, max(0, attempt - 1))))
    return base + random.uniform(0.0, min(1.0, base * 0.2))


async def run_broadcast_worker(state: AppState) -> None:
    if not settings.broadcast.enabled:
        logger.info("Воркер рассылки отключен настройками")
        return

    service = BroadcastWorkerService(db=state.db, redis=state.redis)
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

            ok = await RedisLockRepository.refresh(state.redis, lock, ttl_sec=settings.broadcast.lock_ttl_sec)
            if not ok:
                logger.warning("Lock рассылки потерян; переходим в режим повторного захвата")
                lock = None
                await asyncio.sleep(_lock_retry_delay(1))
                continue

            await service.init_due_campaigns()

            for campaign_id in await service.list_active_campaign_ids():
                batch = await service.claim_messages(campaign_id, batch_size=int(settings.broadcast.batch_size))
                for mid, chat_id, attempt in batch:
                    wait = min_interval - (time.monotonic() - last_send_ts)
                    if wait > 0:
                        await asyncio.sleep(wait)

                    resp = await service.send_to_chat(campaign_id, chat_id=chat_id)
                    last_send_ts = time.monotonic()

                    if bool(resp.get("ok")):
                        await service.mark_message_sent(campaign_id=campaign_id, message_id=mid)
                        continue

                    kind, retry_after = classify_failure(resp)
                    if kind == FailureKind.permanent or attempt >= int(settings.broadcast.max_attempts):
                        await service.mark_message_failed(
                            campaign_id=campaign_id,
                            message_id=mid,
                            error=resp.get("description") or "Постоянная ошибка",
                        )
                    else:
                        await service.schedule_retry(
                            message_id=mid,
                            error=resp.get("description") or "Повторная попытка",
                            retry_after_sec=retry_after,
                            attempt=attempt,
                        )

            await service.complete_finished_campaigns()
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
