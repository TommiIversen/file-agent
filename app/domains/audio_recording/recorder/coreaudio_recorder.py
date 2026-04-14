"""
Audio Recording — CoreAudio Recorder (macOS)

Uses ``sounddevice`` with the default CoreAudio host API.
No dedicated ASIO thread required — CoreAudio manages its own dispatch.

All shared recording machinery lives in the base class.  This file only provides:
- CoreAudio device lookup
- Stream open/close (direct calls, no dedicated thread)
- Channel remapping in the callback (CoreAudio doesn't have ASIO-style selectors)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from .base import AudioRecorder
from .models import AudioTrack, DeviceInfo

logger = logging.getLogger(__name__)


def _query_coreaudio_devices() -> list[DeviceInfo]:
    import sounddevice as sd

    host_apis = sd.query_hostapis()
    devices: list[DeviceInfo] = []
    for i, dev in enumerate(sd.query_devices()):
        api_name = host_apis[dev["hostapi"]]["name"]
        if dev["max_input_channels"] > 0:
            devices.append(
                DeviceInfo(
                    index=i,
                    name=dev["name"],
                    max_input_channels=dev["max_input_channels"],
                    max_output_channels=dev["max_output_channels"],
                    default_samplerate=int(dev["default_samplerate"]),
                    host_api=api_name,
                )
            )
    return devices


def _find_coreaudio_device(name: str) -> int:
    import sounddevice as sd

    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and name.lower() in dev["name"].lower():
            return i
    raise RuntimeError(f"No audio input device matching '{name}' found")


class CoreAudioRecorder(AudioRecorder):
    """macOS CoreAudio recorder — thin subclass of AudioRecorder.

    CoreAudio doesn't support ASIO-style channel selectors.  We open
    ``max(hw_channels) + 1`` channels and remap in the callback so only
    the requested channels reach the writer thread.
    """

    def __init__(self, device_name: str) -> None:
        super().__init__(device_name)
        self._device_index: Optional[int] = None
        # Number of HW channels to open (may be more than len(_channel_selectors))
        self._hw_channels: int = 0

    # ── Subclass hooks ─────────────────────────────────────────

    def _resolve_device(self) -> None:
        self._device_index = _find_coreaudio_device(self._device_name)

    def _open_stream(self) -> float:
        import sounddevice as sd

        # CoreAudio doesn't have channel selectors — open enough channels
        # to cover the highest requested HW channel, then remap in callback.
        self._hw_channels = max(self._channel_selectors) + 1

        self._stream = sd.InputStream(
            device=self._device_index,
            channels=self._hw_channels,
            samplerate=self._samplerate,
            callback=self._coreaudio_callback,
        )
        self._stream.start()
        return self._stream.samplerate

    def _close_stream(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def list_devices(self) -> list[DeviceInfo]:
        return _query_coreaudio_devices()

    # ── Callback with channel remapping ────────────────────────

    def _coreaudio_callback(
        self, indata: np.ndarray, frames: int, time_info: Any, status: Any
    ) -> None:
        """Extract only the configured channels before passing to the shared callback.

        CoreAudio delivers all ``_hw_channels`` columns.  We slice to
        ``_channel_selectors`` so the writer thread sees the same layout
        as ASIO (one column per configured channel, in order).
        """
        remapped = indata[:, self._channel_selectors]
        self._callback_fn(remapped, frames, time_info, status)
