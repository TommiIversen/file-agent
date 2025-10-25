"""
Tests for file discovery functionality - now integrated in FileScanOrchestrator.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.scanner.file_scanner import FileScanner
from app.services.scanner.domain_objects import ScanConfiguration
from app.services.state_manager import StateManager
from app.config import Settings


class TestFileDiscovery:
    """Test the file discovery functionality integrated in FileScanOrchestrator."""

    @pytest.fixture
    def config(self):
        return ScanConfiguration(
            source_directory="test_source",
            polling_interval_seconds=10,
            file_stable_time_seconds=120,
            keep_files_hours=336,
        )

    @pytest.fixture
    def mock_state_manager(self):
        """Create a mock StateManager for testing."""
        return MagicMock(spec=StateManager)

    @pytest.fixture
    def orchestrator(self, config, mock_state_manager):
        settings = MagicMock(spec=Settings)
        settings.growing_file_min_size_mb = 100
        settings.growing_file_poll_interval_seconds = 5
        settings.growing_file_safety_margin_mb = 50
        settings.growing_file_growth_timeout_seconds = 300
        settings.growing_file_chunk_size_kb = 2048
        return FileScanner(config, mock_state_manager, settings=settings)

    @pytest.mark.asyncio
    async def test_discover_all_files_success(self, orchestrator):
        """Test successful file discovery."""
        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock) as mock_exists,
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock) as mock_isdir,
            patch("os.walk") as mock_walk,
        ):
            mock_exists.return_value = True
            mock_isdir.return_value = True
            mock_walk.return_value = [
                (
                    "/test/source",
                    [],
                    ["file1.mxf", "file2.MXF", "file3.mp4", "test_file.mxf"],
                )
            ]

            files = await orchestrator._discover_all_files()

            # Should find 2 files (excluding .mp4 and test_file)
            assert len(files) == 2
            file_paths = {str(f) for f in files}
            assert any("file1.mxf" in path for path in file_paths)
            assert any("file2.MXF" in path for path in file_paths)

    @pytest.mark.asyncio
    async def test_discover_source_not_exists(self, orchestrator):
        """Test when source directory doesn't exist."""
        with patch("aiofiles.os.path.exists", new_callable=AsyncMock) as mock_exists:
            mock_exists.return_value = False

            files = await orchestrator._discover_all_files()
            assert len(files) == 0

    @pytest.mark.asyncio
    async def test_discover_source_not_directory(self, orchestrator):
        """Test when source path is not a directory."""
        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock) as mock_exists,
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock) as mock_isdir,
        ):
            mock_exists.return_value = True
            mock_isdir.return_value = False

            files = await orchestrator._discover_all_files()
            assert len(files) == 0

    @pytest.mark.asyncio
    async def test_discover_handles_exception(self, orchestrator):
        """Test that exceptions are handled gracefully."""
        with patch("aiofiles.os.path.exists", new_callable=AsyncMock) as mock_exists:
            mock_exists.side_effect = Exception("Test error")

            files = await orchestrator._discover_all_files()
            assert len(files) == 0  # Should return empty set on error

    @pytest.mark.asyncio
    async def test_filters_ignored_files(self, orchestrator):
        """Test that ignored files are filtered out."""
        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock) as mock_exists,
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock) as mock_isdir,
            patch("os.walk") as mock_walk,
        ):
            mock_exists.return_value = True
            mock_isdir.return_value = True
            mock_walk.return_value = [
                (
                    "/test/source",
                    [],
                    [
                        "normal.mxf",  # Should be included
                        "test_file.mxf",  # Should be filtered out
                        ".hidden.mxf",  # Should be filtered out
                        "another.mp4",  # Should be filtered out (not MXF)
                    ],
                )
            ]

            files = await orchestrator._discover_all_files()

            assert len(files) == 1
            file_paths = {str(f) for f in files}
            assert any("normal.mxf" in path for path in file_paths)
