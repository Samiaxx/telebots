"""add gemini_api_key to bot_settings

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bot_settings", sa.Column("gemini_api_key", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("bot_settings", "gemini_api_key")
