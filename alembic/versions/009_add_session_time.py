"""009 — Add session_time column to tracked_files

Revision ID: 009_add_session_time
Revises: 008_add_audio_filename_from_justin
Create Date: 2026-05-13
"""

from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "009_add_session_time"
down_revision: Union[str, None] = "008_add_audio_filename_from_justin"


def upgrade() -> None:
    op.add_column(
        "tracked_files",
        sa.Column("session_time", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tracked_files", "session_time")
