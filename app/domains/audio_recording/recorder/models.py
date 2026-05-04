"""
Audio Recording — Track Model & Device Types

Value objects shared across recorder backends and the domain layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AudioTrack:
    """One logical recording track (mono or stereo).

    ``channels`` contains 1-based ASIO/CoreAudio input channel indices.
    Mono  → ``channels=[3]``         → 1-channel WAV
    Stereo → ``channels=[1, 2]``     → 2-channel WAV (interleaved L/R)
    """

    channels: tuple[int, ...]
    label: str
    mode: Literal["mono", "stereo"]

    def __post_init__(self) -> None:
        expected = 1 if self.mode == "mono" else 2
        if len(self.channels) != expected:
            raise ValueError(
                f"{self.mode} track '{self.label}' requires {expected} "
                f"channel(s), got {len(self.channels)}"
            )
        if not self.label:
            raise ValueError("Track label must not be empty")


@dataclass(frozen=True)
class DeviceInfo:
    """Describes an available audio input device."""

    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: int
    host_api: str
