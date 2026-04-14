"""
Audio Recording — Recorder Factory

Returns the correct ``AudioRecorder`` implementation for the current platform.
"""

from __future__ import annotations

import sys

from .base import AudioRecorder
from .models import DeviceInfo


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


def list_available_devices() -> list[DeviceInfo]:
    """List audio input devices without requiring a configured recorder."""
    if sys.platform == "win32":
        from .asio_recorder import _query_asio_devices

        return _query_asio_devices()

    if sys.platform == "darwin":
        from .coreaudio_recorder import _query_coreaudio_devices

        return _query_coreaudio_devices()

    return []
