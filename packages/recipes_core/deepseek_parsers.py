import re

from pydantic import BaseModel, Field


class RecipeExtraction(BaseModel):
    title: str = Field(default="Не указано")
    instructions_text: str = Field(default="Не указан")  # текст с нумерацией
    ingredients_text: str = Field(default="Не указаны")  # текст с маркерами
    raw: str = ""  # сырой ответ (для дебага)

    @property
    def ingredients_list(self) -> list[str]:
        return [
            re.sub(r"^[-*]\s*", "", line).strip()
            for line in self.ingredients_text.splitlines()
            if line.strip() and re.match(r"^[-*]\s*", line.strip())
        ]


def parse_llm_answer(content: str) -> RecipeExtraction:
    """
    Парсим формат:
    Название рецепта: ...
    Рецепт:
    1. ...
    Ингредиенты:
    - ...
    """
    lines = [line.strip() for line in (content or "").splitlines()]
    title = ""
    rec = []
    ing = []

    mode = None  # 'recipe' | 'ingredients' | None
    for line in lines:
        if not line:
            continue
        if line.startswith("Название рецепта:"):
            title = line.split(":", 1)[1].strip()
            mode = None
            continue
        if line.startswith("Рецепт:"):
            mode = "recipe"
            tail = line.replace("Рецепт:", "", 1).strip()
            if tail:
                rec.append(tail)
            continue
        if line.startswith("Ингредиенты:"):
            mode = "ingredients"
            tail = line.replace("Ингредиенты:", "", 1).strip()
            if tail:
                ing.append(tail)
            continue

        if mode == "recipe":
            # принимаем '1. ...' или просто строку
            rec.append(line)
        elif mode == "ingredients":
            # принимаем '- ...' или '* ...' или просто строку
            if not re.match(r"^[-*]\s+", line):
                line = f"- {line}"
            ing.append(line)

    return RecipeExtraction(
        title=title or "Не указано",
        instructions_text="\n".join(rec) or "Не указан",
        ingredients_text="\n".join(ing) or "Не указаны",
        raw=content or "",
    )
