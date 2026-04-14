"""008 — Add audio_filename_from_justin setting

Revision ID: 008_add_audio_filename_from_justin
Revises: 007_add_audio_track_presets
Create Date: 2026-04-14
"""

from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "008_add_audio_filename_from_justin"
down_revision: Union[str, None] = "007_add_audio_track_presets"


def upgrade() -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    op.execute(
        sa.text(
            "INSERT OR IGNORE INTO user_settings (key, value, updated_at) "
            "VALUES (:key, :value, :ts)"
        ).bindparams(key="audio_filename_from_justin", value="true", ts=now)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM user_settings WHERE key = :key").bindparams(
            key="audio_filename_from_justin"
        )
    )
