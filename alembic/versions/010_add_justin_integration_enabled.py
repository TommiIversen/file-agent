"""010 — Add justin_integration_enabled setting

Revision ID: 010_add_justin_integration_enabled
Revises: 009_add_session_time
Create Date: 2026-05-22
"""

from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "010_add_justin_integration_enabled"
down_revision: Union[str, None] = "009_add_session_time"


def upgrade() -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    op.execute(
        sa.text(
            "INSERT OR IGNORE INTO user_settings (key, value, updated_at) "
            "VALUES (:key, :value, :ts)"
        ).bindparams(key="justin_integration_enabled", value="true", ts=now)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM user_settings WHERE key = :key").bindparams(
            key="justin_integration_enabled"
        )
    )
