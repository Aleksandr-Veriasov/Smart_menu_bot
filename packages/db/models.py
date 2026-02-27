import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from packages.security.passwords import hash_password, verify_password


class Base(DeclarativeBase):
    """Базовый класс."""

    pass


class User(Base):
    """Модель пользователя."""

    __tablename__ = "users"

    # Используем Telegram user_id
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, unique=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    linked_recipes: Mapped[list["Recipe"]] = relationship(
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


class Recipe(Base):
    """Модель рецепта."""

    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(2000), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    linked_users: Mapped[list["User"]] = relationship(
        secondary="recipe_users",
        back_populates="linked_recipes",
        lazy="selectin",
        passive_deletes=True,
        overlaps="recipe_users,linked_recipes",
    )
    recipe_users: Mapped[list["RecipeUser"]] = relationship(
        back_populates="recipe",
        lazy="selectin",
        passive_deletes=True,
        overlaps="linked_recipes,linked_users",
    )

    # Видео (один к одному)
    video: Mapped["Video | None"] = relationship(
        back_populates="recipe",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
        passive_deletes=True,
    )

    # Ингредиенты (многие-ко-многим)
    ingredients: Mapped[list["Ingredient"]] = relationship(
        secondary="recipe_ingredients",
        back_populates="recipes",
        lazy="selectin",
        passive_deletes=True,
    )

    def __str__(self):
        return self.title


class Ingredient(Base):
    """Модель ингредиента."""

    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False, unique=True, index=True)

    recipes: Mapped[list["Recipe"]] = relationship(
        secondary="recipe_ingredients",
        back_populates="ingredients",
        lazy="selectin",
        passive_deletes=True,
    )

    def __str__(self) -> str:
        return self.name


class RecipeIngredient(Base):
    """Модель связи между рецептом и ингредиентами."""

    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        UniqueConstraint("recipe_id", "ingredient_id", name="uq_recipe_ingredient"),
        Index("ix_recipe_ingredients_recipe_id", "recipe_id"),
        Index("ix_recipe_ingredients_ingredient_id", "ingredient_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False,
    )
    ingredient_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("ingredients.id", ondelete="CASCADE"),
        nullable=False,
    )
    # TODO добавить поле количества и единицы измерения


class RecipeUser(Base):
    """Модель связи между рецептом и пользователями."""

    __tablename__ = "recipe_users"
    __table_args__ = (
        UniqueConstraint("recipe_id", "user_id", name="uq_recipe_user"),
        Index("ix_recipe_users_recipe_id", "recipe_id"),
        Index("ix_recipe_users_user_id", "user_id"),
        Index("ix_recipe_users_category_id", "category_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    recipe: Mapped["Recipe"] = relationship(
        back_populates="recipe_users",
        lazy="selectin",
        overlaps="linked_recipes,linked_users",
    )
    category: Mapped["Category"] = relationship(back_populates="recipe_users", lazy="selectin")


class Video(Base):
    """Модель видео."""

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("recipes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_url: Mapped[str] = mapped_column(String(500), nullable=False)
    original_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    recipe: Mapped["Recipe"] = relationship(back_populates="video", lazy="selectin")

    def __str__(self) -> str:
        return self.video_url


class Category(Base):
    """Модель категории."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)

    recipe_users: Mapped[list["RecipeUser"]] = relationship(
        back_populates="category",
        lazy="selectin",
        passive_deletes=True,
    )

    def __str__(self) -> str:
        return self.name


# ----------------------------
# Broadcast / Outbox (массовые рассылки)
# ----------------------------


class BroadcastCampaignStatus(str, enum.Enum):
    draft = "draft"
    queued = "queued"
    running = "running"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class BroadcastAudienceType(str, enum.Enum):
    all_users = "all_users"


class BroadcastMessageStatus(str, enum.Enum):
    pending = "pending"
    sending = "sending"
    sent = "sent"
    retry = "retry"
    failed = "failed"


class BroadcastCampaign(Base):
    """
    Кампания рассылки.

    Управление из кабинета:
    - draft: черновик
    - queued: поставить в очередь (воркер создаст outbox и переведёт в running)
    - running: выполняется
    - paused: пауза (воркер не берёт новые сообщения)
    - completed: закончено (все сообщения sent/failed)
    - cancelled: остановлено (воркер не берёт новые)
    - failed: ошибка конфигурации/фона
    """

    __tablename__ = "broadcast_campaigns"
    __table_args__ = (
        Index("ix_broadcast_campaigns_status", "status"),
        Index("ix_broadcast_campaigns_scheduled_at", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[BroadcastCampaignStatus] = mapped_column(
        SAEnum(BroadcastCampaignStatus, name="broadcast_campaign_status", native_enum=True),
        nullable=False,
        default=BroadcastCampaignStatus.draft,
    )

    # Сегментация (расширяемая).
    audience_type: Mapped[BroadcastAudienceType] = mapped_column(
        SAEnum(BroadcastAudienceType, name="broadcast_audience_type", native_enum=True),
        nullable=False,
        default=BroadcastAudienceType.all_users,
    )
    # JSON-строка (параметры сегмента). Оставляем TEXT, чтобы не привязываться к JSONB.
    audience_params_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Контент.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    parse_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="HTML")
    disable_web_page_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # JSON строка reply_markup (InlineKeyboardMarkup и т.п.) как в Bot API.
    reply_markup_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Медиа (минимум для MVP: одно фото).
    photo_file_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Планирование/метрики.
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    outbox_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    total_recipients: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    messages: Mapped[list["BroadcastMessage"]] = relationship(
        back_populates="campaign",
        lazy="selectin",
        passive_deletes=True,
        cascade="all, delete-orphan",
    )

    def __str__(self) -> str:
        return f"{self.id}: {self.name}"


class BroadcastMessage(Base):
    """Сообщение outbox для конкретного chat_id."""

    __tablename__ = "broadcast_messages"
    __table_args__ = (
        UniqueConstraint("campaign_id", "chat_id", name="uq_broadcast_campaign_chat"),
        Index("ix_broadcast_messages_campaign_id", "campaign_id"),
        Index("ix_broadcast_messages_status", "status"),
        Index("ix_broadcast_messages_next_retry_at", "next_retry_at"),
        Index("ix_broadcast_messages_locked_until", "locked_until"),
        Index("ix_broadcast_messages_status_next_retry_at", "status", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("broadcast_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    status: Mapped[BroadcastMessageStatus] = mapped_column(
        SAEnum(BroadcastMessageStatus, name="broadcast_message_status", native_enum=True),
        nullable=False,
        default=BroadcastMessageStatus.pending,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    campaign: Mapped["BroadcastCampaign"] = relationship(back_populates="messages", lazy="selectin")

    def __str__(self) -> str:
        return f"{self.id} ({self.status})"
