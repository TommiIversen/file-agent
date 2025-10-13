"""
Tests for CopyErrorHandler Strategy.

Test suite for error handling strategy that manages retry logic,
error classification, and global vs local error patterns.
"""

import pytest
import asyncio
from datetime import datetime

from app.config import Settings
from app.services.error_handling.copy_error_handler import (
    CopyErrorHandler,
    ErrorType,
    RetryDecision,
    ErrorHandlingResult,
)


@pytest.fixture
def settings():
    """Create test settings"""
    return Settings(
        source_directory="C:/source",
        destination_directory="C:/dest",
        max_retry_attempts=3,
        retry_delay_seconds=1,
        global_retry_delay_seconds=5,
    )


@pytest.fixture
def error_handler(settings):
    """Create CopyErrorHandler instance"""
    return CopyErrorHandler(settings)


class TestErrorClassification:
    """Test error classification logic"""

    def test_classify_file_not_found_as_permanent(self, error_handler):
        """Test FileNotFoundError is classified as PERMANENT"""
        error = FileNotFoundError("Source file not found")
        result = error_handler.classify_error(error)
        assert result == ErrorType.PERMANENT

    def test_classify_size_mismatch_as_permanent(self, error_handler):
        """Test size mismatch errors are classified as PERMANENT"""
        error = ValueError("File size mismatch: source=100, dest=90")
        result = error_handler.classify_error(error)
        assert result == ErrorType.PERMANENT

    def test_classify_corruption_as_permanent(self, error_handler):
        """Test corruption-related errors are classified as PERMANENT"""
        errors = [
            ValueError("File appears corrupt"),
            RuntimeError("Invalid file format"),
            Exception("Malformed data detected"),
        ]

        for error in errors:
            result = error_handler.classify_error(error)
            assert result == ErrorType.PERMANENT

    def test_classify_connection_errors_as_global(self, error_handler):
        """Test network-related errors are classified as GLOBAL"""
        errors = [
            ConnectionError("Network unreachable"),
            TimeoutError("Connection timed out"),
            OSError(28, "No space left on device"),
            OSError(30, "Read-only file system"),
            OSError(32, "Broken pipe"),
        ]

        for error in errors:
            result = error_handler.classify_error(error)
            assert result == ErrorType.GLOBAL

    def test_classify_destination_unavailable_as_global(self, error_handler):
        """Test destination unavailable errors are classified as GLOBAL"""
        errors = [
            OSError("Destination not accessible"),
            RuntimeError("Network destination unavailable"),
            Exception("Destination path unavailable"),
        ]

        for error in errors:
            result = error_handler.classify_error(error)
            assert result == ErrorType.GLOBAL

    def test_classify_permission_errors_as_local(self, error_handler):
        """Test permission-related errors are classified as LOCAL"""
        errors = [
            PermissionError("Access denied"),
            BlockingIOError("Resource temporarily unavailable"),
            InterruptedError("Operation interrupted"),
            OSError("Permission denied"),
            Exception("File is being used by another process"),
            RuntimeError("File locked"),
        ]

        for error in errors:
            result = error_handler.classify_error(error)
            assert result == ErrorType.LOCAL

    def test_classify_unknown_errors_as_local(self, error_handler):
        """Test unknown errors default to LOCAL for safety"""
        errors = [
            RuntimeError("Some unknown error"),
            Exception("Unexpected situation"),
            ValueError("Some other value error"),
        ]

        for error in errors:
            result = error_handler.classify_error(error)
            assert result == ErrorType.LOCAL


class TestLocalErrorHandling:
    """Test local error handling with retry logic"""

    @pytest.mark.asyncio
    async def test_handle_local_error_within_retry_limit(self, error_handler):
        """Test local error handling within retry limit"""
        error = PermissionError("Access denied")
        result = await error_handler.handle_local_error(
            error, "/test/file.txt", attempt=1, max_attempts=3
        )

        assert result.error_type == ErrorType.LOCAL
        assert result.retry_decision == RetryDecision.RETRY_SHORT_DELAY
        assert result.should_retry is True
        assert result.delay_seconds == 1.0
        assert "attempt 1/3" in result.error_message

    @pytest.mark.asyncio
    async def test_handle_local_error_max_attempts_reached(self, error_handler):
        """Test local error handling when max attempts reached"""
        error = PermissionError("Access denied")
        result = await error_handler.handle_local_error(
            error, "/test/file.txt", attempt=3, max_attempts=3
        )

        assert result.error_type == ErrorType.LOCAL
        assert result.retry_decision == RetryDecision.NO_RETRY
        assert result.should_retry is False
        assert result.delay_seconds == 0.0
        assert "Max retry attempts (3) reached" in result.error_message

    @pytest.mark.asyncio
    async def test_handle_permanent_error_no_retry(self, error_handler):
        """Test permanent error handling - no retry"""
        error = FileNotFoundError("File not found")
        result = await error_handler.handle_local_error(
            error, "/test/file.txt", attempt=1, max_attempts=3
        )

        assert result.error_type == ErrorType.PERMANENT
        assert result.retry_decision == RetryDecision.NO_RETRY
        assert result.should_retry is False
        assert result.delay_seconds == 0.0
        assert "Permanent error" in result.error_message

    @pytest.mark.asyncio
    async def test_handle_global_error_escalation(self, error_handler):
        """Test global error escalation from local handler"""
        error = ConnectionError("Network unreachable")
        result = await error_handler.handle_local_error(
            error, "/test/file.txt", attempt=1, max_attempts=3
        )

        assert result.error_type == ErrorType.GLOBAL
        assert result.retry_decision == RetryDecision.RETRY_LONG_DELAY
        assert result.should_retry is True
        assert result.delay_seconds == 5.0
        assert "Global error (escalated)" in result.error_message


