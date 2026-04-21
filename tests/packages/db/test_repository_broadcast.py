"""Тесты для BroadcastRepository."""

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import BroadcastCampaignStatus
from packages.db.repository import BroadcastRepository


class TestBroadcastRepositoryCampaigns:
    """Тесты для методов работы с кампаниями."""

    @pytest.mark.asyncio
    async def test_create_campaign_basic(self, db_session: AsyncSession) -> None:
        """Создание базовой кампании."""
        campaign = await BroadcastRepository.create_campaign(
            db_session,
            name="Тестовая кампания",
            status=BroadcastCampaignStatus.draft,
            audience_type="all_users",
            audience_params_json=None,
            text="Привет всем!",
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup_json=None,
            photo_file_id=None,
            photo_url=None,
            scheduled_at=None,
        )

        assert campaign.id is not None
        assert campaign.name == "Тестовая кампания"
        assert campaign.text == "Привет всем!"
        assert campaign.status == BroadcastCampaignStatus.draft

    @pytest.mark.asyncio
    async def test_get_campaign_or_none_exists(self, db_session: AsyncSession) -> None:
        """Получение существующей кампании."""
        created = await BroadcastRepository.create_campaign(
            db_session,
            name="Кампания для получения",
            status=BroadcastCampaignStatus.draft,
            audience_type="all_users",
            audience_params_json=None,
            text="Текст",
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup_json=None,
            photo_file_id=None,
            photo_url=None,
            scheduled_at=None,
        )

        retrieved = await BroadcastRepository.get_campaign_or_none(db_session, created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "Кампания для получения"

    @pytest.mark.asyncio
    async def test_get_campaign_or_none_not_exists(self, db_session: AsyncSession) -> None:
        """Получение несуществующей кампании возвращает None."""
        campaign = await BroadcastRepository.get_campaign_or_none(db_session, 999999)

        assert campaign is None

    @pytest.mark.asyncio
    async def test_list_campaigns(self, db_session: AsyncSession) -> None:
        """Получение списка кампаний."""
        # Создаем несколько кампаний
        for i in range(3):
            await BroadcastRepository.create_campaign(
                db_session,
                name=f"Кампания {i}",
                status=BroadcastCampaignStatus.draft,
                audience_type="all_users",
                audience_params_json=None,
                text=f"Текст {i}",
                parse_mode="HTML",
                disable_web_page_preview=False,
                reply_markup_json=None,
                photo_file_id=None,
                photo_url=None,
                scheduled_at=None,
            )

        campaigns = await BroadcastRepository.list_campaigns(db_session, limit=10)

        assert len(campaigns) >= 3


class TestBroadcastRepositoryTransitions:
    """Тесты для переходов состояния кампании."""

    @pytest.mark.asyncio
    async def test_queue_campaign(self, db_session: AsyncSession) -> None:
        """Перевод кампании в состояние queued."""
        campaign = await BroadcastRepository.create_campaign(
            db_session,
            name="Кампания в очередь",
            status=BroadcastCampaignStatus.draft,
            audience_type="all_users",
            audience_params_json=None,
            text="Текст",
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup_json=None,
            photo_file_id=None,
            photo_url=None,
            scheduled_at=None,
        )

        queued = await BroadcastRepository.queue_campaign(db_session, campaign_id=campaign.id)

        assert queued.status == BroadcastCampaignStatus.queued
        assert queued.last_error is None

    @pytest.mark.asyncio
    async def test_queue_campaign_nonexistent(self, db_session: AsyncSession) -> None:
        """Перевод несуществующей кампании вызывает ошибку."""
        with pytest.raises(LookupError):
            await BroadcastRepository.queue_campaign(db_session, campaign_id=999999)

    @pytest.mark.asyncio
    async def test_pause_campaign(self, db_session: AsyncSession) -> None:
        """Пауза для запущенной кампании."""
        campaign = await BroadcastRepository.create_campaign(
            db_session,
            name="Кампания для паузы",
            status=BroadcastCampaignStatus.running,
            audience_type="all_users",
            audience_params_json=None,
            text="Текст",
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup_json=None,
            photo_file_id=None,
            photo_url=None,
            scheduled_at=None,
        )

        paused = await BroadcastRepository.pause_campaign(db_session, campaign_id=campaign.id)

        assert paused.status == BroadcastCampaignStatus.paused

    @pytest.mark.asyncio
    async def test_resume_campaign(self, db_session: AsyncSession) -> None:
        """Возобновление паузированной кампании."""
        now = datetime.utcnow()
        campaign = await BroadcastRepository.create_campaign(
            db_session,
            name="Кампания для возобновления",
            status=BroadcastCampaignStatus.paused,
            audience_type="all_users",
            audience_params_json=None,
            text="Текст",
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup_json=None,
            photo_file_id=None,
            photo_url=None,
            scheduled_at=None,
        )

        resumed = await BroadcastRepository.resume_campaign(db_session, campaign_id=campaign.id, now_utc=now)

        assert resumed.status == BroadcastCampaignStatus.running

    @pytest.mark.asyncio
    async def test_cancel_campaign(self, db_session: AsyncSession) -> None:
        """Отмена запущенной кампании."""
        now = datetime.utcnow()
        campaign = await BroadcastRepository.create_campaign(
            db_session,
            name="Кампания для отмены",
            status=BroadcastCampaignStatus.running,
            audience_type="all_users",
            audience_params_json=None,
            text="Текст",
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup_json=None,
            photo_file_id=None,
            photo_url=None,
            scheduled_at=None,
        )

        cancelled = await BroadcastRepository.cancel_campaign(db_session, campaign_id=campaign.id, now_utc=now)

        assert cancelled.status == BroadcastCampaignStatus.cancelled
        assert cancelled.finished_at is not None


class TestBroadcastRepositoryUpdate:
    """Тесты для обновления кампаний."""

    @pytest.mark.asyncio
    async def test_update_campaign_basic(self, db_session: AsyncSession) -> None:
        """Обновление полей кампании."""
        campaign = await BroadcastRepository.create_campaign(
            db_session,
            name="Исходная кампания",
            status=BroadcastCampaignStatus.draft,
            audience_type="all_users",
            audience_params_json=None,
            text="Исходный текст",
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup_json=None,
            photo_file_id=None,
            photo_url=None,
            scheduled_at=None,
        )

        updated = await BroadcastRepository.update_campaign(
            db_session,
            campaign_id=campaign.id,
            changes={"text": "Новый текст", "name": "Новая кампания"},
        )

        assert updated.text == "Новый текст"
        assert updated.name == "Новая кампания"

    @pytest.mark.asyncio
    async def test_update_campaign_with_deliveries_raises_error(self, db_session: AsyncSession) -> None:
        """Обновление кампании с отправками вызывает ошибку."""
        campaign = await BroadcastRepository.create_campaign(
            db_session,
            name="Кампания с отправками",
            status=BroadcastCampaignStatus.draft,
            audience_type="all_users",
            audience_params_json=None,
            text="Текст",
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup_json=None,
            photo_file_id=None,
            photo_url=None,
            scheduled_at=None,
        )
        # Устанавливаем sent_count чтобы имитировать отправки
        campaign.sent_count = 1
        await db_session.flush()

        with pytest.raises(ValueError, match="already has deliveries"):
            await BroadcastRepository.update_campaign(
                db_session,
                campaign_id=campaign.id,
                changes={"text": "Новый текст"},
            )


class TestBroadcastRepositoryMessages:
    """Тесты для работы с сообщениями кампании."""

    @pytest.mark.asyncio
    async def test_list_messages(self, db_session: AsyncSession) -> None:
        """Получение сообщений кампании."""
        campaign = await BroadcastRepository.create_campaign(
            db_session,
            name="Кампания с сообщениями",
            status=BroadcastCampaignStatus.draft,
            audience_type="all_users",
            audience_params_json=None,
            text="Текст",
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup_json=None,
            photo_file_id=None,
            photo_url=None,
            scheduled_at=None,
        )

        messages = await BroadcastRepository.list_messages(db_session, campaign_id=campaign.id, limit=20)

        # Может быть пусто или с сообщениями
        assert isinstance(messages, list)
