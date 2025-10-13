"""
Resume Integration Adapter

Adapter klasse der integrerer resumable copy strategies med existing
job processor framework. Sikrer seamless integration uden at ændre
på existing interfaces.
"""

import logging
from pathlib import Path

from ..models import TrackedFile
from ..utils.resumable_copy_strategies import (
    ResumeCapableMixin,
)

logger = logging.getLogger("app.utils.resume_integration")


class ResumableStrategyAdapter:
    """
    Adapter der wrapper resumable strategies til at fungere med
    existing FileCopyStrategy interface.
    """

    def __init__(self, resumable_strategy):
        self.resumable_strategy = resumable_strategy

    async def copy_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        """
        Copy file med resume support gennem existing interface.

        Args:
            source_path: Source fil path som string
            dest_path: Destination fil path som string
            tracked_file: TrackedFile object for progress tracking

        Returns:
            True hvis copy succeeded, False ellers
        """
        source = Path(source_path)
        dest = Path(dest_path)

        # Progress callback der opdaterer tracked_file
        def progress_callback(bytes_copied: int, total_bytes: int):
            if hasattr(tracked_file, "bytes_copied"):
                tracked_file.bytes_copied = bytes_copied
            if hasattr(tracked_file, "total_size"):
                tracked_file.total_size = total_bytes

        try:
            # Check om strategien har resume capabilities
            if isinstance(self.resumable_strategy, ResumeCapableMixin):
                logger.debug(f"Bruger resume-capable strategy for {source.name}")

                # Prøv først resume hvis det er muligt
                if await self.resumable_strategy.should_attempt_resume(source, dest):
                    logger.info(f"Forsøger resume copy: {source.name}")
                    success = await self.resumable_strategy.execute_resume_copy(
                        source, dest, progress_callback
                    )

                    if success:
                        # Log resume metrics hvis tilgængelig
                        metrics = self.resumable_strategy.get_resume_metrics()
                        if metrics:
                            logger.info(
                                f"Resume SUCCESS: {source.name} - "
                                f"bevarede {metrics.preservation_percentage:.1f}% af eksisterende data"
                            )
                        return True
                    else:
                        logger.warning(
                            f"Resume failed - falling back to fresh copy: {source.name}"
                        )

                # Fallback til fresh copy
                logger.debug(f"Udfører fresh copy: {source.name}")
                return await self.resumable_strategy.execute_copy(
                    source, dest, progress_callback
                )

            else:
                # Legacy strategy uden resume support
                logger.debug(f"Bruger legacy strategy (no resume): {source.name}")
                if hasattr(self.resumable_strategy, "execute_copy"):
                    return await self.resumable_strategy.execute_copy(
                        source, dest, progress_callback
                    )
                else:
                    # Fallback til original interface
                    return await self.resumable_strategy.copy_file(
                        source_path, dest_path, tracked_file
                    )

        except Exception as e:
            logger.error(f"Fejl i ResumableStrategyAdapter for {source.name}: {e}")
            return False

    def supports_file(self, tracked_file: TrackedFile) -> bool:
        """
        Check om strategien supporterer denne fil.
        """
        if hasattr(self.resumable_strategy, "supports_file"):
            return self.resumable_strategy.supports_file(tracked_file)
        else:
            # Default til True for backward compatibility
            return True



def get_resume_config_for_mode(mode: str):
    """
    Get resume configuration baseret på mode setting.

    Args:
        mode: "conservative", "performance", eller "paranoid"

    Returns:
        Appropriate SecureResumeConfig
    """
    from ..utils.secure_resume_config import (
        CONSERVATIVE_CONFIG,
        PERFORMANCE_CONFIG,
        PARANOID_CONFIG,
    )

    mode_map = {
        "conservative": CONSERVATIVE_CONFIG,
        "performance": PERFORMANCE_CONFIG,
        "paranoid": PARANOID_CONFIG,
    }

    config = mode_map.get(mode.lower(), CONSERVATIVE_CONFIG)
    logger.info(f"Resume mode '{mode}' → config: {type(config).__name__}")

    return config


class ResumeMetricsCollector:
    """
    Collector for resume operation metrics til monitoring og optimering.
    """

    def __init__(self):
        self.operations = []

    def record_operation(self, metrics):
        """Record resume operation metrics"""
        self.operations.append(metrics)

        # Keep only recent operations (last 100)
        if len(self.operations) > 100:
            self.operations = self.operations[-100:]

    def get_success_rate(self) -> float:
        """Get success rate for resume operations"""
        if not self.operations:
            return 0.0

        successful = sum(1 for op in self.operations if not op.corruption_detected)
        return (successful / len(self.operations)) * 100.0

    def get_average_preservation(self) -> float:
        """Get average preservation percentage"""
        if not self.operations:
            return 0.0

        return sum(op.preservation_percentage for op in self.operations) / len(
            self.operations
        )

    def log_summary(self):
        """Log summary statistics"""
        if not self.operations:
            logger.info("Ingen resume operations endnu")
            return

        logger.info("Resume Operations Summary:")
        logger.info(f"  Total operations: {len(self.operations)}")
        logger.info(f"  Success rate: {self.get_success_rate():.1f}%")
        logger.info(f"  Average preservation: {self.get_average_preservation():.1f}%")

        # Corruption statistics
        corrupted = sum(1 for op in self.operations if op.corruption_detected)
        logger.info(
            f"  Corruption detected: {corrupted}/{len(self.operations)} ({(corrupted / len(self.operations)) * 100:.1f}%)"
        )


# Global metrics collector
_resume_metrics_collector = ResumeMetricsCollector()
