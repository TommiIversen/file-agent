"""007 — Add audio track presets setting

Revision ID: 007_add_audio_track_presets
Revises: 006_add_audio_settings
Create Date: 2026-04-14
"""

from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "007_add_audio_track_presets"
down_revision: Union[str, None] = "006_add_audio_settings"

_STUDIE_6402_DEFAULT = (
    '[{"name":"6402","tracks":['
    '{"channels":[1,2],"label":"PGM_LR","mode":"stereo"},'
    '{"channels":[3],"label":"Mic1","mode":"mono"},'
    '{"channels":[4],"label":"Mic2","mode":"mono"},'
    '{"channels":[5],"label":"Mic3","mode":"mono"},'
    '{"channels":[6],"label":"Mic4","mode":"mono"},'
    '{"channels":[7],"label":"USB_mono","mode":"mono"},'
    '{"channels":[8],"label":"Mic_prod","mode":"mono"},'
    '{"channels":[9,10],"label":"DALET_LR","mode":"stereo"},'
    '{"channels":[11],"label":"Mic1_clean","mode":"mono"},'
    '{"channels":[12],"label":"Mic2_clean","mode":"mono"},'
    '{"channels":[13],"label":"Mic3_clean","mode":"mono"},'
    '{"channels":[14],"label":"Mic4_clean","mode":"mono"}'
    "]}]"
)


def upgrade() -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    op.execute(
        sa.text(
            "INSERT OR IGNORE INTO user_settings (key, value, updated_at) "
            "VALUES (:key, :value, :ts)"
        ).bindparams(key="audio_track_presets", value=_STUDIE_6402_DEFAULT, ts=now)
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM user_settings WHERE key = :key").bindparams(
            key="audio_track_presets"
        )
    )
