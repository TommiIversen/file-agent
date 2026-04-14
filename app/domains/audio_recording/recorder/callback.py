"""
Audio Recording — Recorder Callback Protocol

Sync callback interface that the recorder engine uses to notify the domain layer
about state changes. Callbacks are called from recorder threads (ASIO/writer),
so implementations MUST bridge to async via loop.call_soon_threadsafe().
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class RecorderCallback(Protocol):
    """Sync callbacks invoked from recorder threads.

    The domain adapter implements this and uses
    ``loop.call_soon_threadsafe(asyncio.ensure_future, ...)``
    to bridge into the async EventBus world.
    """

    def on_started(self, files: list[Path], actual_samplerate: float) -> None:
        """Recording has started successfully."""
        ...

    def on_stopped(
        self,
        files: list[Path],
        duration_seconds: float,
        overflow_count: int,
    ) -> None:
        """Recording has stopped (clean stop)."""
        ...

    def on_error(self, error_message: str, recoverable: bool) -> None:
        """A recording error occurred (writer crash, disk full, etc.)."""
        ...

    def on_overflow_warning(self, dropped_count: int, total_drops: int) -> None:
        """Audio queue overflow — writer can't keep up.

        ``dropped_count`` is the number of blocks dropped since the last
        successfully queued block.  ``total_drops`` is the running total.
        """
        ...

    def on_device_lost(self) -> None:
        """Audio device disappeared (USB unplug, driver crash)."""
        ...
