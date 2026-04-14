"""
Audio Recording — Recorder Factory

Returns the correct ``AudioRecorder`` implementation for the current platform.
"""

from __future__ import annotations

import sys

from .base import AudioRecorder


def create_recorder(device_name: str) -> AudioRecorder:
    """Create a platform-appropriate recorder instance.

    - **Windows** → ``AsioRecorder`` (ASIO backend via dedicated COM STA thread)
    - **macOS**   → ``CoreAudioRecorder`` (CoreAudio via sounddevice default)
    """
    if sys.platform == "win32":
        from .asio_recorder import AsioRecorder

        return AsioRecorder(device_name)

    if sys.platform == "darwin":
        from .coreaudio_recorder import CoreAudioRecorder

        return CoreAudioRecorder(device_name)

    raise RuntimeError(f"Unsupported platform: {sys.platform}")
