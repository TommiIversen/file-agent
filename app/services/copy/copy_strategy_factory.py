"""
Copy Strategy Factory for File Transfer Agent.

CopyStrategyFactory er ansvarlig for:
- Strategy selection baseret på file karakteristika
- Configuration generation for FileCopyExecutor
- Progress callback creation optimeret for file type
- Integration mellem gamle copy strategies og nye FileCopyExecutor

Dette er Phase 3.3 i refactoring roadmap - ekstraherer strategy selection
logic fra FileCopyService for at følge SOLID principper.
"""

import logging
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Any, Awaitable

from app.config import Settings
from app.models import TrackedFile, FileStatus
from app.services.state_manager import StateManager
from app.services.copy.file_copy_executor import CopyProgress


@dataclass
class ExecutorConfig:
    """
    Configuration for FileCopyExecutor copy operations.

    Contains all necessary information for the executor to perform
    optimal copy operations based on file characteristics.
    """

    use_temp_file: bool
    chunk_size: int
    progress_update_interval: int
    strategy_name: str
    is_growing_file: bool
    copy_mode: str = "normal"  # "normal", "growing", "stream"

    def get_summary(self) -> str:
        """Get human-readable summary of the configuration."""
        return (
            f"ExecutorConfig(strategy={self.strategy_name}, "
            f"mode={self.copy_mode}, temp_file={self.use_temp_file}, "
            f"chunk_size={self.chunk_size}, growing={self.is_growing_file})"
        )


