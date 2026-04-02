"""
Tests for ProcessResult.__str__ — covers all branch combinations.
"""
import pytest

from app.domains.file_processing.consumer.job_models import ProcessResult


class TestProcessResultStr:
    """Tests for ProcessResult.__str__ method."""

    def test_success_no_extras(self):
        result = ProcessResult(success=True, file_path="/test/file.mxf")
        assert "SUCCESS" in str(result)
        assert "/test/file.mxf" in str(result)
        assert "retry" not in str(result)

    def test_failed_no_extras(self):
        result = ProcessResult(success=False, file_path="/test/file.mxf")
        assert "FAILED" in str(result)
        assert "/test/file.mxf" in str(result)

    def test_failed_with_retry(self):
        result = ProcessResult(
            success=False, file_path="/test/file.mxf", should_retry=True
        )
        s = str(result)
        assert "FAILED" in s
        assert "retry=true" in s

    def test_failed_with_retry_scheduled(self):
        result = ProcessResult(
            success=False,
            file_path="/test/file.mxf",
            should_retry=True,
            retry_scheduled=True,
        )
        s = str(result)
        assert "retry=true" in s
        assert "scheduled=true" in s

    def test_failed_with_space_shortage(self):
        result = ProcessResult(
            success=False, file_path="/test/file.mxf", space_shortage=True
        )
        s = str(result)
        assert "space_shortage=true" in s

    def test_failed_with_all_extras(self):
        result = ProcessResult(
            success=False,
            file_path="/test/file.mxf",
            should_retry=True,
            retry_scheduled=True,
            space_shortage=True,
        )
        s = str(result)
        assert "FAILED" in s
        assert "retry=true" in s
        assert "scheduled=true" in s
        assert "space_shortage=true" in s

    def test_success_with_error_message_ignored_in_str(self):
        result = ProcessResult(
            success=True, file_path="/test/ok.mxf", error_message="some warning"
        )
        s = str(result)
        assert "SUCCESS" in s

    def test_failed_with_only_scheduled(self):
        result = ProcessResult(
            success=False, file_path="/test/file.mxf", retry_scheduled=True
        )
        s = str(result)
        assert "scheduled=true" in s
        assert "retry=true" not in s
