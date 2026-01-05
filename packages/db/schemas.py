from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ===================== SHORT-СХЕМЫ =====================


class CategoryShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class IngredientShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class VideoShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_url: str


class RecipeShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str


class UserShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


# ===================== USER =====================


class UserBase(BaseModel):
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class UserCreate(UserBase):
    """Создание пользователя (Telegram user_id обязателен)."""

    id: int  # BigInteger в БД, но для API — int ок


class UserUpdate(UserBase):
    """Частичное обновление пользователя."""

    pass


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    # Важно: у тебя lazy='dynamic', поэтому здесь нужно прокинуть
    # конкретный список (recipe.query.all()) или использовать eager load.
    recipes: list[RecipeShort] = Field(default_factory=list)


# ===================== CATEGORY =====================


class CategoryBase(BaseModel):
    name: str


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str | None = None


class CategoryRead(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


# ===================== INGREDIENT =====================


class IngredientBase(BaseModel):
    name: str


class IngredientCreate(IngredientBase):
    pass


class IngredientUpdate(BaseModel):
    name: str | None = None


class IngredientRead(IngredientBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


# ===================== VIDEO (one-to-one с Recipe) =====================


class VideoBase(BaseModel):
    video_url: str


class VideoCreate(VideoBase):
    # Связь хранится на стороне Video
    recipe_id: int


class VideoUpdate(BaseModel):
    video_url: str | None = None
    recipe_id: int | None = None  # на случай перевязки


class VideoRead(VideoBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recipe_id: int


# ===================== RECIPE =====================


class RecipeBase(BaseModel):
    title: str
    description: str | None = None


class RecipeCreate(RecipeBase):
    user_id: int
    category_id: int
    ingredient_ids: list[int] = Field(default_factory=list)  # M2M через id


class RecipeUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category_id: int | None = None
    ingredient_ids: list[int] | None = None
    # если передано ingredient_ids — заменить состав
    # при необходимости добавь:
    # add_ingredient_ids: Optional[List[int]] = None
    # remove_ingredient_ids: Optional[List[int]] = None


class RecipeRead(RecipeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    user_id: int

    category: CategoryShort
    ingredients: list[IngredientShort] = Field(default_factory=list)
    video: VideoShort | None = None


# ===================== RECIPE_INGREDIENT (линк-таблица) =====================


class RecipeIngredientCreate(BaseModel):
    recipe_id: int
    ingredient_id: int


class RecipeIngredientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recipe_id: int
    ingredient_id: int
