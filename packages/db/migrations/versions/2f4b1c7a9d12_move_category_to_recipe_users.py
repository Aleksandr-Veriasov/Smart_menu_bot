"""move category to recipe_users

Revision ID: 2f4b1c7a9d12
Revises: 8c1a2f6d9e3b
Create Date: 2025-09-17 18:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2f4b1c7a9d12"
down_revision: str | Sequence[str] | None = "8c1a2f6d9e3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "recipe_users",
        sa.Column("category_id", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE recipe_users ru
            SET category_id = r.category_id
            FROM recipes r
            WHERE ru.recipe_id = r.id
            """
        )
    )
    with op.batch_alter_table("recipe_users") as batch_op:
        batch_op.alter_column("category_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "recipe_users_category_id_fkey",
            "categories",
            ["category_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_recipe_users_category_id",
        "recipe_users",
        ["category_id"],
        unique=False,
    )

    op.drop_index("ix_recipes_category_id", table_name="recipes")
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.drop_constraint("recipes_category_id_fkey", type_="foreignkey")
        batch_op.drop_column("category_id")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.add_column(sa.Column("category_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "recipes_category_id_fkey",
            "categories",
            ["category_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_recipes_category_id", "recipes", ["category_id"], unique=False)
    op.execute(
        sa.text(
            """
            UPDATE recipes r
            SET category_id = sub.category_id
            FROM (
                SELECT recipe_id, MIN(category_id) AS category_id
                FROM recipe_users
                GROUP BY recipe_id
            ) AS sub
            WHERE r.id = sub.recipe_id
            """
        )
    )
    op.drop_index("ix_recipe_users_category_id", table_name="recipe_users")
    with op.batch_alter_table("recipe_users") as batch_op:
        batch_op.drop_constraint("recipe_users_category_id_fkey", type_="foreignkey")
        batch_op.drop_column("category_id")
