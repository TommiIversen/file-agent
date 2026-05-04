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


def _find_coreaudio_device(
    name: str,
    *,
    retry_with_reinit: bool = True,
    max_attempts: int = 6,
    delay_s: float = 1.0,
) -> int:
    """Find device index by name.

    After a USB reconnect, PortAudio may need several reinit cycles before
    the device is visible in its enumeration.  We retry up to
    *max_attempts* times with a *delay_s* pause + PortAudio reinit between
    each attempt.
    """
    import time

    import sounddevice as sd

    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and name.lower() in dev["name"].lower():
            return i

    if not retry_with_reinit:
        raise RuntimeError(f"No audio input device matching '{name}' found")

    for attempt in range(1, max_attempts + 1):
        logger.warning(
            "Device '%s' not found — reinit PortAudio attempt %d/%d (wait %.1fs)",
            name,
            attempt,
            max_attempts,
            delay_s,
        )
        time.sleep(delay_s)
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            logger.debug("PortAudio reinit failed on attempt %d", attempt, exc_info=True)
            continue

        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0 and name.lower() in dev["name"].lower():
                logger.info("Device '%s' found after %d reinit attempt(s)", name, attempt)
                return i

    raise RuntimeError(f"No audio input device matching '{name}' found")


class CoreAudioRecorder(AudioRecorder):
    """macOS CoreAudio recorder — thin subclass of AudioRecorder.

    CoreAudio doesn't support ASIO-style channel selectors.  We open
    ``max(hw_channels) + 1`` channels and remap in the callback so only
    the requested channels reach the writer thread.
    """

    def __init__(self, device_name: str, *, reinit_portaudio: bool = False) -> None:
        super().__init__(device_name)
        self._device_index: Optional[int] = None
        # Number of HW channels to open (may be more than len(_channel_selectors))
        self._hw_channels: int = 0

        if reinit_portaudio:
            self._reinitialize_portaudio()
        else:
            # Only probe mic permission on first init — not during recovery.
            # The probe opens/closes a stream which can destabilise PortAudio
            # right after a reinit.
            self._request_mic_permission(device_name)

    # ── PortAudio lifecycle ────────────────────────────────────

    @staticmethod
    def _reinitialize_portaudio() -> None:
        """Reset PortAudio after device loss.

        After a USB device is unplugged, PortAudio's internal state can
        become corrupt (PaErrorCode -9986).  Re-initialising clears it.
        """
        try:
            import sounddevice as sd

            sd._terminate()
            sd._initialize()
            logger.info("PortAudio re-initialized after device loss")
        except Exception:
            logger.warning("PortAudio re-initialization failed", exc_info=True)

    # ── Subclass hooks ─────────────────────────────────────────

    @staticmethod
    def _request_mic_permission(device_name: str) -> None:
        """Open and immediately close a stream to trigger macOS mic permission.

        macOS shows the permission dialog the first time an input stream
        is opened.  Doing it at init avoids a surprise prompt during a
        live recording session.
        """
        try:
            import sounddevice as sd

            idx = _find_coreaudio_device(device_name)
            stream = sd.InputStream(device=idx, channels=1)
            stream.start()
            stream.stop()
            stream.close()
            logger.debug("Microphone permission pre-requested for '%s'", device_name)
        except Exception:
            logger.debug("Mic permission probe skipped for '%s'", device_name, exc_info=True)

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
            finished_callback=self._on_stream_finished,
        )
        self._stream.start()
        return self._stream.samplerate

    def _close_stream(self) -> None:
        if self._stream:
            try:
                self._stream.stop()
            except Exception:
                logger.debug("stream.stop() failed (device may be gone)", exc_info=True)
            try:
                self._stream.close()
            except Exception:
                logger.debug("stream.close() failed (device may be gone)", exc_info=True)
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
