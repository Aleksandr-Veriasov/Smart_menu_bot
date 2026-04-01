from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PipelineDraft:
    """Нормализованный черновик рецепта для video pipeline."""

    status: str | None = None
    original_url: str | None = None
    video_file_id: str | None = None
    save_error: str | None = None
    title: str | None = None
    recipe: str | None = None
    ingredients: str | list[str] | None = None
    recipe_id: int | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> PipelineDraft | None:
        """Строит PipelineDraft из Redis-словаря."""
        if not isinstance(data, dict):
            return None
        recipe_id = data.get("recipe_id")
        normalized_recipe_id = int(recipe_id) if isinstance(recipe_id, int | str) and str(recipe_id).isdigit() else None
        ingredients = data.get("ingredients")
        normalized_ingredients = ingredients if isinstance(ingredients, str | list) else None
        return cls(
            status=str(data["status"]) if data.get("status") is not None else None,
            original_url=str(data["original_url"]) if data.get("original_url") is not None else None,
            video_file_id=str(data["video_file_id"]) if data.get("video_file_id") is not None else None,
            save_error=str(data["save_error"]) if data.get("save_error") is not None else None,
            title=str(data["title"]) if data.get("title") is not None else None,
            recipe=str(data["recipe"]) if data.get("recipe") is not None else None,
            ingredients=normalized_ingredients,
            recipe_id=normalized_recipe_id,
        )

    def to_dict(self) -> dict[str, object]:
        """Преобразует черновик в словарь для записи в Redis."""
        data: dict[str, object] = {}
        if self.status is not None:
            data["status"] = self.status
        if self.original_url is not None:
            data["original_url"] = self.original_url
        if self.video_file_id is not None:
            data["video_file_id"] = self.video_file_id
        if self.save_error is not None:
            data["save_error"] = self.save_error
        if self.title is not None:
            data["title"] = self.title
        if self.recipe is not None:
            data["recipe"] = self.recipe
        if self.ingredients is not None:
            data["ingredients"] = self.ingredients
        if self.recipe_id is not None:
            data["recipe_id"] = self.recipe_id
        return data
