"""replace pipeline_id with message_id composite key

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop synthetic pipeline_id; add message_id + composite unique (chat_id, message_id)."""
    op.drop_index("ix_pipeline_jobs_pipeline_id", table_name="pipeline_jobs")
    op.drop_constraint("uq_pipeline_jobs_pipeline_id", "pipeline_jobs", type_="unique")
    op.drop_column("pipeline_jobs", "pipeline_id")

    op.add_column(
        "pipeline_jobs",
        sa.Column("message_id", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.alter_column("pipeline_jobs", "message_id", server_default=None)

    op.create_unique_constraint("uq_pipeline_jobs_chat_message", "pipeline_jobs", ["chat_id", "message_id"])
    op.create_index("ix_pipeline_jobs_chat_message", "pipeline_jobs", ["chat_id", "message_id"], unique=True)


def downgrade() -> None:
    """Restore pipeline_id synthetic key."""
    op.drop_index("ix_pipeline_jobs_chat_message", table_name="pipeline_jobs")
    op.drop_constraint("uq_pipeline_jobs_chat_message", "pipeline_jobs", type_="unique")
    op.drop_column("pipeline_jobs", "message_id")

    op.add_column(
        "pipeline_jobs",
        sa.Column("pipeline_id", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.alter_column("pipeline_jobs", "pipeline_id", server_default=None)

    op.create_unique_constraint("uq_pipeline_jobs_pipeline_id", "pipeline_jobs", ["pipeline_id"])
    op.create_index("ix_pipeline_jobs_pipeline_id", "pipeline_jobs", ["pipeline_id"], unique=True)
