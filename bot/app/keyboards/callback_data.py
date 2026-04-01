from bot.app.core.recipes_mode import RecipeMode


class CallbackData:
    @staticmethod
    def random_recipe(category_slug: str) -> str:
        return f"{category_slug}_random"

    @staticmethod
    def category_mode(category_slug: str, mode: RecipeMode, pipeline_id: int = 0) -> str:
        if mode is RecipeMode.SAVE:
            return f"{category_slug}_{mode.value}:{pipeline_id}"
        return f"{category_slug}_{mode.value}"

    @staticmethod
    def recipe_choice(category_slug: str, mode: str, recipe_id: int) -> str:
        return f"{category_slug}_{mode}_{recipe_id}"

    @staticmethod
    def pagination(direction: str, page: int) -> str:
        return f"{direction}_{page}"

    @staticmethod
    def recipe_delete(recipe_id: int) -> str:
        return f"delete_recipe_{recipe_id}"

    @staticmethod
    def recipe_share(recipe_id: int) -> str:
        return f"share_recipe_{recipe_id}"

    @staticmethod
    def share_back(recipe_id: int) -> str:
        return f"share_back_{recipe_id}"

    @staticmethod
    def recipe_add(recipe_id: int) -> str:
        return f"add_recipe:{recipe_id}"

    @staticmethod
    def save_recipe(pipeline_id: int) -> str:
        return f"save_recipe:{pipeline_id}"

    @staticmethod
    def cancel_save_recipe(pipeline_id: int | None = None) -> str:
        return "cancel_save_recipe" if pipeline_id is None else f"cancel_save_recipe:{pipeline_id}"

    @staticmethod
    def book_category(category_slug: str) -> str:
        return f"bookcat_{category_slug}"

    @staticmethod
    def url_pick(sid: str, recipe_id: int) -> str:
        return f"urlpick:{sid}:{recipe_id}"

    @staticmethod
    def url_add(sid: str, recipe_id: int) -> str:
        return f"urladd:{sid}:{recipe_id}"

    @staticmethod
    def url_list(sid: str) -> str:
        return f"urllist:{sid}"

    @staticmethod
    def url_add_category(sid: str, recipe_id: int, slug: str) -> str:
        return f"urladdcat:{sid}:{recipe_id}:{slug}"
