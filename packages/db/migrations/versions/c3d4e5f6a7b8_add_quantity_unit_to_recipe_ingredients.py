"""add quantity and unit to recipe_ingredients

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recipe_ingredients", sa.Column("quantity", sa.Numeric(10, 3), nullable=True))
    op.add_column("recipe_ingredients", sa.Column("unit", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("recipe_ingredients", "unit")
    op.drop_column("recipe_ingredients", "quantity")
