"""
Audio Recording — Domain Commands (CQRS)
"""

from dataclasses import dataclass
from typing import Optional

from app.core.cqrs.command import Command


@dataclass
class StartAudioRecordingCommand(Command):
    """Start audio recording with the given filename stem.

    ``filename_stem`` is typically the full filename from Justin API
    (e.g. ``"260414_151304_KAM_1"``).  When ``channel_name`` is provided,
    the recorder replaces the channel portion with each track label —
    making the approach naming-convention-agnostic.

    When ``channel_name`` is None (local-timestamp fallback), the
    recorder falls back to ``{stem}_{label}.wav``.
    """

    filename_stem: str
    channel_name: Optional[str]
    session_id: str


@dataclass
class StopAudioRecordingCommand(Command):
    """Stop the active audio recording session."""

    pass
