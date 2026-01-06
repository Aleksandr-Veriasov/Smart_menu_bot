from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
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

    recipe: Mapped["Recipe"] = relationship(back_populates="recipe_users", lazy="selectin")
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
