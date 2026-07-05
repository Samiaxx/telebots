"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("fetch_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("rewrite_style", sa.String(length=20), nullable=False, server_default="light"),
        sa.Column("language", sa.String(length=50), nullable=False, server_default="English"),
        sa.Column("topic_keywords", sa.String(length=500), nullable=True, server_default=""),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("telegram_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("cron_expression", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("rewritten_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "bot_settings",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("bot_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rewrite_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_rewrite_style", sa.String(length=20), nullable=False, server_default="light"),
        sa.Column("gemini_model", sa.String(length=100), nullable=False, server_default="gemini-1.5-flash"),
        sa.Column("max_posts_per_hour", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("include_images", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("bot_settings")
    op.drop_table("posts")
    op.drop_table("schedules")
    op.drop_table("channels")
    op.drop_table("sources")