class CopyStrategyFactory:
    """
    Factory for creating copy configurations and progress callbacks.

    Determines optimal copy approach based on file characteristics:
    - Normal files: Standard copy with temp file strategy
    - Growing files: Streaming copy with special handling
    - Large files: Optimized chunk sizes and progress reporting
    - Network destinations: Enhanced retry and verification

    Bridges between legacy copy strategies and new FileCopyExecutor architecture.
    """

    def __init__(self, settings: Settings, state_manager: StateManager):
        """
        Initialize CopyStrategyFactory with dependencies.

        Args:
            settings: Application settings for copy configuration
            state_manager: State manager for file status updates
        """
        self.settings = settings
        self.state_manager = state_manager

        # Network-optimized copy configuration
        self.normal_chunk_size = (
            settings.normal_file_chunk_size_kb * 1024
        )  # 1MB default
        self.large_file_chunk_size = (
            settings.large_file_chunk_size_kb * 1024
        )  # 2MB for large files
        self.growing_file_chunk_size = (
            settings.growing_file_chunk_size_kb * 1024
        )  # 2MB for growing files
        self.large_file_threshold = settings.large_file_threshold_gb * (
            1024**3
        )  # Convert to bytes

        logging.debug(
            f"CopyStrategyFactory initialized with optimized chunk sizes: "
            f"normal={self.normal_chunk_size // 1024}KB, "
            f"large={self.large_file_chunk_size // 1024}KB, "
            f"growing={self.growing_file_chunk_size // 1024}KB, "
            f"threshold={settings.large_file_threshold_gb}GB"
        )

    def get_executor_config(self, tracked_file: TrackedFile) -> ExecutorConfig:
        is_growing = self._is_growing_file(tracked_file)
        strategy_name = self._select_strategy_name(tracked_file, is_growing)
        use_temp_file = self._should_use_temp_file(tracked_file, is_growing)
        chunk_size = self._get_optimal_chunk_size(tracked_file, is_growing)
        progress_interval = self._get_progress_update_interval(tracked_file, is_growing)
        copy_mode = self._get_copy_mode(tracked_file, is_growing)

        config = ExecutorConfig(
            use_temp_file=use_temp_file,
            chunk_size=chunk_size,
            progress_update_interval=progress_interval,
            strategy_name=strategy_name,
            is_growing_file=is_growing,
            copy_mode=copy_mode,
        )

        logging.debug(
            f"Generated config for {Path(tracked_file.file_path).name}: "
            f"{config.get_summary()}"
        )

        return config

    def should_use_temp_file(self, tracked_file: TrackedFile) -> bool:
        return self._should_use_temp_file(
            tracked_file, self._is_growing_file(tracked_file)
        )

    def get_progress_callback(
        self, tracked_file: TrackedFile
    ) -> Callable[[CopyProgress], None]:
        is_growing = self._is_growing_file(tracked_file)

        # For growing files, use more frequent updates
        if is_growing:
            return self._create_growing_file_callback(tracked_file)
        else:
            return self._create_normal_file_callback(tracked_file)

    def get_available_strategies(self) -> Dict[str, str]:
        strategies = {
            "normal_temp": "Normal file copy with temporary file",
            "normal_direct": "Normal file copy direct to destination",
            "growing_stream": "Growing file copy with streaming approach",
        }

        if self.settings.enable_growing_file_support:
            strategies["growing_safe"] = "Growing file copy with safety margin"

        return strategies

    def get_factory_info(self) -> Dict[str, Any]:
        return {
            "normal_chunk_size_kb": self.normal_chunk_size // 1024,
            "large_file_chunk_size_kb": self.large_file_chunk_size // 1024,
            "growing_file_chunk_size_kb": self.growing_file_chunk_size // 1024,
            "large_file_threshold_gb": self.settings.large_file_threshold_gb,
            "growing_file_support": self.settings.enable_growing_file_support,
            "default_temp_file_usage": self.settings.use_temporary_file,
            "available_strategies": list(self.get_available_strategies().keys()),
        }

    # Private helper methods

    def _is_growing_file(self, tracked_file: TrackedFile) -> bool:
        """Check if file is marked as growing."""
        return (
            getattr(tracked_file, "is_growing_file", False)
            and self.settings.enable_growing_file_support
        )

    def _select_strategy_name(self, tracked_file: TrackedFile, is_growing: bool) -> str:
        """Select appropriate strategy name based on file characteristics."""
        if is_growing:
            return "growing_stream"
        elif self.settings.use_temporary_file:
            return "normal_temp"
        else:
            return "normal_direct"

    def _should_use_temp_file(
        self, tracked_file: TrackedFile, is_growing: bool
    ) -> bool:
        """Determine if temporary file should be used."""
        # Growing files typically don't use temp files for streaming copy
        if is_growing:
            return False

        # Use settings default for normal files
        return self.settings.use_temporary_file

    def _get_optimal_chunk_size(
        self, tracked_file: TrackedFile, is_growing: bool
    ) -> int:
        """Determine optimal chunk size based on file characteristics."""
        if is_growing:
            return self.growing_file_chunk_size
        elif tracked_file.file_size > self.large_file_threshold:
            return self.large_file_chunk_size
        else:
            return self.normal_chunk_size

    def _get_progress_update_interval(
        self, tracked_file: TrackedFile, is_growing: bool
    ) -> int:
        """Determine progress update interval based on file type."""
        if is_growing:
            # More frequent updates for growing files
            return 1  # Update every 1%
        elif tracked_file.file_size > self.large_file_threshold:
            # Less frequent updates for large files to avoid overhead
            return 5  # Update every 5%
        else:
            # Standard update interval for normal files
            return getattr(self.settings, "copy_progress_update_interval", 2)

    def _get_copy_mode(self, tracked_file: TrackedFile, is_growing: bool) -> str:
        """Determine copy mode based on file characteristics."""
        if is_growing:
            return "growing"
        elif tracked_file.file_size > self.large_file_threshold:
            return "large_file"
        else:
            return "normal"

    def _create_normal_file_callback(
        self, tracked_file: TrackedFile
    ) -> Callable[[CopyProgress], None]:
        """Create progress callback for normal files."""

        def normal_progress_callback(progress: CopyProgress) -> None:
            """Progress callback for normal file copy operations."""
            try:
                # Calculate transfer rate in MB/s
                copy_speed_mbps = progress.current_rate_bytes_per_sec / (1024 * 1024)

                # Schedule async state update without awaiting - UUID precision
                if tracked_file:
                    asyncio.create_task(
                        self.state_manager.update_file_status_by_id(
                            tracked_file.id,
                            FileStatus.COPYING,
                            copy_progress=progress.progress_percent,
                            bytes_copied=progress.bytes_copied,
                            copy_speed_mbps=copy_speed_mbps,
                        )
                    )

                logging.debug(
                    f"Normal copy progress: {Path(tracked_file.file_path).name} - "
                    f"{progress.progress_percent:.1f}% "
                    f"({copy_speed_mbps:.2f} MB/s)"
                )

            except Exception as e:
                logging.warning(f"Progress callback error for {tracked_file.file_path}: {e}")

        return normal_progress_callback

    def _create_growing_file_callback(
        self, tracked_file: TrackedFile
    ) -> Callable[[CopyProgress], None]:
        """Create progress callback for growing files."""

        def growing_progress_callback(progress: CopyProgress) -> None:
            """Progress callback for growing file copy operations."""
            try:
                # Calculate transfer rate in MB/s
                copy_speed_mbps = progress.current_rate_bytes_per_sec / (1024 * 1024)

                # Schedule async state update without awaiting - UUID precision
                if tracked_file:
                    asyncio.create_task(
                        self.state_manager.update_file_status_by_id(
                            tracked_file.id,
                            FileStatus.GROWING_COPY,
                            copy_progress=progress.progress_percent,
                            bytes_copied=progress.bytes_copied,
                            file_size=progress.total_bytes,  # May be growing
                            copy_speed_mbps=copy_speed_mbps,
                        )
                    )

                logging.debug(
                    f"Growing copy progress: {Path(tracked_file.file_path).name} - "
                    f"{progress.progress_percent:.1f}% "
                    f"({progress.bytes_copied} / {progress.total_bytes} bytes, "
                    f"{copy_speed_mbps:.2f} MB/s)"
                )

            except Exception as e:
                logging.warning(
                    f"Growing file progress callback error for {tracked_file.file_path}: {e}"
                )

        return growing_progress_callback
