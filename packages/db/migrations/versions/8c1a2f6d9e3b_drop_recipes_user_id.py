"""move recipe user_id to recipe_users and drop column

Revision ID: 8c1a2f6d9e3b
Revises: 4b0e3c8a2c1b
Create Date: 2025-09-17 16:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c1a2f6d9e3b"
down_revision: str | Sequence[str] | None = "4b0e3c8a2c1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        sa.text(
            """
            INSERT INTO recipe_users (recipe_id, user_id)
            SELECT r.id, r.user_id
            FROM recipes r
            WHERE r.user_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM recipe_users ru
                  WHERE ru.recipe_id = r.id AND ru.user_id = r.user_id
              )
            """
        )
    )
    op.drop_index("ix_recipes_user_id", table_name="recipes")
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.drop_constraint("recipes_user_id_fkey", type_="foreignkey")
        batch_op.drop_column("user_id")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            "recipes_user_id_fkey",
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_recipes_user_id", "recipes", ["user_id"], unique=False)
    op.execute(
        sa.text(
            """
            UPDATE recipes r
            SET user_id = sub.user_id
            FROM (
                SELECT recipe_id, MIN(user_id) AS user_id
                FROM recipe_users
                GROUP BY recipe_id
            ) AS sub
            WHERE r.id = sub.recipe_id
            """
        )
    )
