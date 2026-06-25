# Импортируем все модули явно — это обязательно для SQLAlchemy:
# Base.metadata должна видеть все таблицы до создания движка/миграций.
from packages.db.models import broadcast, pipeline, recipe, user  # noqa: F401

from .base import Base
from .broadcast import (
    BroadcastAudienceType,
    BroadcastCampaign,
    BroadcastCampaignStatus,
    BroadcastMessage,
    BroadcastMessageStatus,
)
from .pipeline import PipelineJob, PipelineJobStatus
from .recipe import Category, Ingredient, Recipe, RecipeIngredient, RecipeUser, Video
from .user import Admin, User

__all__ = [
    # base
    "Base",
    # user
    "User",
    "Admin",
    # recipe
    "Recipe",
    "Ingredient",
    "RecipeIngredient",
    "RecipeUser",
    "Video",
    "Category",
    # broadcast
    "BroadcastCampaignStatus",
    "BroadcastAudienceType",
    "BroadcastMessageStatus",
    "BroadcastCampaign",
    "BroadcastMessage",
    # pipeline
    "PipelineJobStatus",
    "PipelineJob",
]
