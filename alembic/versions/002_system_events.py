"""002 — Create system_events table

Revision ID: 002_system_events
Revises: 001_tracked_files
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_system_events"
down_revision: Union[str, None] = "001_tracked_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
    )
    op.create_index("ix_system_events_timestamp", "system_events", ["timestamp"])
    op.create_index("ix_system_events_level", "system_events", ["level"])
    op.create_index("ix_system_events_event_type", "system_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_system_events_event_type")
    op.drop_index("ix_system_events_level")
    op.drop_index("ix_system_events_timestamp")
    op.drop_table("system_events")
