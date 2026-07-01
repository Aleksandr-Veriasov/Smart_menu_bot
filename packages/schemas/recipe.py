from decimal import Decimal


class IngredientLink:
    """DTO для создания/обновления связи рецепт-ингредиент."""

    __slots__ = ("ingredient_id", "quantity", "unit")

    def __init__(
        self,
        ingredient_id: int,
        quantity: Decimal | None = None,
        unit: str | None = None,
    ) -> None:
        self.ingredient_id = ingredient_id
        self.quantity = quantity
        self.unit = unit
