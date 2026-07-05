"""add persona and source health tracking

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("persona", sa.String(length=500), nullable=True, server_default=""))
    op.add_column("sources", sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "last_error")
    op.drop_column("sources", "last_fetched_at")
    op.drop_column("sources", "persona")
