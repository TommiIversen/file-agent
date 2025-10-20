"""
Copy Error Handler - classifies errors and manages retry logic.
"""

import asyncio
import logging
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

from app.config import Settings


class ErrorType(str, Enum):
    """Classification of error types for retry logic."""

    LOCAL = "local"
    GLOBAL = "global"
    PERMANENT = "permanent"


class RetryDecision(str, Enum):
    """Decision on how to handle an error."""

    RETRY_SHORT_DELAY = "retry_short_delay"
    RETRY_LONG_DELAY = "retry_long_delay"
    NO_RETRY = "no_retry"


@dataclass
class ErrorHandlingResult:
    """Result of error handling analysis."""

    error_type: ErrorType
    retry_decision: RetryDecision
    delay_seconds: float
    should_retry: bool
    error_message: str
    timestamp: datetime

    @property
    def is_retriable(self) -> bool:
        """Check if this error should be retried"""
        return self.retry_decision != RetryDecision.NO_RETRY


class CopyErrorHandler:
    """Handles copy errors with classification and retry logic."""

    def __init__(self, settings: Settings):
        self.settings = settings

        self._local_errors_count = 0
        self._global_errors_count = 0
        self._permanent_errors_count = 0
        self._total_retries_performed = 0

        self._in_global_error_state = False
        self._last_global_error_time: Optional[datetime] = None

        logging.info("CopyErrorHandler initialized")
        logging.info(f"Max retry attempts: {self.settings.max_retry_attempts}")
        logging.info(f"Local retry delay: {self.settings.retry_delay_seconds}s")
        logging.info(f"Global retry delay: {self.settings.global_retry_delay_seconds}s")

    async def handle_local_error(
        self, error: Exception, file_path: str, attempt: int, max_attempts: int
    ) -> ErrorHandlingResult:
        """Handle local error with retry decision logic."""
        error_type = self.classify_error(error)

        logging.warning(
            f"Local error handling: {error.__class__.__name__}: {error}",
            extra={
                "operation": "local_error_handling",
                "file_path": file_path,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "error_type": error_type.value,
                "error_class": error.__class__.__name__,
            },
        )

        if error_type == ErrorType.PERMANENT:
            self._permanent_errors_count += 1
            return ErrorHandlingResult(
                error_type=error_type,
                retry_decision=RetryDecision.NO_RETRY,
                delay_seconds=0.0,
                should_retry=False,
                error_message=f"Permanent error: {str(error)}",
                timestamp=datetime.now(),
            )

        elif error_type == ErrorType.GLOBAL:
            self._global_errors_count += 1
            return ErrorHandlingResult(
                error_type=error_type,
                retry_decision=RetryDecision.RETRY_LONG_DELAY,
                delay_seconds=float(self.settings.global_retry_delay_seconds),
                should_retry=True,
                error_message=f"Global error (escalated): {str(error)}",
                timestamp=datetime.now(),
            )

        else:  # LOCAL error
            self._local_errors_count += 1

            if attempt >= max_attempts:
                return ErrorHandlingResult(
                    error_type=error_type,
                    retry_decision=RetryDecision.NO_RETRY,
                    delay_seconds=0.0,
                    should_retry=False,
                    error_message=f"Max retry attempts ({max_attempts}) reached: {str(error)}",
                    timestamp=datetime.now(),
                )
            else:
                self._total_retries_performed += 1
                return ErrorHandlingResult(
                    error_type=error_type,
                    retry_decision=RetryDecision.RETRY_SHORT_DELAY,
                    delay_seconds=float(self.settings.retry_delay_seconds),
                    should_retry=True,
                    error_message=f"Local error (attempt {attempt}/{max_attempts}): {str(error)}",
                    timestamp=datetime.now(),
                )

    async def handle_global_error(self, error_message: str) -> None:
        """Handle global error with infinite retry and long delay."""
        if not self._in_global_error_state:
            logging.warning(f"Global error detected: {error_message}")
            logging.warning(
                f"Pausing all operations for {self.settings.global_retry_delay_seconds} seconds"
            )

            self._in_global_error_state = True
            self._last_global_error_time = datetime.now()
            self._global_errors_count += 1

        await asyncio.sleep(self.settings.global_retry_delay_seconds)

    def classify_error(self, error: Exception) -> ErrorType:
        """Classify an exception as LOCAL, GLOBAL or PERMANENT."""
        error_str = str(error).lower()

        if isinstance(error, FileNotFoundError):
            return ErrorType.PERMANENT

        if isinstance(error, ValueError) and "size mismatch" in error_str:
            return ErrorType.PERMANENT

        if "corrupt" in error_str or "invalid" in error_str or "malformed" in error_str:
            return ErrorType.PERMANENT

        if isinstance(error, (ConnectionError, TimeoutError)):
            return ErrorType.GLOBAL

        if isinstance(error, OSError):
            errno = getattr(error, "errno", None)

            if errno in [28, 30, 32]:
                return ErrorType.GLOBAL

            if "network" in error_str or "destination" in error_str:
                return ErrorType.GLOBAL

        if "destination" in error_str and (
            "unavailable" in error_str or "not accessible" in error_str
        ):
            return ErrorType.GLOBAL

        if isinstance(error, PermissionError):
            return ErrorType.LOCAL

        if isinstance(error, (BlockingIOError, InterruptedError)):
            return ErrorType.LOCAL

        if "permission denied" in error_str or "access denied" in error_str:
            return ErrorType.LOCAL

        if "file is being used" in error_str or "locked" in error_str:
            return ErrorType.LOCAL

        return ErrorType.LOCAL

    def should_retry(self, error: Exception, attempt: int, max_attempts: int) -> bool:
        """Determine if an error should be retried based on error type and attempt count."""
        error_type = self.classify_error(error)

        if error_type == ErrorType.PERMANENT:
            return False

        if error_type == ErrorType.GLOBAL:
            return True

        return attempt < max_attempts

    def clear_global_error_state(self) -> None:
        """Clear global error state when destination becomes available again."""
        if self._in_global_error_state:
            logging.info("Clearing global error state - destination available again")
            self._in_global_error_state = False
            self._last_global_error_time = None

    def get_error_statistics(self) -> Dict[str, Any]:
        """Get detailed error handling statistics."""
        return {
            "local_errors_count": self._local_errors_count,
            "global_errors_count": self._global_errors_count,
            "permanent_errors_count": self._permanent_errors_count,
            "total_retries_performed": self._total_retries_performed,
            "in_global_error_state": self._in_global_error_state,
            "last_global_error_time": self._last_global_error_time.isoformat()
            if self._last_global_error_time
            else None,
            "error_handling_config": {
                "max_retry_attempts": self.settings.max_retry_attempts,
                "retry_delay_seconds": self.settings.retry_delay_seconds,
                "global_retry_delay_seconds": self.settings.global_retry_delay_seconds,
            },
        }

    def get_classification_info(self) -> Dict[str, Any]:
        """Get information about error classification logic for debugging."""
        return {
            "permanent_patterns": [
                "FileNotFoundError",
                "ValueError with 'size mismatch'",
                "Corruption patterns (corrupt, invalid, malformed)",
            ],
            "global_patterns": [
                "ConnectionError, TimeoutError",
                "OSError errno 28,30,32 (No space, Read-only, Broken pipe)",
                "Network/destination unavailable patterns",
            ],
            "local_patterns": [
                "PermissionError, BlockingIOError",
                "Permission/access denied patterns",
                "File lock patterns",
            ],
            "default_classification": "LOCAL (for unknown retriable errors)",
        }

    def reset_statistics(self) -> None:
        """Reset error statistics for testing purposes."""
        self._local_errors_count = 0
        self._global_errors_count = 0
        self._permanent_errors_count = 0
        self._total_retries_performed = 0
        self._in_global_error_state = False
        self._last_global_error_time = None

        logging.info("Error statistics reset")
