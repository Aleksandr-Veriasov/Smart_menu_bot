"""Тесты для VideoRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.repository import (
    CategoryRepository,
    RecipeRepository,
    UserRepository,
    VideoRepository,
)
from packages.db.schemas import (
    CategoryCreate,
    RecipeCreate,
    UserCreate,
)


class TestVideoRepositoryCreate:
    """Тесты для VideoRepository.create()."""

    @pytest.mark.asyncio
    async def test_create_video_basic(self, db_session: AsyncSession) -> None:
        """Создание видео с URL."""
        # Создаем рецепт для видео
        user = await UserRepository.create(
            db_session,
            UserCreate(id=555555, username="video_user"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Видео рецепты"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт с видео",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        # Создаем видео
        video = await VideoRepository.create(
            db_session,
            video_url="https://youtube.com/watch?v=abc123",
            recipe_id=recipe.id,
        )

        assert video.id is not None
        assert video.video_url == "https://youtube.com/watch?v=abc123"
        assert video.recipe_id == recipe.id
        assert video.original_url is None

    @pytest.mark.asyncio
    async def test_create_video_with_original_url(self, db_session: AsyncSession) -> None:
        """Создание видео с оригинальным URL."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=666666, username="video_user2"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Видео 2"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт 2",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        video = await VideoRepository.create(
            db_session,
            video_url="https://example.com/video.mp4",
            recipe_id=recipe.id,
            original_url="https://original.com/video",
        )

        assert video.video_url == "https://example.com/video.mp4"
        assert video.original_url == "https://original.com/video"


class TestVideoRepositoryGet:
    """Тесты для методов получения видео."""

    @pytest.mark.asyncio
    async def test_get_video_url(self, db_session: AsyncSession) -> None:
        """Получение URL видео по ID рецепта."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=777777, username="video_user3"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Видео 3"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт 3",
                user_id=user.id,
                category_id=category.id,
            ),
        )
        await VideoRepository.create(
            db_session,
            video_url="https://youtube.com/watch?v=xyz789",
            recipe_id=recipe.id,
        )

        url = await VideoRepository.get_video_url(db_session, recipe.id)

        assert url == "https://youtube.com/watch?v=xyz789"

    @pytest.mark.asyncio
    async def test_get_video_url_nonexistent_recipe(self, db_session: AsyncSession) -> None:
        """Получение URL видео для несуществующего рецепта возвращает None."""
        url = await VideoRepository.get_video_url(db_session, 999999)

        assert url is None

    @pytest.mark.asyncio
    async def test_get_by_original_url(self, db_session: AsyncSession) -> None:
        """Получение видео по оригинальному URL."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=888888, username="video_user4"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Видео 4"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт 4",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        created_video = await VideoRepository.create(
            db_session,
            video_url="https://cdn.example.com/video.mp4",
            recipe_id=recipe.id,
            original_url="https://original.example.com/video",
        )

        video = await VideoRepository.get_by_original_url(db_session, "https://original.example.com/video")

        assert video is not None
        assert video.id == created_video.id
        assert video.original_url == "https://original.example.com/video"

    @pytest.mark.asyncio
    async def test_get_by_original_url_nonexistent(self, db_session: AsyncSession) -> None:
        """Получение по несуществующему оригинальному URL возвращает None."""
        video = await VideoRepository.get_by_original_url(db_session, "https://nonexistent.com/video")

        assert video is None

    @pytest.mark.asyncio
    async def test_get_all_by_original_url(self, db_session: AsyncSession) -> None:
        """Получение всех видео по оригинальному URL."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=999999, username="video_user5"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Видео 5"),
        )

        # Создаем несколько рецептов и видео с одним оригинальным URL
        original_url = "https://example.com/original/unique5"
        for i in range(3):
            recipe = await RecipeRepository.create(
                db_session,
                RecipeCreate(
                    title=f"Рецепт {i}",
                    user_id=user.id,
                    category_id=category.id,
                ),
            )
            await VideoRepository.create(
                db_session,
                video_url=f"https://cdn.example.com/video{i}.mp4",
                recipe_id=recipe.id,
                original_url=original_url,
            )

        videos = await VideoRepository.get_all_by_original_url(db_session, original_url)

        assert len(videos) == 3
        for video in videos:
            assert video.original_url == original_url

    @pytest.mark.asyncio
    async def test_get_all_by_original_url_with_limit(self, db_session: AsyncSession) -> None:
        """Получение видео с лимитом."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=1111111, username="video_user6"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Видео 6"),
        )

        original_url = "https://example2.com/original/unique6"
        for i in range(5):
            recipe = await RecipeRepository.create(
                db_session,
                RecipeCreate(
                    title=f"Рецепт видео {i}",
                    user_id=user.id,
                    category_id=category.id,
                ),
            )
            await VideoRepository.create(
                db_session,
                video_url=f"https://cdn2.example.com/v{i}.mp4",
                recipe_id=recipe.id,
                original_url=original_url,
            )

        videos = await VideoRepository.get_all_by_original_url(db_session, original_url, limit=2)

        assert len(videos) == 2


class TestVideoRepositoryIntegration:
    """Интеграционные тесты для VideoRepository."""

    @pytest.mark.asyncio
    async def test_video_associated_with_recipe(self, db_session: AsyncSession) -> None:
        """Видео связано с рецептом."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=2222222, username="video_user7"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Видео 7"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт с видео",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        # Создаем видео для рецепта
        await VideoRepository.create(
            db_session,
            video_url="https://youtube.com/watch?v=test123",
            recipe_id=recipe.id,
        )

        # Проверяем что видео привязано к рецепту
        video_url = await VideoRepository.get_video_url(db_session, recipe.id)
        assert video_url == "https://youtube.com/watch?v=test123"
