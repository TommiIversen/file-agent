"""Tests for peak metering logic in the writer thread."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from app.domains.audio_recording.recorder.base import (
    _TrackWriter,
    AudioRecorder,
)
from app.domains.audio_recording.recorder.models import AudioTrack

# Test constants: 128 frames/block at 48 kHz, interval = 48000/10 = 4800 frames
_FRAMES_PER_BLOCK = 128
_TEST_SAMPLERATE = 48000
_INTERVAL_FRAMES = _TEST_SAMPLERATE // 10  # 4800
_BLOCKS_PER_INTERVAL = _INTERVAL_FRAMES // _FRAMES_PER_BLOCK  # 37 (4736 frames)
# 37 blocks × 128 = 4736 < 4800, so we need 38 blocks to cross the threshold
_BLOCKS_TO_TRIGGER = _BLOCKS_PER_INTERVAL + 1  # 38


# ── Concrete stub (abstract methods are no-ops) ────────────────


class _StubRecorder(AudioRecorder):
    """Minimal concrete subclass for testing shared base logic."""

    def _open_stream(self) -> float:
        return 48000.0

    def _close_stream(self) -> None:
        pass

    def _resolve_device(self) -> None:
        pass

    def list_devices(self):  # type: ignore[override]
        return []


def _make_recorder(
    tracks: list[AudioTrack],
) -> tuple[_StubRecorder, MagicMock]:
    """Set up a recorder with channel map + peak_acc, ready for _writer_loop."""
    rec = _StubRecorder(device_name="test")
    cb = MagicMock()
    rec.set_callback(cb)

    rec._build_channel_map(tracks)
    rec._peak_acc = np.zeros(len(rec._channel_selectors), dtype=np.float32)
    rec._levels_frame_count = 0
    rec._levels_interval_frames = _INTERVAL_FRAMES

    # Create dummy TrackWriters (writer itself unused — we test metering only)
    rec._track_writers = [
        _TrackWriter(track=t, path=MagicMock(), writer=MagicMock())
        for t in tracks
    ]
    return rec, cb


# ── Tests ───────────────────────────────────────────────────────


class TestPeakMetering:
    """Tests for the peak accumulation + on_levels emission."""

    def _feed_blocks(
        self,
        rec: _StubRecorder,
        block: np.ndarray,
        count: int,
    ) -> None:
        """Put *count* copies of *block* through the queue and run the writer."""
        for _ in range(count):
            rec._audio_q.put((block, 0))
        rec._audio_q.put(None)  # sentinel
        rec._writer_loop()

    def test_on_levels_fires_after_interval(self) -> None:
        """on_levels is called exactly once after _BLOCKS_TO_TRIGGER blocks."""
        track = AudioTrack(channels=(1,), label="Mic1", mode="mono")
        rec, cb = _make_recorder([track])

        block = np.full((128, 1), 0.5, dtype=np.float32)
        self._feed_blocks(rec, block, _BLOCKS_TO_TRIGGER)

        assert cb.on_levels.call_count == 1
        peaks = cb.on_levels.call_args[0][0]
        assert len(peaks) == 1
        assert peaks[0]["label"] == "Mic1"
        assert len(peaks[0]["peaks"]) == 1
        assert peaks[0]["peaks"][0] == pytest.approx(0.5, abs=0.001)

    def test_on_levels_not_fired_before_interval(self) -> None:
        """on_levels must NOT fire before reaching the interval threshold."""
        track = AudioTrack(channels=(1,), label="Mic1", mode="mono")
        rec, cb = _make_recorder([track])

        block = np.full((128, 1), 0.5, dtype=np.float32)
        self._feed_blocks(rec, block, _BLOCKS_TO_TRIGGER - 1)

        cb.on_levels.assert_not_called()

    def test_accumulator_takes_running_max(self) -> None:
        """Peak accumulator should hold the maximum across blocks."""
        track = AudioTrack(channels=(1,), label="Mic1", mode="mono")
        rec, cb = _make_recorder([track])

        blocks: list[np.ndarray] = []
        for i in range(_BLOCKS_TO_TRIGGER):
            if i == 5:
                blocks.append(np.full((128, 1), 0.9, dtype=np.float32))
            else:
                blocks.append(np.full((128, 1), 0.1, dtype=np.float32))

        for b in blocks:
            rec._audio_q.put((b, 0))
        rec._audio_q.put(None)
        rec._writer_loop()

        peaks = cb.on_levels.call_args[0][0]
        assert peaks[0]["peaks"][0] == pytest.approx(0.9, abs=0.001)

    def test_stereo_track_reports_two_peaks(self) -> None:
        """A stereo track should report separate L and R peaks."""
        track = AudioTrack(channels=(1, 2), label="PGM_LR", mode="stereo")
        rec, cb = _make_recorder([track])

        block = np.zeros((128, 2), dtype=np.float32)
        block[:, 0] = 0.8  # L
        block[:, 1] = 0.3  # R
        self._feed_blocks(rec, block, _BLOCKS_TO_TRIGGER)

        peaks = cb.on_levels.call_args[0][0]
        assert len(peaks) == 1
        assert peaks[0]["label"] == "PGM_LR"
        assert len(peaks[0]["peaks"]) == 2
        assert peaks[0]["peaks"][0] == pytest.approx(0.8, abs=0.001)
        assert peaks[0]["peaks"][1] == pytest.approx(0.3, abs=0.001)

    def test_multiple_tracks(self) -> None:
        """Multiple tracks should each get their own peak entry."""
        tracks = [
            AudioTrack(channels=(1, 2), label="PGM_LR", mode="stereo"),
            AudioTrack(channels=(3,), label="Mic1", mode="mono"),
        ]
        rec, cb = _make_recorder(tracks)

        block = np.zeros((128, 3), dtype=np.float32)
        block[:, 0] = 0.7   # PGM L
        block[:, 1] = 0.6   # PGM R
        block[:, 2] = 0.4   # Mic1
        self._feed_blocks(rec, block, _BLOCKS_TO_TRIGGER)

        peaks = cb.on_levels.call_args[0][0]
        assert len(peaks) == 2
        assert peaks[0]["label"] == "PGM_LR"
        assert peaks[0]["peaks"][0] == pytest.approx(0.7, abs=0.001)
        assert peaks[0]["peaks"][1] == pytest.approx(0.6, abs=0.001)
        assert peaks[1]["label"] == "Mic1"
        assert peaks[1]["peaks"][0] == pytest.approx(0.4, abs=0.001)

    def test_accumulator_resets_after_emission(self) -> None:
        """After emitting, peak_acc must reset so the next interval starts fresh."""
        track = AudioTrack(channels=(1,), label="Mic1", mode="mono")
        rec, cb = _make_recorder([track])

        loud = np.full((128, 1), 0.9, dtype=np.float32)
        quiet = np.full((128, 1), 0.1, dtype=np.float32)

        for _ in range(_BLOCKS_TO_TRIGGER):
            rec._audio_q.put((loud, 0))
        for _ in range(_BLOCKS_TO_TRIGGER):
            rec._audio_q.put((quiet, 0))
        rec._audio_q.put(None)
        rec._writer_loop()

        assert cb.on_levels.call_count == 2
        first_peaks = cb.on_levels.call_args_list[0][0][0]
        second_peaks = cb.on_levels.call_args_list[1][0][0]
        assert first_peaks[0]["peaks"][0] == pytest.approx(0.9, abs=0.001)
        assert second_peaks[0]["peaks"][0] == pytest.approx(0.1, abs=0.001)

    def test_silence_reports_zero_peaks(self) -> None:
        """Total silence should produce 0.0 peaks."""
        track = AudioTrack(channels=(1,), label="Mic1", mode="mono")
        rec, cb = _make_recorder([track])

        block = np.zeros((128, 1), dtype=np.float32)
        self._feed_blocks(rec, block, _BLOCKS_TO_TRIGGER)

        peaks = cb.on_levels.call_args[0][0]
        assert peaks[0]["peaks"][0] == 0.0
