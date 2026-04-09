"""004 — Add output_folder_time_format setting

Revision ID: 004_add_time_format
Revises: 003_user_settings
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_add_time_format"
down_revision: Union[str, None] = "003_user_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    op.execute(
        sa.text(
            "INSERT OR IGNORE INTO user_settings (key, value, updated_at) "
            "VALUES (:key, :value, :ts)"
        ).bindparams(key="output_folder_time_format", value="filename[7:13]", ts=now)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM user_settings WHERE key = :key").bindparams(
            key="output_folder_time_format"
        )
    )
