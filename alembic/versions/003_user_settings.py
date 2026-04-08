"""003 — Create user_settings table with sane defaults

Revision ID: 003_user_settings
Revises: 002_system_events
Create Date: 2026-04-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_user_settings"
down_revision: Union[str, None] = "002_system_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Sane defaults so the app works out-of-the-box without an env file.
# source_directory and destination_directory are empty — user configures via UI.
_DEFAULT_SETTINGS: list[tuple[str, str]] = [
    ("source_directory", ""),
    ("destination_directory", ""),
    ("network_share_url", ""),
    ("enable_auto_mount", "false"),
    ("macos_mount_point", ""),
    ("tally_light_switch_ip", ""),
    ("output_folder_template_enabled", "false"),
    ("output_folder_rules", ""),
    ("output_folder_default_category", "OTHER"),
    ("output_folder_date_format", "filename[0:6]"),
    ("max_concurrent_copies", "7"),
    ("justin_auto_stop_minutes", "0"),
]


def upgrade() -> None:
    # Use raw SQL with IF NOT EXISTS to avoid conflict when create_schema()
    # has already created the table (belt-and-suspenders pattern).
    op.execute(sa.text(
        "CREATE TABLE IF NOT EXISTS user_settings ("
        "  key TEXT PRIMARY KEY,"
        "  value TEXT NOT NULL,"
        "  updated_at TEXT NOT NULL"
        ")"
    ))

    # Seed defaults
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    for key, value in _DEFAULT_SETTINGS:
        op.execute(
            sa.text(
                "INSERT OR IGNORE INTO user_settings (key, value, updated_at) "
                "VALUES (:key, :value, :ts)"
            ).bindparams(key=key, value=value, ts=now)
        )


def downgrade() -> None:
    op.drop_table("user_settings")
