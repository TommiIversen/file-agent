"""
Audio Recording — ASIO Recorder (Windows)

Based on the validated POC in ``scripts/audio-poc/recorder.py``.
COM STA requirement is enforced via a dedicated ``AsioThread`` that owns the
entire PortAudio/ASIO lifecycle.

All shared recording machinery (writer thread, queue, WAV creation, watchdog,
callback, zero-fill) lives in the base class.  This file only provides:
- ``AsioThread`` singleton (COM STA thread)
- ASIO device lookup
- Stream open/close via ``AsioThread.submit()``
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import queue
import threading
from typing import Optional

from .base import AudioRecorder
from .models import DeviceInfo

os.environ["SD_ENABLE_ASIO"] = "1"

logger = logging.getLogger(__name__)


# ── AsioThread (singleton) ────────────────────────────────────────


class AsioThread:
    """Dedicated thread that owns the PortAudio/ASIO lifecycle.

    ASIO uses COM (STA) on Windows — all PortAudio calls MUST happen on
    the same thread.  This class runs a command queue on a pinned thread
    that initialises PortAudio at startup.
    """

    def __init__(self) -> None:
        self._cmd_q: queue.Queue[tuple] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="asio-thread", daemon=True)
        self._ready = threading.Event()
        self._sd = None  # sounddevice imported on ASIO thread
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        import sounddevice as sd

        sd._terminate()
        sd._initialize()
        self._sd = sd
        self._ready.set()

        while True:
            future, fn, args, kwargs = self._cmd_q.get()
            if fn is None:  # shutdown signal
                sd._terminate()
                logger.info("PortAudio/ASIO terminated")
                future.set_result(None)
                break
            try:
                result = fn(*args, **kwargs)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)

    def submit(self, fn, *args, **kwargs) -> concurrent.futures.Future:
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._cmd_q.put((future, fn, args, kwargs))
        return future

    def shutdown(self) -> None:
        future = self.submit(None)
        self._thread.join(timeout=5)

    @property
    def sd(self):
        return self._sd


_asio_thread: Optional[AsioThread] = None
_asio_lock = threading.Lock()


def get_asio_thread() -> AsioThread:
    global _asio_thread
    with _asio_lock:
        if _asio_thread is None:
            _asio_thread = AsioThread()
        return _asio_thread


def shutdown_asio() -> None:
    global _asio_thread
    with _asio_lock:
        if _asio_thread is not None:
            _asio_thread.shutdown()
            _asio_thread = None


# ── Helpers ────────────────────────────────────────────────────────


def _find_asio_device(name: str) -> int:
    at = get_asio_thread()
    sd = at.sd
    host_apis = sd.query_hostapis()
    for i, dev in enumerate(sd.query_devices()):
        api = host_apis[dev["hostapi"]]["name"]
        if "ASIO" in api and name.lower() in dev["name"].lower():
            return i
    raise RuntimeError(f"No ASIO device matching '{name}' found")


def _query_asio_devices() -> list[DeviceInfo]:
    at = get_asio_thread()
    sd = at.sd
    host_apis = sd.query_hostapis()
    devices: list[DeviceInfo] = []
    for i, dev in enumerate(sd.query_devices()):
        api_name = host_apis[dev["hostapi"]]["name"]
        if "ASIO" in api_name:
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


# ── AsioRecorder ───────────────────────────────────────────────────


class AsioRecorder(AudioRecorder):
    """Windows ASIO recorder — thin subclass of AudioRecorder.

    Only implements stream open/close (on the ASIO thread) and device lookup.
    """

    def __init__(self, device_name: str) -> None:
        super().__init__(device_name)
        self._at = get_asio_thread()
        self._device_index: Optional[int] = None

    # ── Subclass hooks ─────────────────────────────────────────

    def _resolve_device(self) -> None:
        self._device_index = self._at.submit(_find_asio_device, self._device_name).result()

    def _open_stream(self) -> float:
        return self._at.submit(self._open_stream_on_asio_thread).result()

    def _open_stream_on_asio_thread(self) -> float:
        """Runs on the dedicated ASIO thread."""
        sd = self._at.sd
        asio_settings = sd.AsioSettings(channel_selectors=self._channel_selectors)
        self._stream = sd.InputStream(
            device=self._device_index,
            channels=len(self._channel_selectors),
            samplerate=self._samplerate,
            callback=self._callback_fn,
            extra_settings=asio_settings,
            finished_callback=self._on_stream_finished,
        )
        self._stream.start()
        return self._stream.samplerate

    def _close_stream(self) -> None:
        self._at.submit(self._close_stream_on_asio_thread).result()

    def _close_stream_on_asio_thread(self) -> None:
        """Runs on the dedicated ASIO thread."""
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def list_devices(self) -> list[DeviceInfo]:
        return self._at.submit(_query_asio_devices).result()
