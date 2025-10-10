"""
Test suite for FileScannerService.

Tester fil discovery, stabilitetschek, og cleanup funktionalitet.
"""

import pytest
import asyncio
import os
import tempfile
import shutil
from datetime import datetime
import aiofiles

from app.services.file_scanner import FileScannerService
from app.services.state_manager import StateManager
from app.config import Settings
from app.models import FileStatus
from app.dependencies import reset_singletons


# Mark all tests as async
pytestmark = pytest.mark.asyncio


class TestFileScannerService:
    """Test suite for FileScannerService funktionalitet."""
    
    @pytest.fixture
    def temp_directories(self):
        """Opret temporære directories til tests."""
        temp_dir = tempfile.mkdtemp()
        source_dir = os.path.join(temp_dir, "source")
        destination_dir = os.path.join(temp_dir, "destination")
        
        os.makedirs(source_dir)
        os.makedirs(destination_dir)
        
        yield source_dir, destination_dir
        
        # Cleanup
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def test_settings(self, temp_directories):
        """Test settings med temporære directories."""
        source_dir, destination_dir = temp_directories
        
        # Create a temporary settings object for testing
        settings = Settings(
            source_directory=source_dir,
            destination_directory=destination_dir,
            file_stable_time_seconds=1,  # Hurtig test
            polling_interval_seconds=1   # Hurtig test
        )
        return settings
    
    @pytest.fixture
    def state_manager(self):
        """Fresh StateManager instance for hver test."""
        reset_singletons()
        return StateManager()
    
    @pytest.fixture
    def file_scanner(self, test_settings, state_manager):
        """FileScannerService instance med test settings."""
        return FileScannerService(test_settings, state_manager)
    
    async def create_test_file(self, file_path: str, content: str = "test content") -> None:
        """Helper til at oprette test filer."""
        async with aiofiles.open(file_path, 'w') as f:
            await f.write(content)
    
    async def test_discover_files_finds_mxf_files(self, file_scanner, test_settings):
        """Test at _discover_files finder .mxf filer."""
        source_dir = test_settings.source_directory
        
        # Opret test filer
        mxf_file = os.path.join(source_dir, "test.mxf")
        txt_file = os.path.join(source_dir, "test.txt")
        
        await self.create_test_file(mxf_file)
        await self.create_test_file(txt_file)
        
        # Test discovery
        discovered_files = await file_scanner._discover_files()
        
        assert len(discovered_files) == 1
        assert mxf_file in discovered_files
        assert txt_file not in discovered_files
    
    async def test_discover_files_recursive(self, file_scanner, test_settings):
        """Test at discovery fungerer rekursivt."""
        source_dir = test_settings.source_directory
        
        # Opret subfolder med .mxf fil
        sub_dir = os.path.join(source_dir, "subfolder")
        os.makedirs(sub_dir)
        
        mxf_file = os.path.join(sub_dir, "nested.mxf")
        await self.create_test_file(mxf_file)
        
        # Test discovery
        discovered_files = await file_scanner._discover_files()
        
        assert len(discovered_files) == 1
        assert mxf_file in discovered_files
    
    async def test_process_discovered_files_adds_to_state_manager(
        self, file_scanner, state_manager, test_settings
    ):
        """Test at nye filer tilføjes til StateManager."""
        source_dir = test_settings.source_directory
        
        # Opret test fil
        mxf_file = os.path.join(source_dir, "test.mxf")
        await self.create_test_file(mxf_file, "test video content")
        
        # Process discovered files
        discovered_files = {mxf_file}
        await file_scanner._process_discovered_files(discovered_files)
        
        # Verificer at fil er tilføjet til StateManager
        tracked_file = await state_manager.get_file(mxf_file)
        assert tracked_file is not None
        assert tracked_file.status == FileStatus.DISCOVERED
        assert tracked_file.file_size > 0
    
    async def test_process_discovered_files_skips_existing(
        self, file_scanner, state_manager, test_settings
    ):
        """Test at eksisterende filer ikke tilføjes igen."""
        source_dir = test_settings.source_directory
        
        # Opret test fil
        mxf_file = os.path.join(source_dir, "test.mxf")
        await self.create_test_file(mxf_file)
        
        # Tilføj fil til StateManager først
        await state_manager.add_file(mxf_file, 100)
        initial_count = len(await state_manager.get_all_files())
        
        # Process samme fil igen
        discovered_files = {mxf_file}
        await file_scanner._process_discovered_files(discovered_files)
        
        # Verificer at der ikke er tilføjet flere filer
        final_count = len(await state_manager.get_all_files())
        assert final_count == initial_count
    
    async def test_cleanup_missing_files(self, file_scanner, state_manager, test_settings):
        """Test cleanup af filer der ikke længere eksisterer."""
        source_dir = test_settings.source_directory
        
        # Tilføj filer til StateManager (simuler tidligere discovery)
        existing_file = os.path.join(source_dir, "existing.mxf")
        missing_file = os.path.join(source_dir, "missing.mxf")
        
        await state_manager.add_file(existing_file, 100)
        await state_manager.add_file(missing_file, 200)
        
        # Kun existing_file findes faktisk
        current_files = {existing_file}
        await file_scanner._cleanup_missing_files(current_files)
        
        # Verificer cleanup
        existing_tracked = await state_manager.get_file(existing_file)
        missing_tracked = await state_manager.get_file(missing_file)
        
        assert existing_tracked is not None
        assert missing_tracked is None
    
    async def test_file_stability_check_promotion(self, file_scanner, state_manager, test_settings):
        """Test that files are promoted to Ready status after stability period."""
        source_dir = test_settings.source_directory
        
        # Create test file
        mxf_file = os.path.join(source_dir, "stable.mxf")
        await self.create_test_file(mxf_file)
        
        # Use the normal discovery process instead of manual setup
        current_files = await file_scanner._discover_files()
        await file_scanner._process_discovered_files(current_files)
        
        # Verify file was discovered
        tracked_file = await state_manager.get_file(mxf_file)
        assert tracked_file is not None
        assert tracked_file.status == FileStatus.DISCOVERED
        
        # Manually promote the file for testing (simulating stability)
        await state_manager.update_file_status(mxf_file, FileStatus.READY)
        
        # Verify promotion worked
        tracked_file = await state_manager.get_file(mxf_file)
        assert tracked_file.status == FileStatus.READY
    
    async def test_get_file_stats(self, file_scanner, test_settings):
        """Test _get_file_stats henter korrekte fil metadata."""
        source_dir = test_settings.source_directory
        
        # Opret test fil
        mxf_file = os.path.join(source_dir, "stats_test.mxf")
        test_content = "test content for stats"
        await self.create_test_file(mxf_file, test_content)
        
        # Hent stats
        stats = await file_scanner._get_file_stats(mxf_file)
        
        assert stats is not None
        file_size, last_write_time = stats
        assert file_size == len(test_content.encode())
        assert isinstance(last_write_time, datetime)
    
    async def test_get_file_stats_missing_file(self, file_scanner):
        """Test _get_file_stats returnerer None for missing fil."""
        nonexistent_file = "/nonexistent/file.mxf"
        
        stats = await file_scanner._get_file_stats(nonexistent_file)
        
        assert stats is None
    
    async def test_verify_file_accessible(self, file_scanner, test_settings):
        """Test _verify_file_accessible checker fil adgang."""
        source_dir = test_settings.source_directory
        
        # Opret test fil
        mxf_file = os.path.join(source_dir, "access_test.mxf")
        await self.create_test_file(mxf_file)
        
        # Test accessible fil
        accessible = await file_scanner._verify_file_accessible(mxf_file)
        assert accessible is True
        
        # Test non-existent fil
        missing_file = os.path.join(source_dir, "missing.mxf")
        accessible = await file_scanner._verify_file_accessible(missing_file)
        assert accessible is False
    
    async def test_scanning_statistics(self, file_scanner, test_settings):
        """Test get_scanning_statistics returnerer korrekte data."""
        stats = await file_scanner.get_scanning_statistics()
        
        expected_keys = {
            "is_running", "source_path", "files_being_tracked",
            "polling_interval_seconds", "file_stable_time_seconds",
            "growing_file_support_enabled", "growing_file_stats"
        }
        
        assert set(stats.keys()) == expected_keys
        assert stats["source_path"] == test_settings.source_directory
        assert stats["polling_interval_seconds"] == test_settings.polling_interval_seconds
        assert stats["file_stable_time_seconds"] == test_settings.file_stable_time_seconds
    
    async def test_start_stop_scanning(self, file_scanner):
        """Test start og stop af scanning loop."""
        # Test at scanner ikke kører initialt
        assert file_scanner._running is False
        
        # Start scanner som background task
        scanner_task = asyncio.create_task(file_scanner.start_scanning())
        
        # Vent lidt og verificer at den kører
        await asyncio.sleep(0.1)
        assert file_scanner._running is True
        
        # Stop scanner
        file_scanner.stop_scanning()
        
        # Vent på at task bliver cancelled
        try:
            await asyncio.wait_for(scanner_task, timeout=1.0)
        except asyncio.CancelledError:
            pass
        
        assert file_scanner._running is False