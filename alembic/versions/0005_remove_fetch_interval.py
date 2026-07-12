"""remove unused fetch_interval_minutes from sources

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-09

This field was never actually wired into the scheduler — actual fetch/post
timing is fully controlled by each Schedule's cron expression (a Source can
even be linked to multiple Schedules with different frequencies), so a
single "interval" on the Source itself never mapped to real behavior. It was
confusing UI, not a real setting — removing it rather than leaving it as
dead config.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("sources", "fetch_interval_minutes")


def downgrade() -> None:
    op.add_column("sources", sa.Column("fetch_interval_minutes", sa.Integer(), nullable=False, server_default="60"))
