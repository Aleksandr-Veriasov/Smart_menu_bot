from pydantic import BaseModel


class AdminStatsRead(BaseModel):
    users_count: int
    recipes_count: int
    broadcasts_count: int
    active_broadcasts_count: int
