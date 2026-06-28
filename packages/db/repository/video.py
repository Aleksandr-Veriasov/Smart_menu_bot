from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from packages.db.models import Video

from .base import BaseRepository


class VideoRepository(BaseRepository[Video]):
    """Репозиторий для работы с видео рецептов."""

    model = Video

    async def get_video_url(self, recipe_id: int) -> str | None:
        """Вернуть video_url для рецепта."""
        statement = select(self.model.video_url).where(self.model.recipe_id == recipe_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_original_url(self, original_url: str) -> Video | None:
        """Найти последнее видео по original_url."""
        statement = (
            select(self.model).where(self.model.original_url == original_url).order_by(self.model.id.desc()).limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_all_by_original_url(self, original_url: str, *, limit: int = 20) -> list[Video]:
        """Вернуть все видео с указанным original_url, от новых к старым."""
        statement = select(self.model).where(self.model.original_url == original_url).order_by(self.model.id.desc())
        if limit and limit > 0:
            statement = statement.limit(int(limit))
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def create(
        self,
        video_url: str,
        recipe_id: int,
        *,
        original_url: str | None = None,
    ) -> Video:
        """Создать видео для рецепта. Raises ValueError при дублировании."""
        video = self.model(video_url=video_url, recipe_id=recipe_id, original_url=original_url)
        self.session.add(video)
        try:
            return await self.save(video)
        except IntegrityError as exc:
            raise ValueError("Video already exists") from exc
