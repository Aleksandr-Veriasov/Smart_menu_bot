from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.security.passwords import hash_password, verify_password

from .base import Base


class User(Base):
    """Модель пользователя."""

    __tablename__ = "users"

    # Используем Telegram user_id
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, unique=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    linked_recipes: Mapped[list["Recipe"]] = relationship(  # noqa: F821
        secondary="recipe_users",
        back_populates="linked_users",
        lazy="selectin",
        passive_deletes=True,
        overlaps="recipe_users,linked_users",
    )


class Admin(Base):
    """Модель администратора (для доступа к админке)."""

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    login: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Важно: вычислений и I/O здесь не делаем — только простая запись/сравнение
    def set_password(self, raw_password: str) -> None:
        self.password_hash = hash_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return verify_password(raw_password, self.password_hash)
