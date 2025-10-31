"""
Tests for file_operations utilities.

Comprehensive test coverage for all pure functions in file_operations.py.
Max 400 lines as per 2:1 test ratio (200 lines production code).

Part of Fase 1.1 refactoring tests.
"""

import pytest
from pathlib import Path

from app.utils.file_operations import (
    calculate_relative_path,
    generate_conflict_free_path,
    build_destination_path,
)


class TestCalculateRelativePath:
    """Test calculate_relative_path function."""

    def test_simple_file_in_base(self):
        """Test file directly in base directory."""
        source_path = Path("/src/video.mxf")
        source_base = Path("/src")

        result = calculate_relative_path(source_path, source_base)

        assert result == Path("video.mxf")

    def test_file_in_subdirectory(self):
        """Test file in subdirectory structure."""
        source_path = Path("/src/recordings/stream1/video.mxf")
        source_base = Path("/src")

        result = calculate_relative_path(source_path, source_base)

        assert result == Path("recordings/stream1/video.mxf")

    def test_file_outside_base_directory(self):
        """Test file outside base directory returns just filename."""
        source_path = Path("/other/location/video.mxf")
        source_base = Path("/src")

        result = calculate_relative_path(source_path, source_base)

        assert result == Path("video.mxf")

    def test_windows_paths(self):
        """Test with Windows-style paths."""
        source_path = Path("C:/src/folder/video.mxf")
        source_base = Path("C:/src")

        result = calculate_relative_path(source_path, source_base)

        assert result == Path("folder/video.mxf")


class TestGenerateConflictFreePath:
    """Test generate_conflict_free_path function."""

    def test_no_conflict(self, tmp_path):
        """Test when no conflict exists."""
        dest_path = tmp_path / "video.mxf"

        result = generate_conflict_free_path(dest_path)

        assert result == dest_path

    def test_single_conflict(self, tmp_path):
        """Test with one existing file."""
        dest_path = tmp_path / "video.mxf"
        dest_path.touch()  # Create conflicting file

        result = generate_conflict_free_path(dest_path)

        assert result == tmp_path / "video_1.mxf"
        assert not result.exists()

    def test_multiple_conflicts(self, tmp_path):
        """Test with multiple existing files."""
        base_path = tmp_path / "video.mxf"
        base_path.touch()
        (tmp_path / "video_1.mxf").touch()
        (tmp_path / "video_2.mxf").touch()

        result = generate_conflict_free_path(base_path)

        assert result == tmp_path / "video_3.mxf"
        assert not result.exists()

    def test_different_extensions(self, tmp_path):
        """Test with different file extensions."""
        dest_path = tmp_path / "archive.tar.gz"
        dest_path.touch()

        result = generate_conflict_free_path(dest_path)

        assert result == tmp_path / "archive_1.tar.gz"

    def test_no_extension(self, tmp_path):
        """Test with file without extension."""
        dest_path = tmp_path / "README"
        dest_path.touch()

        result = generate_conflict_free_path(dest_path)

        assert result == tmp_path / "README_1"

    def test_max_conflicts_raises_error(self, tmp_path):
        """Test that excessive conflicts raise RuntimeError."""
        dest_path = tmp_path / "video.mxf"

        # Mock exists() to always return True (simulating infinite conflicts)
        original_exists = Path.exists
        Path.exists = lambda self: True

        try:
            with pytest.raises(
                RuntimeError,
                match="Could not resolve name conflict after 9999 attempts",
            ):
                generate_conflict_free_path(dest_path)
        finally:
            Path.exists = original_exists




class TestBuildDestinationPath:
    """Test build_destination_path function."""

    def test_simple_file(self):
        """Test building path for simple file."""
        source_path = Path("/src/video.mxf")
        source_base = Path("/src")
        dest_base = Path("/dest")

        result = build_destination_path(source_path, source_base, dest_base)

        assert result == Path("/dest/video.mxf")

    def test_subdirectory_structure(self):
        """Test preserving subdirectory structure."""
        source_path = Path("/src/recordings/stream1/video.mxf")
        source_base = Path("/src")
        dest_base = Path("/dest")

        result = build_destination_path(source_path, source_base, dest_base)

        assert result == Path("/dest/recordings/stream1/video.mxf")

    def test_file_outside_source_base(self):
        """Test file outside source base uses just filename."""
        source_path = Path("/other/video.mxf")
        source_base = Path("/src")
        dest_base = Path("/dest")

        result = build_destination_path(source_path, source_base, dest_base)

        assert result == Path("/dest/video.mxf")

