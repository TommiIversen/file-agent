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
    validate_file_sizes,
    create_temp_file_path,
    build_destination_path,
    resolve_destination_with_conflicts,
    validate_source_file,
    validate_file_copy_integrity,
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
            with pytest.raises(RuntimeError, match="Could not resolve name conflict after 9999 attempts"):
                generate_conflict_free_path(dest_path)
        finally:
            Path.exists = original_exists


class TestValidateFileSizes:
    """Test validate_file_sizes function."""
    
    def test_matching_sizes(self):
        """Test when file sizes match."""
        assert validate_file_sizes(1024, 1024) is True
        assert validate_file_sizes(0, 0) is True
        assert validate_file_sizes(1000000, 1000000) is True
    
    def test_different_sizes(self):
        """Test when file sizes don't match."""
        assert validate_file_sizes(1024, 1023) is False
        assert validate_file_sizes(1000, 2000) is False
        assert validate_file_sizes(0, 1) is False


class TestCreateTempFilePath:
    """Test create_temp_file_path function."""
    
    def test_simple_extension(self):
        """Test with simple file extension."""
        dest_path = Path("/dest/video.mxf")
        
        result = create_temp_file_path(dest_path)
        
        assert result == Path("/dest/video.mxf.tmp")
    
    def test_multiple_extensions(self):
        """Test with multiple file extensions."""
        dest_path = Path("/dest/archive.tar.gz")
        
        result = create_temp_file_path(dest_path)
        
        assert result == Path("/dest/archive.tar.gz.tmp")
    
    def test_no_extension(self):
        """Test with file without extension."""
        dest_path = Path("/dest/README")
        
        result = create_temp_file_path(dest_path)
        
        assert result == Path("/dest/README.tmp")


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


class TestResolveDestinationWithConflicts:
    """Test resolve_destination_with_conflicts function."""
    
    def test_no_conflicts(self, tmp_path):
        """Test when no conflicts exist."""
        source_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        
        source_file = source_dir / "video.mxf"
        
        result = resolve_destination_with_conflicts(source_file, source_dir, dest_dir)
        
        assert result == dest_dir / "video.mxf"
    
    def test_with_conflicts(self, tmp_path):
        """Test conflict resolution."""
        source_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        
        source_file = source_dir / "video.mxf"
        conflicting_file = dest_dir / "video.mxf"
        conflicting_file.touch()
        
        result = resolve_destination_with_conflicts(source_file, source_dir, dest_dir)
        
        assert result == dest_dir / "video_1.mxf"
    
    def test_subdirectory_with_conflicts(self, tmp_path):
        """Test subdirectory preservation with conflict resolution."""
        source_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        
        subdir = dest_dir / "recordings"
        subdir.mkdir()
        
        source_file = source_dir / "recordings" / "video.mxf"
        conflicting_file = dest_dir / "recordings" / "video.mxf"
        conflicting_file.touch()
        
        result = resolve_destination_with_conflicts(source_file, source_dir, dest_dir)
        
        assert result == dest_dir / "recordings" / "video_1.mxf"


class TestValidateSourceFile:
    """Test validate_source_file function."""
    
    def test_valid_file(self, tmp_path):
        """Test with valid existing file."""
        file_path = tmp_path / "video.mxf"
        file_path.write_text("test content")
        
        # Should not raise any exception
        validate_source_file(file_path)
    
    def test_nonexistent_file(self, tmp_path):
        """Test with non-existent file."""
        file_path = tmp_path / "missing.mxf"
        
        with pytest.raises(FileNotFoundError, match="Source file does not exist"):
            validate_source_file(file_path)
    
    def test_directory_instead_of_file(self, tmp_path):
        """Test with directory instead of file."""
        dir_path = tmp_path / "not_a_file"
        dir_path.mkdir()
        
        with pytest.raises(ValueError, match="Source path is not a regular file"):
            validate_source_file(dir_path)


class TestValidateFileCopyIntegrity:
    """Test validate_file_copy_integrity function."""
    
    def test_matching_file_sizes(self, tmp_path):
        """Test with matching file sizes."""
        source_file = tmp_path / "source.mxf"
        dest_file = tmp_path / "dest.mxf"
        
        content = b"test content"
        source_file.write_bytes(content)
        dest_file.write_bytes(content)
        
        # Should not raise any exception
        validate_file_copy_integrity(source_file, dest_file)
    
    def test_mismatched_file_sizes(self, tmp_path):
        """Test with different file sizes."""
        source_file = tmp_path / "source.mxf"
        dest_file = tmp_path / "dest.mxf"
        
        source_file.write_bytes(b"longer content")
        dest_file.write_bytes(b"short")
        
        with pytest.raises(ValueError, match="File size mismatch"):
            validate_file_copy_integrity(source_file, dest_file)


class TestIntegrationScenarios:
    """Integration tests combining multiple functions."""
    
    def test_complete_workflow_no_conflicts(self, tmp_path):
        """Test complete workflow without conflicts."""
        source_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        
        # Create source file
        source_file = source_dir / "recordings" / "video.mxf"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("test content")
        
        # Validate source
        validate_source_file(source_file)
        
        # Build destination path
        dest_path = resolve_destination_with_conflicts(source_file, source_dir, dest_dir)
        
        # Create temp path
        temp_path = create_temp_file_path(dest_path)
        
        # Verify expected paths
        assert dest_path == dest_dir / "recordings" / "video.mxf"
        assert temp_path == dest_dir / "recordings" / "video.mxf.tmp"
    
    def test_complete_workflow_with_conflicts(self, tmp_path):
        """Test complete workflow with conflicts."""
        source_dir = tmp_path / "src" 
        dest_dir = tmp_path / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        
        # Create source file
        source_file = source_dir / "video.mxf"
        source_file.write_text("test content")
        
        # Create conflicting destination
        conflict_file = dest_dir / "video.mxf"
        conflict_file.write_text("existing content")
        
        # Resolve destination with conflicts
        final_dest = resolve_destination_with_conflicts(source_file, source_dir, dest_dir)
        
        # Should resolve to video_1.mxf
        assert final_dest == dest_dir / "video_1.mxf"
        assert not final_dest.exists()  # Conflict-free path
        
        # Create temp path
        temp_path = create_temp_file_path(final_dest)
        assert temp_path == dest_dir / "video_1.mxf.tmp"