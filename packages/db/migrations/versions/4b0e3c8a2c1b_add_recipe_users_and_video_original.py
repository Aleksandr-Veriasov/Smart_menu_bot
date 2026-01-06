"""add recipe_users, video original url, last used at

Revision ID: 4b0e3c8a2c1b
Revises: dc078ab58d48
Create Date: 2025-09-17 14:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4b0e3c8a2c1b"
down_revision: str | Sequence[str] | None = "dc078ab58d48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "videos",
        sa.Column("original_url", sa.String(length=2000), nullable=True),
    )
    op.add_column(
        "recipes",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "recipe_users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "user_id", name="uq_recipe_user"),
    )
    op.create_index(
        "ix_recipe_users_recipe_id",
        "recipe_users",
        ["recipe_id"],
        unique=False,
    )
    op.create_index(
        "ix_recipe_users_user_id",
        "recipe_users",
        ["user_id"],
        unique=False,
    )
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.drop_constraint("recipes_user_id_fkey", type_="foreignkey")
        batch_op.alter_column("user_id", existing_type=sa.BigInteger(), nullable=True)
        batch_op.create_foreign_key(
            "recipes_user_id_fkey",
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.drop_constraint("recipes_user_id_fkey", type_="foreignkey")
        batch_op.alter_column("user_id", existing_type=sa.BigInteger(), nullable=False)
        batch_op.create_foreign_key(
            "recipes_user_id_fkey",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.drop_index("ix_recipe_users_user_id", table_name="recipe_users")
    op.drop_index("ix_recipe_users_recipe_id", table_name="recipe_users")
    op.drop_table("recipe_users")
    op.drop_column("recipes", "last_used_at")
    op.drop_column("videos", "original_url")
