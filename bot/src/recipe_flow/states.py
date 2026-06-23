from aiogram.fsm.state import State, StatesGroup


class DeleteRecipeStates(StatesGroup):
    CONFIRM_DELETE = State()


class SaveRecipeStates(StatesGroup):
    CHOOSE_CATEGORY = State()


class SearchRecipeStates(StatesGroup):
    CHOOSE_TYPE = State()
    WAIT_TITLE = State()
    WAIT_INGREDIENT = State()
