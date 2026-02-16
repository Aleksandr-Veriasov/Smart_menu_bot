from enum import IntEnum


class DeleteRecipeState(IntEnum):
    CONFIRM_DELETE = 10


class SaveRecipeState(IntEnum):
    CHOOSE_CATEGORY = 20


class SearchRecipeState(IntEnum):
    CHOOSE_TYPE = 30
    WAIT_TITLE = 31
    WAIT_INGREDIENT = 32
