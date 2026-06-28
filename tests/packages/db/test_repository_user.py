"""Tests for UserRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.repository import UserRepository
from packages.db.schemas import UserCreate, UserUpdate


class TestUserRepositoryCreate:
    """Тесты для UserRepository.create()."""

    @pytest.mark.asyncio
    async def test_create_user_basic(self, db_session: AsyncSession) -> None:
        """Создание пользователя с минимальными данными."""
        user_create = UserCreate(id=123456, username="testuser")

        user = await UserRepository(db_session).create(user_create)

        assert user.id == 123456
        assert user.username == "testuser"

    @pytest.mark.asyncio
    async def test_create_user_with_all_fields(self, db_session: AsyncSession) -> None:
        """Создание пользователя со всеми опциональными полями."""
        user_create = UserCreate(
            id=789012,
            username="fulluser",
            first_name="John",
            last_name="Doe",
        )

        user = await UserRepository(db_session).create(user_create)

        assert user.id == 789012
        assert user.first_name == "John"
        assert user.last_name == "Doe"

    @pytest.mark.asyncio
    async def test_create_duplicate_user_raises_error(self, db_session: AsyncSession) -> None:
        """Создание пользователя с дублирующимся ID вызывает ValueError."""
        user_create = UserCreate(id=111111, username="duplicate")

        # Create first user
        await UserRepository(db_session).create(user_create)

        # Try to create duplicate
        with pytest.raises(ValueError, match="User already exists"):
            await UserRepository(db_session).create(user_create)

    @pytest.mark.asyncio
    async def test_user_has_id_after_create(self, db_session: AsyncSession) -> None:
        """Пользователь получает PK после flush."""
        user_create = UserCreate(id=222222, username="newuser")

        user = await UserRepository(db_session).create(user_create)

        assert user.id is not None
        assert isinstance(user.id, int)


class TestUserRepositoryGetById:
    """Тесты для UserRepository.get_by_id()."""

    @pytest.mark.asyncio
    async def test_get_existing_user_by_id(self, db_session: AsyncSession) -> None:
        """Получение существующего пользователя по ID."""
        user_create = UserCreate(id=333333, username="getuser")
        repo = UserRepository(db_session)
        created = await repo.create(user_create)

        retrieved = await repo.get_by_id(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.username == "getuser"

    @pytest.mark.asyncio
    async def test_get_nonexistent_user_returns_none(self, db_session: AsyncSession) -> None:
        """Получение несуществующего пользователя возвращает None."""
        result = await UserRepository(db_session).get_by_id(999999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_with_zero_id_returns_none(self, db_session: AsyncSession) -> None:
        """Получение пользователя с невалидным ID (0) возвращает None."""
        result = await UserRepository(db_session).get_by_id(0)

        assert result is None


class TestUserRepositoryUpdate:
    """Тесты для UserRepository.update()."""

    @pytest.mark.asyncio
    async def test_update_user_basic(self, db_session: AsyncSession) -> None:
        """Обновление полей пользователя."""
        # Create user
        user_create = UserCreate(id=444444, username="updateme")
        repo = UserRepository(db_session)
        user = await repo.create(user_create)

        # Update user
        update_data = UserUpdate(username="updated_username")
        updated = await repo.update(user.id, update_data)

        assert updated.username == "updated_username"
        assert updated.id == 444444  # unchanged

    @pytest.mark.asyncio
    async def test_update_user_multiple_fields(self, db_session: AsyncSession) -> None:
        """Обновление нескольких полей пользователя одновременно."""
        repo = UserRepository(db_session)
        user_create = UserCreate(id=555555, username="multiupdate")
        user = await repo.create(user_create)

        update_data = UserUpdate(username="new_username", first_name="Jane")
        updated = await repo.update(user.id, update_data)

        assert updated.username == "new_username"
        assert updated.first_name == "Jane"

    @pytest.mark.asyncio
    async def test_update_nonexistent_user_raises_error(self, db_session: AsyncSession) -> None:
        """Обновление несуществующего пользователя вызывает ValueError."""
        update_data = UserUpdate(username="something")

        with pytest.raises(ValueError, match="User not found"):
            await UserRepository(db_session).update(999999, update_data)

    @pytest.mark.asyncio
    async def test_update_preserves_other_fields(self, db_session: AsyncSession) -> None:
        """Обновление отдельных полей не влияет на остальные."""
        user_create = UserCreate(
            id=666666,
            username="preserve",
            first_name="Original",
            last_name="Name",
        )
        repo = UserRepository(db_session)
        user = await repo.create(user_create)

        # Update only username
        update_data = UserUpdate(username="newusername")
        updated = await repo.update(user.id, update_data)

        assert updated.first_name == "Original"
        assert updated.last_name == "Name"
        assert updated.username == "newusername"


class TestUserRepositoryIntegration:
    """Интеграционные тесты для UserRepository."""

    @pytest.mark.asyncio
    async def test_create_and_retrieve_user_full_cycle(self, db_session: AsyncSession) -> None:
        """Полный цикл: создание, получение, обновление, получение снова."""
        from packages.db.schemas import UserUpdate

        repo = UserRepository(db_session)

        # Create
        user_create = UserCreate(id=777777, username="fullcycle")
        created = await repo.create(user_create)

        # Retrieve
        retrieved = await repo.get_by_id(created.id)
        assert retrieved is not None
        assert retrieved.username == "fullcycle"

        # Update
        await repo.update(created.id, UserUpdate(username="updated_cycle"))

        # Retrieve again
        final = await repo.get_by_id(created.id)
        assert final is not None
        assert final.username == "updated_cycle"

    @pytest.mark.asyncio
    async def test_multiple_users_isolation(self, db_session: AsyncSession) -> None:
        """Несколько пользователей не влияют друг на друга."""
        repo = UserRepository(db_session)

        # Create user 1
        user1_create = UserCreate(id=888888, username="user1")
        user1 = await repo.create(user1_create)

        # Create user 2
        user2_create = UserCreate(id=999999, username="user2")
        user2 = await repo.create(user2_create)

        # Update user 1
        update_data = UserUpdate(username="user1_updated")
        await repo.update(user1.id, update_data)

        # Verify user 2 unchanged
        user2_check = await repo.get_by_id(user2.id)
        assert user2_check is not None
        assert user2_check.username == "user2"

        # Verify user 1 updated
        user1_check = await repo.get_by_id(user1.id)
        assert user1_check is not None
        assert user1_check.username == "user1_updated"
