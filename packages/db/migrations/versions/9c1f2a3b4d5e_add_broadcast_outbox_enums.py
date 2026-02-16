"""add broadcast outbox (enums)

Revision ID: 9c1f2a3b4d5e
Revises: 2f4b1c7a9d12
Create Date: 2026-02-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9c1f2a3b4d5e"
down_revision: str | Sequence[str] | None = "2f4b1c7a9d12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    campaign_status = postgresql.ENUM(
        "draft",
        "queued",
        "running",
        "paused",
        "completed",
        "cancelled",
        "failed",
        name="broadcast_campaign_status",
        create_type=False,
    )
    audience_type = postgresql.ENUM(
        "all_users",
        name="broadcast_audience_type",
        create_type=False,
    )
    message_status = postgresql.ENUM(
        "pending",
        "sending",
        "sent",
        "retry",
        "failed",
        name="broadcast_message_status",
        create_type=False,
    )

    # Create enums first (PostgreSQL).
    campaign_status.create(bind, checkfirst=True)
    audience_type.create(bind, checkfirst=True)
    message_status.create(bind, checkfirst=True)

    op.create_table(
        "broadcast_campaigns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            campaign_status,
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column(
            "audience_type",
            audience_type,
            server_default=sa.text("'all_users'"),
            nullable=False,
        ),
        sa.Column("audience_params_json", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("parse_mode", sa.String(length=16), server_default=sa.text("'HTML'"), nullable=False),
        sa.Column("disable_web_page_preview", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("reply_markup_json", sa.Text(), nullable=True),
        sa.Column("photo_file_id", sa.String(length=300), nullable=True),
        sa.Column("photo_url", sa.String(length=2000), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("outbox_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_recipients", sa.Integer(), nullable=True),
        sa.Column("sent_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_broadcast_campaigns_status", "broadcast_campaigns", ["status"], unique=False)
    op.create_index("ix_broadcast_campaigns_scheduled_at", "broadcast_campaigns", ["scheduled_at"], unique=False)

    op.create_table(
        "broadcast_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey("broadcast_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            message_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "chat_id", name="uq_broadcast_campaign_chat"),
    )
    op.create_index("ix_broadcast_messages_campaign_id", "broadcast_messages", ["campaign_id"], unique=False)
    op.create_index("ix_broadcast_messages_status", "broadcast_messages", ["status"], unique=False)
    op.create_index("ix_broadcast_messages_next_retry_at", "broadcast_messages", ["next_retry_at"], unique=False)
    op.create_index("ix_broadcast_messages_locked_until", "broadcast_messages", ["locked_until"], unique=False)
    op.create_index(
        "ix_broadcast_messages_status_next_retry_at",
        "broadcast_messages",
        ["status", "next_retry_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    op.drop_index("ix_broadcast_messages_status_next_retry_at", table_name="broadcast_messages")
    op.drop_index("ix_broadcast_messages_locked_until", table_name="broadcast_messages")
    op.drop_index("ix_broadcast_messages_next_retry_at", table_name="broadcast_messages")
    op.drop_index("ix_broadcast_messages_status", table_name="broadcast_messages")
    op.drop_index("ix_broadcast_messages_campaign_id", table_name="broadcast_messages")
    op.drop_table("broadcast_messages")

    op.drop_index("ix_broadcast_campaigns_scheduled_at", table_name="broadcast_campaigns")
    op.drop_index("ix_broadcast_campaigns_status", table_name="broadcast_campaigns")
    op.drop_table("broadcast_campaigns")

    sa.Enum(name="broadcast_message_status").drop(bind, checkfirst=True)
    sa.Enum(name="broadcast_audience_type").drop(bind, checkfirst=True)
    sa.Enum(name="broadcast_campaign_status").drop(bind, checkfirst=True)
