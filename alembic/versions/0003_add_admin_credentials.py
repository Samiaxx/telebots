"""add admin credentials to bot_settings

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bot_settings", sa.Column("admin_username", sa.String(length=255), nullable=True))
    op.add_column("bot_settings", sa.Column("admin_password_hash", sa.String(length=255), nullable=True))
    op.add_column("bot_settings", sa.Column("admin_password_salt", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("bot_settings", "admin_password_salt")
    op.drop_column("bot_settings", "admin_password_hash")
    op.drop_column("bot_settings", "admin_username")
