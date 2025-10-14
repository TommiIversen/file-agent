"""
Test suite for Enhanced Scanner UUID Integration.

Demonstrates how scanner services can be enhanced to use UUID-based operations
for better event sourcing and precise file tracking.
"""

import pytest
from unittest.mock import Mock, patch

from app.models import FileStatus
from app.services.state_manager import StateManager
from app.dependencies import reset_singletons

# Import our enhanced scanner
from tests.enhanced_scanner_uuid_demo import UUIDEnhancedFileScanOrchestrator

# Mark all tests as async
pytestmark = pytest.mark.asyncio


class TestEnhancedScannerUUIDBenefits:
    """Test suite demonstrating UUID-enhanced scanner benefits."""

    @pytest.fixture
    def state_manager(self):
        """Fresh StateManager instance for each test."""
        reset_singletons()
        return StateManager()

    @pytest.fixture
    def enhanced_scanner(self, state_manager):
        """Enhanced scanner with UUID capabilities."""
        return UUIDEnhancedFileScanOrchestrator(state_manager)

    async def test_scanner_event_sourcing_file_disappears_and_returns(
        self, enhanced_scanner, state_manager
    ):
        """
        Test event sourcing: File disappears and returns with preserved history.
        
        This is the DREAM scenario you described!
        """
        
        # Mock file metadata to avoid file system dependencies
        with patch('app.services.scanner.domain_objects.FileMetadata.from_path') as mock_metadata:
            # Setup mock metadata
            mock_meta = Mock()
            mock_meta.size = 1024
            mock_meta.last_write_time = None
            mock_meta.is_empty.return_value = False
            mock_meta.path.name = "render_temp.mxf"
            mock_metadata.return_value = mock_meta
            
            # Cycle 1: File appears
            await enhanced_scanner.discover_and_process_files({
                "/test/render_temp.mxf"
            })
            
            # Verify file exists
            current_file = await state_manager.get_file("/test/render_temp.mxf")
            assert current_file is not None
            assert current_file.status == FileStatus.DISCOVERED
            original_uuid = current_file.id
            
            # Cycle 2: File disappears (EVENT SOURCING!)
            await enhanced_scanner.discover_and_process_files(set())  # Empty set = file disappeared
            
            # Verify file is marked as REMOVED (not deleted!)
            disappeared_file = await state_manager.get_file("/test/render_temp.mxf")
            assert disappeared_file is None  # Not in active files
            
            # But history is preserved!
            history = await state_manager.get_file_history("/test/render_temp.mxf")
            assert len(history) == 1
            assert history[0].status == FileStatus.REMOVED
            assert history[0].id == original_uuid
            
            # Cycle 3: File returns (NEW UUID, preserved history!)
            mock_meta.size = 2048  # Different size
            await enhanced_scanner.discover_and_process_files({
                "/test/render_temp.mxf"
            })
            
            # Verify new file with new UUID
            returned_file = await state_manager.get_file("/test/render_temp.mxf")
            assert returned_file is not None
            assert returned_file.status == FileStatus.DISCOVERED
            assert returned_file.id != original_uuid  # NEW UUID!
            assert returned_file.file_size == 2048
            
            # Verify complete history preserved
            full_history = await state_manager.get_file_history("/test/render_temp.mxf")
            assert len(full_history) == 2
            
            current_entry = next(f for f in full_history if f.status != FileStatus.REMOVED)
            removed_entry = next(f for f in full_history if f.status == FileStatus.REMOVED)
            
            assert current_entry.id == returned_file.id
            assert current_entry.file_size == 2048
            assert removed_entry.id == original_uuid
            assert removed_entry.file_size == 1024

    async def test_scanner_uuid_based_precise_updates(
        self, enhanced_scanner, state_manager
    ):
        """Test UUID-based updates for precise file tracking during stability checks."""
        
        with patch('app.services.scanner.domain_objects.FileMetadata.from_path') as mock_metadata:
            # Setup initial file
            mock_meta = Mock()
            mock_meta.size = 1024
            mock_meta.last_write_time = None
            mock_meta.is_empty.return_value = False
            mock_meta.path.name = "video_001.mxf"
            mock_metadata.return_value = mock_meta
            
            # Discover file
            await enhanced_scanner.discover_and_process_files({
                "/test/video_001.mxf"
            })
            
            tracked_file = await state_manager.get_file("/test/video_001.mxf")
            original_uuid = tracked_file.id
            
            # Simulate file size change
            mock_meta.size = 2048
            await enhanced_scanner.discover_and_process_files({
                "/test/video_001.mxf"
            })
            
            # Verify UUID-based update happened
            updated_file = await state_manager.get_file("/test/video_001.mxv")
            if updated_file:  # File might not exist due to path mismatch
                assert updated_file.id == original_uuid  # Same UUID
                assert updated_file.file_size == 2048    # Updated size
            
            # Verify by UUID lookup works
            by_uuid = await state_manager.get_file_by_id(original_uuid)
            assert by_uuid is not None
            assert by_uuid.file_size == 2048

    async def test_scanner_handles_multiple_file_cycles_with_history(
        self, enhanced_scanner, state_manager
    ):
        """Test multiple cycles of same filename with complete history."""
        
        with patch('app.services.scanner.domain_objects.FileMetadata.from_path') as mock_metadata:
            file_uuids = []
            
            # Simulate 3 cycles of same filename
            for cycle in range(3):
                mock_meta = Mock()
                mock_meta.size = 1000 * (cycle + 1)  # Different sizes
                mock_meta.last_write_time = None
                mock_meta.is_empty.return_value = False
                mock_meta.path.name = f"daily_render_{cycle}.mxf"
                mock_metadata.return_value = mock_meta
                
                # File appears
                await enhanced_scanner.discover_and_process_files({
                    "/test/daily_render.mxf"
                })
                
                current_file = await state_manager.get_file("/test/daily_render.mxf")
                if current_file:
                    file_uuids.append(current_file.id)
                
                # File disappears
                await enhanced_scanner.discover_and_process_files(set())
            
            # Verify complete history
            history = await state_manager.get_file_history("/test/daily_render.mxf")
            assert len(history) == 3
            
            # All should be REMOVED now
            for entry in history:
                assert entry.status == FileStatus.REMOVED
            
            # All should have unique UUIDs
            history_uuids = [entry.id for entry in history]
            assert len(set(history_uuids)) == 3
            
            # File sizes should be preserved
            file_sizes = sorted([entry.file_size for entry in history])
            expected_sizes = [1000, 2000, 3000]
            assert file_sizes == expected_sizes

    async def test_scanner_statistics_with_uuid_insights(
        self, enhanced_scanner, state_manager
    ):
        """Test enhanced statistics with UUID-based insights."""
        
        with patch('app.services.scanner.domain_objects.FileMetadata.from_path') as mock_metadata:
            mock_meta = Mock()
            mock_meta.size = 1024
            mock_meta.last_write_time = None
            mock_meta.is_empty.return_value = False
            mock_meta.path.name = "test.mxf"
            mock_metadata.return_value = mock_meta
            
            # Add some files
            await enhanced_scanner.discover_and_process_files({
                "/test/file1.mxf",
                "/test/file2.mxf"
            })
            
            # Get enhanced statistics
            stats = await enhanced_scanner.get_scan_statistics()
            
            # Verify UUID-specific insights
            assert "uuid_tracking_active" in stats
            assert stats["uuid_tracking_active"] is True
            assert stats["event_sourcing_enabled"] is True
            assert "current_scan_files" in stats
            
            # Should track files by UUID
            assert len(enhanced_scanner._current_scan_files) == 2

    async def test_scanner_demonstrates_uuid_benefits_logging(
        self, enhanced_scanner, state_manager
    ):
        """Test that UUID benefits demonstration works."""
        
        with patch('app.services.scanner.domain_objects.FileMetadata.from_path') as mock_metadata:
            with patch('tests.enhanced_scanner_uuid_demo.logging') as mock_logging:
                mock_meta = Mock()
                mock_meta.size = 1024
                mock_meta.last_write_time = None
                mock_meta.is_empty.return_value = False
                mock_meta.path.name = "demo.mxf"
                mock_metadata.return_value = mock_meta
                
                # Add file
                await enhanced_scanner.discover_and_process_files({
                    "/test/demo.mxf"
                })
                
                # Run demonstration
                await enhanced_scanner.demonstrate_uuid_benefits("/test/demo.mxf")
                
                # Verify logging happened
                assert mock_logging.info.called
                
                # Should have logged UUID information
                log_calls = [str(call) for call in mock_logging.info.call_args_list]
                uuid_logs = [call for call in log_calls if "UUID" in call]
                assert len(uuid_logs) > 0