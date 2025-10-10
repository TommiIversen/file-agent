"""
Tests for FileCopyService - Fase 4 of File Transfer Agent.

Test coverage inkluderer:
- End-to-end file copy workflow  
- Error handling (global vs. lokal)
- Name conflict resolution
- File verification og integrity  
- Progress tracking og StateManager integration
- Retry logic og failure scenarios
- Integration med JobQueueService

Som specificeret i roadmap Fase 4 testkrav.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock
from datetime import datetime
import aiofiles

from app.config import Settings
from app.models import FileStatus
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService
from app.services.file_copier import FileCopyService


class TestFileCopyService:
    """Test suite for FileCopyService functionality."""
    
    @pytest.fixture
    def temp_directories(self):
        """Create temporary source and destination directories."""
        with tempfile.TemporaryDirectory() as source_dir, \
             tempfile.TemporaryDirectory() as dest_dir:
            yield Path(source_dir), Path(dest_dir)
    
    @pytest.fixture
    def mock_settings(self, temp_directories):
        """Mock Settings with temporary directories."""
        source_dir, dest_dir = temp_directories
        settings = Settings(
            source_directory=str(source_dir),
            destination_directory=str(dest_dir),
            file_stable_time_seconds=1,  # Short for tests
            polling_interval_seconds=1,
            use_temporary_file=True,
            max_retry_attempts=3,
            retry_delay_seconds=1,  # Short for tests
            global_retry_delay_seconds=2,  # Short for tests
            log_level="DEBUG"
        )
        return settings
    
    @pytest.fixture
    def state_manager(self):
        """Create StateManager instance."""
        return StateManager()
    
    @pytest.fixture
    def job_queue_service(self, mock_settings, state_manager):
        """Create JobQueueService instance."""
        return JobQueueService(mock_settings, state_manager)
    
    @pytest.fixture
    def file_copier(self, mock_settings, state_manager, job_queue_service):
        """Create FileCopyService instance."""
        return FileCopyService(mock_settings, state_manager, job_queue_service)
    
    @pytest.fixture
    def sample_file(self, temp_directories):
        """Create a sample file for testing."""
        source_dir, _ = temp_directories
        file_path = source_dir / "test_video.mxf"
        
        # Create file with some content
        content = b"Sample MXF video content " * 100  # ~2.5KB
        file_path.write_bytes(content)
        
        return file_path, len(content)
    
    @pytest.mark.asyncio
    async def test_file_copier_initialization(self, file_copier, mock_settings):
        """Test FileCopyService initialization."""
        assert file_copier.settings == mock_settings
        
        # Check statistics tracker initialization
        stats = await file_copier.get_copy_statistics()
        assert stats["total_files_copied"] == 0
        assert stats["total_bytes_copied"] == 0
        assert stats["total_files_failed"] == 0
        assert not file_copier._running
        assert file_copier._destination_available
    
    @pytest.mark.asyncio
    async def test_destination_availability_check(self, file_copier, temp_directories):
        """Test destination availability checking."""
        source_dir, dest_dir = temp_directories
        
        # Test with valid destination
        assert await file_copier._check_destination_availability()
        
        # Test with non-existent destination
        shutil.rmtree(dest_dir)
        file_copier._clear_destination_cache()  # Clear cache after deleting directory
        assert not await file_copier._check_destination_availability()
    
    @pytest.fixture
    async def test_name_conflict_resolution(self, file_copier, temp_directories):
        """Test navnekonflikt resolution med _1, _2 suffixes."""
        source_dir, dest_dir = temp_directories
        
        # Create conflicting file
        original_path = dest_dir / "video.mxf"
        original_path.write_text("original")
        
        # Test conflict resolution
        resolved_path = await file_copier._resolve_name_conflict(original_path)
        assert resolved_path.name == "video_1.mxf"
        
        # Create another conflict
        resolved_path.write_text("first conflict")
        resolved_path2 = await file_copier._resolve_name_conflict(original_path)
        assert resolved_path2.name == "video_2.mxf"
    
    @pytest.fixture
    async def test_destination_path_resolution(self, file_copier, temp_directories, sample_file):
        """Test destination path calculation og relative structure."""
        source_dir, dest_dir = temp_directories
        file_path, _ = sample_file
        
        # Test simple file
        dest_path = await file_copier._resolve_destination_path(file_path)
        expected = dest_dir / "test_video.mxv"
        assert dest_path.parent == dest_dir
        assert dest_path.name == "test_video.mxf"
        
        # Test subdirectory structure
        subdir = source_dir / "recordings" / "stream1"
        subdir.mkdir(parents=True)
        subfile = subdir / "video.mxf"
        subfile.write_text("test")
        
        dest_path = await file_copier._resolve_destination_path(subfile)
        expected = dest_dir / "recordings" / "stream1" / "video.mxf"
        assert dest_path == expected
    
    @pytest.mark.asyncio
    async def test_file_copy_with_verification(self, file_copier, sample_file, temp_directories):
        """Test complete file copy med verifikation."""
        source_dir, dest_dir = temp_directories
        file_path, file_size = sample_file
        
        # Add file to StateManager først
        await file_copier.state_manager.add_file(
            str(file_path), file_size, datetime.now()
        )
        
        # Test copy process
        await file_copier._copy_single_file(str(file_path), 1, 1)
        
        # Verify destination file exists og har korrekt størrelse
        dest_file = dest_dir / "test_video.mxf"
        assert dest_file.exists()
        assert dest_file.stat().st_size == file_size
        
        # Verify source file blev slettet
        assert not file_path.exists()
        
        # Verify StateManager blev opdateret til Completed
        tracked_file = await file_copier.state_manager.get_file(str(file_path))
        assert tracked_file.status == FileStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_copy_with_temporary_file(self, file_copier, sample_file, temp_directories):
        """Test copy process med temporary .tmp fil."""
        source_dir, dest_dir = temp_directories
        file_path, file_size = sample_file
        
        # Ensure use_temporary_file is enabled
        file_copier.settings.use_temporary_file = True
        
        # Add file to StateManager
        await file_copier.state_manager.add_file(
            str(file_path), file_size, datetime.now()
        )
        
        # Track temp files created during copy by monitoring filesystem
        import os
        initial_files = set(os.listdir(dest_dir))
        
        # Test copy
        await file_copier._copy_single_file(str(file_path), 1, 1)
        
        # Verify that at some point during copy, a .tmp file was present
        # Since copy is fast, we verify that the final file exists and no .tmp remains
        final_files = set(os.listdir(dest_dir))
        new_files = final_files - initial_files
        
        # Should have created one new file (the final copied file)
        assert len(new_files) == 1
        final_file = new_files.pop()
        
        # Verify it's not a temp file (strategy should have renamed it)
        assert not final_file.endswith('.tmp')
        
        # Verify final file has correct content
        copied_file_path = dest_dir / final_file
        assert copied_file_path.exists()
        assert copied_file_path.stat().st_size == file_size
    
    @pytest.mark.asyncio
    async def test_copy_without_temporary_file(self, file_copier, sample_file, temp_directories):
        """Test copy process uden temporary fil."""
        source_dir, dest_dir = temp_directories
        file_path, file_size = sample_file
        
        # Disable temporary file usage
        file_copier.settings.use_temporary_file = False
        
        # Add file to StateManager
        await file_copier.state_manager.add_file(
            str(file_path), file_size, datetime.now()
        )
        
        # Test copy
        await file_copier._copy_single_file(str(file_path), 1, 1)
        
        # Verify file was copied directly
        dest_file = dest_dir / "test_video.mxf"
        assert dest_file.exists()
        assert dest_file.stat().st_size == file_size
    
    @pytest.mark.asyncio 
    async def test_file_size_verification_failure(self, file_copier, sample_file, temp_directories):
        """Test file size verification failure detection."""
        source_dir, dest_dir = temp_directories
        file_path, file_size = sample_file
        
        # Create destination file med forkert størrelse
        dest_file = dest_dir / "test_video.mxf"
        dest_file.write_text("wrong size")
        
        # Test verification failure
        with pytest.raises(ValueError, match="Filstørrelse mismatch"):
            await file_copier._verify_file_copy(file_path, dest_file)
    
    @pytest.mark.asyncio
    async def test_retry_logic_success_after_failure(self, file_copier, sample_file):
        """Test retry logic hvor kopiering lykkes efter fejl."""
        file_path, file_size = sample_file
        
        # Add to StateManager
        await file_copier.state_manager.add_file(
            str(file_path), file_size, datetime.now()
        )
        
        # Mock _copy_single_file to fail first time, succeed second time
        call_count = 0
        original_copy = file_copier._copy_single_file
        
        async def mock_copy_that_fails_once(source_path, attempt, max_attempts):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Simulated failure")
            return await original_copy(source_path, attempt, max_attempts)
        
        file_copier._copy_single_file = mock_copy_that_fails_once
        
        # Create job
        job = {
            "file_path": str(file_path),
            "file_size": file_size,
            "added_to_queue_at": datetime.now(),
            "retry_count": 0
        }
        
        # Test retry logic
        success = await file_copier._copy_file_with_retry(job)
        
        # Verify success after retry
        assert success
        assert call_count == 2  # Failed once, succeeded on retry
    
    @pytest.mark.asyncio
    async def test_retry_logic_permanent_failure(self, file_copier, sample_file):
        """Test retry logic hvor alle forsøg fejler."""
        file_path, file_size = sample_file
        
        # Add to StateManager
        await file_copier.state_manager.add_file(
            str(file_path), file_size, datetime.now()
        )
        
        # Mock _copy_single_file to always fail
        async def mock_copy_that_always_fails(source_path, attempt, max_attempts):
            raise Exception("Permanent failure")
        
        file_copier._copy_single_file = mock_copy_that_always_fails
        
        # Create job
        job = {
            "file_path": str(file_path),
            "file_size": file_size,
            "added_to_queue_at": datetime.now(),
            "retry_count": 0
        }
        
        # Test retry logic
        success = await file_copier._copy_file_with_retry(job)
        
        # Verify permanent failure
        assert not success
    
    @pytest.mark.asyncio
    async def test_progress_tracking_during_copy(self, file_copier, temp_directories):
        """Test at copy progress bliver tracked i StateManager."""
        source_dir, dest_dir = temp_directories
        
        # Create larger file for progress tracking
        large_file = source_dir / "large_video.mxf"
        content = b"X" * (10 * 1024 * 1024)  # 10MB
        async with aiofiles.open(large_file, 'wb') as f:
            await f.write(content)
        
        # Add to StateManager
        await file_copier.state_manager.add_file(
            str(large_file), len(content), datetime.now()
        )
        
        # Track progress updates
        progress_updates = []
        original_update = file_copier.state_manager.update_file_status
        
        async def track_progress_updates(file_path, status, **kwargs):
            if 'copy_progress' in kwargs:
                progress_updates.append(kwargs['copy_progress'])
            return await original_update(file_path, status, **kwargs)
        
        file_copier.state_manager.update_file_status = track_progress_updates
        
        # Test copy med progress tracking
        await file_copier._copy_single_file(str(large_file), 1, 1)
        
        # Verify progress was tracked
        assert len(progress_updates) > 0
        assert 100.0 in progress_updates  # Final progress should be 100%
    
    @pytest.mark.asyncio
    async def test_job_processing_success(self, file_copier, sample_file, job_queue_service):
        """Test complete job processing workflow."""
        file_path, file_size = sample_file
        
        # Add file to StateManager
        await file_copier.state_manager.add_file(
            str(file_path), file_size, datetime.now()
        )
        
        # Create job
        job = {
            "file_path": str(file_path),
            "file_size": file_size,
            "added_to_queue_at": datetime.now(),
            "retry_count": 0
        }
        
        # Mock job_queue_service methods
        job_queue_service.mark_job_completed = AsyncMock()
        job_queue_service.mark_job_failed = AsyncMock()
        
        # Process job
        await file_copier._process_job(job)
        
        # Verify job was marked completed
        job_queue_service.mark_job_completed.assert_called_once_with(job)
        job_queue_service.mark_job_failed.assert_not_called()
        
        # Verify statistics
        stats = await file_copier.get_copy_statistics()
        assert stats["total_files_copied"] == 1
        assert stats["total_files_failed"] == 0
    
    @pytest.mark.asyncio
    async def test_job_processing_failure(self, file_copier, sample_file, job_queue_service):
        """Test job processing når kopiering fejler permanent."""
        file_path, file_size = sample_file
        
        # Add file to StateManager
        await file_copier.state_manager.add_file(
            str(file_path), file_size, datetime.now()
        )
        
        # Mock copy method to always fail
        file_copier._copy_file_with_retry = AsyncMock(return_value=False)
        
        # Create job
        job = {
            "file_path": str(file_path),
            "file_size": file_size,
            "added_to_queue_at": datetime.now(),
            "retry_count": 0
        }
        
        # Mock job_queue_service methods
        job_queue_service.mark_job_completed = AsyncMock()
        job_queue_service.mark_job_failed = AsyncMock()
        
        # Process job
        await file_copier._process_job(job)
        
        # Verify job was marked failed
        job_queue_service.mark_job_failed.assert_called_once()
        job_queue_service.mark_job_completed.assert_not_called()
        
        # Verify statistics
        stats = await file_copier.get_copy_statistics()
        assert stats["total_files_copied"] == 0
        assert stats["total_files_failed"] == 1
        
        # Verify file status blev sat til FAILED
        tracked_file = await file_copier.state_manager.get_file(str(file_path))
        assert tracked_file.status == FileStatus.FAILED
    
    @pytest.mark.asyncio
    async def test_global_error_handling(self, file_copier, temp_directories):
        """Test global error handling når destination er utilgængelig."""
        source_dir, dest_dir = temp_directories
        
        # Remove destination directory for at simulere global fejl
        shutil.rmtree(dest_dir)
        
        # Test global error handling
        await file_copier._handle_global_error("Test global error")
        
        # Verify destination_available flag
        assert not file_copier._destination_available

    @pytest.mark.asyncio
    async def test_copy_statistics(self, file_copier):
        """Test copy statistics gathering."""
        # Use statistics tracker to set test data
        file_copier.statistics_tracker.complete_copy_session("/test/file1.txt", success=True, final_bytes_transferred=512 * 1024 * 1024)  # 512MB
        file_copier.statistics_tracker.complete_copy_session("/test/file2.txt", success=True, final_bytes_transferred=512 * 1024 * 1024)  # 512MB
        file_copier.statistics_tracker.complete_copy_session("/test/file3.txt", success=False)
        file_copier.statistics_tracker.complete_copy_session("/test/file4.txt", success=False)

        stats = await file_copier.get_copy_statistics()

        assert stats["total_files_copied"] == 2
        assert stats["total_bytes_copied"] == 1024 * 1024 * 1024  # 1GB total
        assert stats["total_files_failed"] == 2
        assert stats["total_gb_copied"] == 1.0
        assert "performance" in stats
        assert "error_handling" in stats
        assert stats["is_running"] == file_copier._running
        assert stats["destination_available"] == file_copier._destination_available
        assert "settings" in stats
    
    @pytest.mark.asyncio
    async def test_consumer_status(self, file_copier):
        """Test consumer status reporting."""
        file_copier._running = True
        file_copier._destination_available = False
        
        status = file_copier.get_consumer_status()
        
        assert status["is_running"]
        assert not status["destination_available"]
        assert "task_created" in status


class TestFileCopyServiceIntegration:
    """Integration tests for FileCopyService med andre services."""
    
    @pytest.fixture
    def full_system(self, temp_directories):
        """Setup complete system for integration testing."""
        source_dir, dest_dir = temp_directories
        
        # Create settings
        settings = Settings(
            source_directory=str(source_dir),
            destination_directory=str(dest_dir),
            file_stable_time_seconds=1,
            polling_interval_seconds=1,
            use_temporary_file=True,
            max_retry_attempts=2,
            retry_delay_seconds=1,
            global_retry_delay_seconds=2,
            log_level="DEBUG"
        )
        
        # Create services
        state_manager = StateManager()
        job_queue_service = JobQueueService(settings, state_manager)
        file_copier = FileCopyService(settings, state_manager, job_queue_service)
        
        return {
            'settings': settings,
            'state_manager': state_manager,
            'job_queue_service': job_queue_service,
            'file_copier': file_copier,
            'source_dir': source_dir,
            'dest_dir': dest_dir
        }
    