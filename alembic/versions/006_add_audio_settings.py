"""006 — Add audio recording settings

Revision ID: 006_add_audio_settings
Revises: 005_add_brand_name
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006_add_audio_settings"
down_revision: Union[str, None] = "005_add_brand_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AUDIO_DEFAULTS = [
    ("audio_recording_enabled", "false"),
    ("audio_device_name", ""),
    ("audio_sample_rate", "48000"),
    ("audio_tracks", "[]"),
]


def upgrade() -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    for key, value in _AUDIO_DEFAULTS:
        op.execute(
            sa.text(
                "INSERT OR IGNORE INTO user_settings (key, value, updated_at) "
                "VALUES (:key, :value, :ts)"
            ).bindparams(key=key, value=value, ts=now)
        )


def downgrade() -> None:
    for key, _ in _AUDIO_DEFAULTS:
        op.execute(
            sa.text("DELETE FROM user_settings WHERE key = :key").bindparams(
                key=key
            )
        )
