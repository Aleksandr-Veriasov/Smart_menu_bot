from __future__ import annotations

from dataclasses import dataclass

from bot.app.core.recipes_mode import RecipeMode


@dataclass(slots=True)
class RecipesStateData:
    """Нормализованное состояние списка рецептов, хранимое в Redis."""

    recipes_page: int = 0
    recipes_total_pages: int = 1
    category_slug: str = "recipes"
    category_id: int = 0
    mode: str = RecipeMode.SHOW.value
    category_name: str | None = None
    list_title: str | None = None
    search_items: list[dict[str, int | str]] | None = None
    search: dict[str, str] | None = None

    @property
    def display_title(self) -> str:
        """Возвращает заголовок списка рецептов для интерфейса."""
        if self.list_title:
            return self.list_title
        return f'Выберите рецепт из категории «{self.category_name or "категория"}»:'

    def with_pagination(
        self,
        *,
        page: int,
        total_pages: int,
        category_slug: str,
        mode: RecipeMode,
    ) -> RecipesStateData:
        """Возвращает обновлённый state после смены страницы списка рецептов."""
        return RecipesStateData(
            recipes_page=page,
            recipes_total_pages=total_pages,
            category_slug=category_slug,
            category_id=self.category_id,
            mode=mode.value,
            category_name=self.category_name,
            list_title=self.list_title,
            search_items=self.search_items,
            search=self.search,
        )

    @classmethod
    def from_dict(cls, data: dict | None) -> RecipesStateData:
        """Строит state из Redis-словаря с безопасными значениями по умолчанию."""
        if not isinstance(data, dict):
            return cls()
        return cls(
            recipes_page=int(data.get("recipes_page", 0) or 0),
            recipes_total_pages=int(data.get("recipes_total_pages", 1) or 1),
            category_slug=str(data.get("category_slug", "recipes") or "recipes"),
            category_id=int(data.get("category_id", 0) or 0),
            mode=str(data.get("mode", RecipeMode.SHOW.value) or RecipeMode.SHOW.value),
            category_name=str(data["category_name"]) if data.get("category_name") is not None else None,
            list_title=str(data["list_title"]) if data.get("list_title") is not None else None,
            search_items=data.get("search_items") if isinstance(data.get("search_items"), list) else None,
            search=data.get("search") if isinstance(data.get("search"), dict) else None,
        )

    def to_dict(self) -> dict[str, object]:
        """Преобразует state в словарь для записи в Redis."""
        data: dict[str, object] = {
            "recipes_page": self.recipes_page,
            "recipes_total_pages": self.recipes_total_pages,
            "category_slug": self.category_slug,
            "category_id": self.category_id,
            "mode": self.mode,
        }
        if self.category_name is not None:
            data["category_name"] = self.category_name
        if self.list_title is not None:
            data["list_title"] = self.list_title
        if self.search_items is not None:
            data["search_items"] = self.search_items
        if self.search is not None:
            data["search"] = self.search
        return data

    @classmethod
    def for_category(
        cls,
        *,
        category_name: str,
        category_slug: str,
        category_id: int,
        mode: RecipeMode,
        recipes_total_pages: int,
    ) -> RecipesStateData:
        """Создаёт state для пользовательской категории рецептов."""
        return cls(
            recipes_page=0,
            recipes_total_pages=recipes_total_pages,
            category_name=category_name,
            category_slug=category_slug,
            category_id=category_id,
            mode=mode.value,
        )

    @classmethod
    def for_book(
        cls,
        *,
        category_name: str,
        category_slug: str,
        recipes_total_pages: int,
        search_items: list[dict[str, int | str]],
    ) -> RecipesStateData:
        """Создаёт state для книги рецептов."""
        return cls(
            recipes_page=0,
            recipes_total_pages=recipes_total_pages,
            category_name=category_name,
            category_slug=f"book_{category_slug}",
            category_id=0,
            mode=RecipeMode.SHOW.value,
            list_title=f"📚 Книга рецептов • {category_name}",
            search_items=search_items,
        )

    @classmethod
    def for_search(
        cls,
        *,
        search_type: str,
        query: str,
        recipes_total_pages: int,
        search_items: list[dict[str, int | str]],
    ) -> RecipesStateData:
        """Создаёт state для поисковой выдачи."""
        search_label = "названию" if search_type == "title" else "ингредиенту"
        return cls(
            recipes_page=0,
            recipes_total_pages=recipes_total_pages,
            category_slug="search",
            category_id=0,
            mode=RecipeMode.SEARCH.value,
            list_title=f"Результаты поиска по {search_label}: «{query}»",
            search_items=search_items,
            search={"type": search_type, "query": query},
        )