class TestGlobalErrorHandling:
    """Test global error handling with infinite retry"""

    @pytest.mark.asyncio
    async def test_handle_global_error_first_time(self, error_handler):
        """Test first global error sets state and waits"""
        # Mock asyncio.sleep to avoid waiting
        original_sleep = asyncio.sleep
        sleep_called_with = None

        async def mock_sleep(delay):
            nonlocal sleep_called_with
            sleep_called_with = delay

        asyncio.sleep = mock_sleep

        try:
            await error_handler.handle_global_error("Destination not available")

            assert error_handler._in_global_error_state is True
            assert error_handler._last_global_error_time is not None
            assert sleep_called_with == 5.0  # global_retry_delay_seconds

        finally:
            asyncio.sleep = original_sleep

    @pytest.mark.asyncio
    async def test_handle_global_error_subsequent_calls(self, error_handler):
        """Test subsequent global errors don't spam logs"""
        # Mock asyncio.sleep
        sleep_calls = []

        async def mock_sleep(delay):
            sleep_calls.append(delay)

        original_sleep = asyncio.sleep
        asyncio.sleep = mock_sleep

        try:
            # First call should set state
            await error_handler.handle_global_error("Network error")
            assert error_handler._in_global_error_state is True

            # Second call should still wait but not log initial message again
            await error_handler.handle_global_error("Still network error")

            assert len(sleep_calls) == 2
            assert all(delay == 5.0 for delay in sleep_calls)

        finally:
            asyncio.sleep = original_sleep

    def test_clear_global_error_state(self, error_handler):
        """Test clearing global error state"""
        # Set global error state manually
        error_handler._in_global_error_state = True
        error_handler._last_global_error_time = datetime.now()

        # Clear state
        error_handler.clear_global_error_state()

        assert error_handler._in_global_error_state is False
        assert error_handler._last_global_error_time is None


class TestRetryDecisions:
    """Test retry decision logic"""

    def test_should_retry_permanent_error(self, error_handler):
        """Test permanent errors are not retried"""
        error = FileNotFoundError("File not found")
        should_retry = error_handler.should_retry(error, attempt=1, max_attempts=3)
        assert should_retry is False

    def test_should_retry_global_error(self, error_handler):
        """Test global errors are always retried"""
        error = ConnectionError("Network error")
        should_retry = error_handler.should_retry(error, attempt=5, max_attempts=3)
        assert should_retry is True  # Global errors ignore attempt count

    def test_should_retry_local_error_within_limit(self, error_handler):
        """Test local errors are retried within limit"""
        error = PermissionError("Access denied")
        should_retry = error_handler.should_retry(error, attempt=2, max_attempts=3)
        assert should_retry is True

    def test_should_retry_local_error_over_limit(self, error_handler):
        """Test local errors are not retried over limit"""
        error = PermissionError("Access denied")
        should_retry = error_handler.should_retry(error, attempt=3, max_attempts=3)
        assert should_retry is False


class TestErrorStatistics:
    """Test error statistics tracking"""

    @pytest.mark.asyncio
    async def test_statistics_tracking(self, error_handler):
        """Test error statistics are tracked correctly"""
        # Handle different types of errors
        await error_handler.handle_local_error(
            PermissionError("Access denied"), "/test1.txt", 1, 3
        )
        await error_handler.handle_local_error(
            FileNotFoundError("Not found"), "/test2.txt", 1, 3
        )
        await error_handler.handle_local_error(
            ConnectionError("Network error"), "/test3.txt", 1, 3
        )

        stats = error_handler.get_error_statistics()

        assert stats["local_errors_count"] == 1  # PermissionError
        assert stats["permanent_errors_count"] == 1  # FileNotFoundError
        assert stats["global_errors_count"] == 1  # ConnectionError
        assert stats["total_retries_performed"] == 1  # Only local error gets retry

    @pytest.mark.asyncio
    async def test_statistics_accumulation(self, error_handler):
        """Test statistics accumulate over multiple calls"""
        # Handle multiple local errors
        for i in range(3):
            await error_handler.handle_local_error(
                PermissionError(f"Error {i}"), f"/test{i}.txt", 1, 3
            )

        stats = error_handler.get_error_statistics()
        assert stats["local_errors_count"] == 3
        assert stats["total_retries_performed"] == 3

    def test_reset_statistics(self, error_handler):
        """Test statistics reset functionality"""
        # Set some statistics manually
        error_handler._local_errors_count = 5
        error_handler._global_errors_count = 2
        error_handler._permanent_errors_count = 1
        error_handler._in_global_error_state = True

        # Reset
        error_handler.reset_statistics()

        stats = error_handler.get_error_statistics()
        assert stats["local_errors_count"] == 0
        assert stats["global_errors_count"] == 0
        assert stats["permanent_errors_count"] == 0
        assert stats["total_retries_performed"] == 0
        assert stats["in_global_error_state"] is False


