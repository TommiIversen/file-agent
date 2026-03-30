"""001 — Create tracked_files table

Revision ID: 001_tracked_files
Revises: None
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_tracked_files"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tracked_files",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="Discovered"),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("destination_path", sa.Text(), nullable=True),
        sa.Column("copy_progress", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("bytes_copied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("copy_speed_mbps", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_info", sa.Text(), nullable=True),  # JSON
        sa.Column("discovered_at", sa.Text(), nullable=False),  # ISO datetime
        sa.Column("creation_time", sa.Text(), nullable=True),
        sa.Column("last_write_time", sa.Text(), nullable=True),
        sa.Column("started_copying_at", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.Column("failed_at", sa.Text(), nullable=True),
        sa.Column("space_error_at", sa.Text(), nullable=True),
        sa.Column("last_growth_check", sa.Text(), nullable=True),
        sa.Column("growth_rate_mbps", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("previous_file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("growth_stable_since", sa.Text(), nullable=True),
    )

    op.create_index("ix_tracked_files_file_path", "tracked_files", ["file_path"])
    op.create_index("ix_tracked_files_status", "tracked_files", ["status"])
    op.create_index("ix_tracked_files_discovered_at", "tracked_files", ["discovered_at"])
    op.create_index("ix_tracked_files_completed_at", "tracked_files", ["completed_at"])


def downgrade() -> None:
    op.drop_index("ix_tracked_files_completed_at", "tracked_files")
    op.drop_index("ix_tracked_files_discovered_at", "tracked_files")
    op.drop_index("ix_tracked_files_status", "tracked_files")
    op.drop_index("ix_tracked_files_file_path", "tracked_files")
    op.drop_table("tracked_files")
