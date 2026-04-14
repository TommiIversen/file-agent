"""
Audio Recording — Domain Commands (CQRS)
"""

from dataclasses import dataclass

from app.core.cqrs.command import Command


@dataclass
class StartAudioRecordingCommand(Command):
    """Start audio recording with the given filename prefix.

    The track config, device, and samplerate come from user settings.
    ``filename_prefix`` is typically obtained from Justin API.
    """

    filename_prefix: str
    session_id: str


@dataclass
class StopAudioRecordingCommand(Command):
    """Stop the active audio recording session."""

    pass