class TestErrorHandlingResult:
    """Test ErrorHandlingResult dataclass"""

    def test_error_handling_result_creation(self):
        """Test ErrorHandlingResult creation"""
        result = ErrorHandlingResult(
            error_type=ErrorType.LOCAL,
            retry_decision=RetryDecision.RETRY_SHORT_DELAY,
            delay_seconds=1.0,
            should_retry=True,
            error_message="Test error",
            timestamp=datetime.now(),
        )

        assert result.error_type == ErrorType.LOCAL
        assert result.is_retriable is True

    def test_is_retriable_property(self):
        """Test is_retriable property logic"""
        # Retriable result
        retriable_result = ErrorHandlingResult(
            error_type=ErrorType.LOCAL,
            retry_decision=RetryDecision.RETRY_SHORT_DELAY,
            delay_seconds=1.0,
            should_retry=True,
            error_message="Test",
            timestamp=datetime.now(),
        )
        assert retriable_result.is_retriable is True

        # Non-retriable result
        non_retriable_result = ErrorHandlingResult(
            error_type=ErrorType.PERMANENT,
            retry_decision=RetryDecision.NO_RETRY,
            delay_seconds=0.0,
            should_retry=False,
            error_message="Test",
            timestamp=datetime.now(),
        )
        assert non_retriable_result.is_retriable is False


class TestConfigurationInfo:
    """Test configuration and debugging info methods"""

    def test_get_error_statistics_structure(self, error_handler):
        """Test error statistics structure"""
        stats = error_handler.get_error_statistics()

        expected_keys = {
            "local_errors_count",
            "global_errors_count",
            "permanent_errors_count",
            "total_retries_performed",
            "in_global_error_state",
            "last_global_error_time",
            "error_handling_config",
        }
        assert set(stats.keys()) == expected_keys

        config = stats["error_handling_config"]
        assert "max_retry_attempts" in config
        assert "retry_delay_seconds" in config
        assert "global_retry_delay_seconds" in config

    def test_get_classification_info(self, error_handler):
        """Test classification info for debugging"""
        info = error_handler.get_classification_info()

        expected_keys = {
            "permanent_patterns",
            "global_patterns",
            "local_patterns",
            "default_classification",
        }
        assert set(info.keys()) == expected_keys

        # Verify pattern lists are not empty
        assert len(info["permanent_patterns"]) > 0
        assert len(info["global_patterns"]) > 0
        assert len(info["local_patterns"]) > 0


class TestEdgeCases:
    """Test edge cases and error conditions"""

    @pytest.mark.asyncio
    async def test_handle_error_with_none_file_path(self, error_handler):
        """Test handling error with None file path"""
        error = PermissionError("Access denied")
        result = await error_handler.handle_local_error(
            error, None, attempt=1, max_attempts=3
        )

        # Should still work normally
        assert result.error_type == ErrorType.LOCAL
        assert result.should_retry is True

    @pytest.mark.asyncio
    async def test_handle_error_with_zero_max_attempts(self, error_handler):
        """Test handling error with zero max attempts"""
        error = PermissionError("Access denied")
        result = await error_handler.handle_local_error(
            error, "/test.txt", attempt=1, max_attempts=0
        )

        # Should not retry if max_attempts is 0
        assert result.retry_decision == RetryDecision.NO_RETRY
        assert result.should_retry is False

    def test_classify_error_with_none_error(self, error_handler):
        """Test error classification with unusual inputs"""

        # Test with error that has no string representation
        class WeirdError(Exception):
            def __str__(self):
                return ""

        error = WeirdError()
        result = error_handler.classify_error(error)

        # Should default to LOCAL
        assert result == ErrorType.LOCAL

    @pytest.mark.asyncio
    async def test_concurrent_error_handling(self, error_handler):
        """Test concurrent error handling doesn't interfere"""
        errors = [
            PermissionError("Error 1"),
            PermissionError("Error 2"),
            PermissionError("Error 3"),
        ]

        # Handle errors concurrently
        tasks = [
            error_handler.handle_local_error(error, f"/test{i}.txt", 1, 3)
            for i, error in enumerate(errors)
        ]

        results = await asyncio.gather(*tasks)

        # All should be handled correctly
        assert len(results) == 3
        assert all(result.error_type == ErrorType.LOCAL for result in results)
        assert all(result.should_retry is True for result in results)

        # Statistics should reflect all errors
        stats = error_handler.get_error_statistics()
        assert stats["local_errors_count"] == 3
        assert stats["total_retries_performed"] == 3
