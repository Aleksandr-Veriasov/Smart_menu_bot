"""add pipeline_jobs

Revision ID: a1b2c3d4e5f6
Revises: 9c1f2a3b4d5e
Create Date: 2026-06-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "9c1f2a3b4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    job_status = postgresql.ENUM(
        "pending",
        "running",
        "done",
        "failed",
        name="pipeline_job_status",
        create_type=False,
    )
    job_status.create(bind, checkfirst=True)

    op.create_table(
        "pipeline_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pipeline_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column(
            "status",
            job_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("progress_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pipeline_id", name="uq_pipeline_jobs_pipeline_id"),
    )
    op.create_index("ix_pipeline_jobs_pipeline_id", "pipeline_jobs", ["pipeline_id"], unique=True)
    op.create_index(
        "ix_pipeline_jobs_status_retry",
        "pipeline_jobs",
        ["status", "next_retry_at"],
        unique=False,
    )
    op.create_index("ix_pipeline_jobs_locked_until", "pipeline_jobs", ["locked_until"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_index("ix_pipeline_jobs_locked_until", table_name="pipeline_jobs")
    op.drop_index("ix_pipeline_jobs_status_retry", table_name="pipeline_jobs")
    op.drop_index("ix_pipeline_jobs_pipeline_id", table_name="pipeline_jobs")
    op.drop_table("pipeline_jobs")

    sa.Enum(name="pipeline_job_status").drop(bind, checkfirst=True)
