"""005 — Add brand_name setting

Revision ID: 005_add_brand_name
Revises: 004_add_time_format
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005_add_brand_name"
down_revision: Union[str, None] = "004_add_time_format"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    op.execute(
        sa.text(
            "INSERT OR IGNORE INTO user_settings (key, value, updated_at) "
            "VALUES (:key, :value, :ts)"
        ).bindparams(key="brand_name", value="Dr. Feta", ts=now)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM user_settings WHERE key = :key").bindparams(
            key="brand_name"
        )
    )
