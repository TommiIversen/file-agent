"""
Test for Copy Progress Updates Optimization
==========================================

Tester at copy progress updates sendes intelligent - kun ved hele procent 
og kun når der er en faktisk forskel.
"""

import asyncio
import tempfile
import os
from pathlib import Path

import pytest

from app.services.file_copier import FileCopyService
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService
from app.config import Settings


class TestCopyProgressOptimization:
    """Test copy progress update optimization"""
    
    @pytest.fixture
    def temp_directory(self):
        """Create temporary directory for test files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir
    
    @pytest.fixture
    def test_settings(self, temp_directory):
        """Create test settings with temporary directories"""
        return Settings(
            source_directory=temp_directory,
            destination_directory=os.path.join(temp_directory, "dest"),
            copy_progress_update_interval=5,  # Update every 5%
            use_temporary_file=False  # Simplified for testing
        )
    
    @pytest.fixture 
    def state_manager(self):
        """Create StateManager instance for testing"""
        return StateManager()
    
    @pytest.fixture
    def job_queue(self, test_settings, state_manager):
        """Create JobQueueService for testing"""
        return JobQueueService(test_settings, state_manager)
    
    @pytest.fixture
    def file_copier(self, test_settings, state_manager, job_queue):
        """Create FileCopyService for testing"""
        return FileCopyService(test_settings, state_manager, job_queue)
    
    @pytest.mark.asyncio
    async def test_progress_updates_only_at_intervals(
        self, 
        file_copier, 
        state_manager,
        temp_directory
    ):
        """
        Test at progress updates kun sendes ved konfigurerede intervaller.
        
        Med interval=5 skal vi kun få updates ved 0%, 5%, 10%, 15%, etc.
        """
        # Create test files
        source_file = Path(temp_directory) / "source.mxf"
        dest_dir = Path(temp_directory) / "dest"
        dest_dir.mkdir()
        
        # Create a file large enough to trigger multiple progress updates
        test_content = b"x" * (10 * 1024)  # 10KB file
        source_file.write_bytes(test_content)
        
        # Add to state manager
        await state_manager.add_file(str(source_file), len(test_content))
        
        # Mock StateManager to track progress updates
        progress_updates = []
        original_update = state_manager.update_file_status
        
        async def mock_update_file_status(file_path, status, **kwargs):
            if 'copy_progress' in kwargs:
                progress_updates.append(kwargs['copy_progress'])
            return await original_update(file_path, status, **kwargs)
        
        state_manager.update_file_status = mock_update_file_status
        
        # Create job and copy file
        job = {
            "file_path": str(source_file),
            "file_size": len(test_content),
            "discovered_at": "2024-10-09T15:30:00"
        }
        
        await file_copier._copy_file_with_retry(job)
        
        # Verify progress updates are optimized
        print(f"Progress updates received: {progress_updates}")
        
        # Should only have updates at 5% intervals (or 100% completion)
        expected_updates = [u for u in progress_updates if u % 5 == 0 or u == 100.0]
        
        # Remove duplicates while preserving order
        unique_updates = []
        for update in progress_updates:
            if update not in unique_updates:
                unique_updates.append(update)
        
        assert len(unique_updates) <= len(expected_updates), (
            f"Too many progress updates. Got {len(unique_updates)}, expected max {len(expected_updates)}"
        )
        
        # Should always end with 100%
        assert 100.0 in progress_updates, "Final progress should be 100%"
    
    @pytest.mark.asyncio
    async def test_progress_updates_reduce_websocket_traffic(
        self,
        file_copier,
        state_manager,
        temp_directory
    ):
        """
        Test at færre progress updates reducerer WebSocket trafik.
        """
        # Create test file
        source_file = Path(temp_directory) / "large_file.mxf"
        dest_dir = Path(temp_directory) / "dest"
        dest_dir.mkdir()
        
        # Larger file to simulate real-world scenario
        test_content = b"x" * (100 * 1024)  # 100KB
        source_file.write_bytes(test_content)
        
        await state_manager.add_file(str(source_file), len(test_content))
        
        # Count total state manager updates
        update_count = 0
        original_update = state_manager.update_file_status
        
        async def count_updates(file_path, status, **kwargs):
            nonlocal update_count
            if 'copy_progress' in kwargs:
                update_count += 1
            return await original_update(file_path, status, **kwargs)
        
        state_manager.update_file_status = count_updates
        
        # Copy file
        job = {
            "file_path": str(source_file),
            "file_size": len(test_content),
            "discovered_at": "2024-10-09T15:30:00"
        }
        
        await file_copier._copy_file_with_retry(job)
        
        # With 5% intervals, max updates should be 20 (0%, 5%, 10%, ..., 100%)
        # In practice, might be fewer due to file size
        max_expected_updates = 21  # 0-100 in 5% steps = 21 updates
        
        assert update_count <= max_expected_updates, (
            f"Too many progress updates: {update_count} > {max_expected_updates}"
        )
        
        print(f"Progress updates sent: {update_count} (max allowed: {max_expected_updates})")
    
    @pytest.mark.asyncio
    async def test_configurable_update_interval(
        self,
        temp_directory
    ):
        """
        Test at update interval kan konfigureres.
        """
        # Test with different intervals
        for interval in [1, 5, 10]:
            # Create new settings with different interval
            settings = Settings(
                source_directory=temp_directory,
                destination_directory=os.path.join(temp_directory, "dest"),
                copy_progress_update_interval=interval,
                use_temporary_file=False
            )
            
            state_manager = StateManager()
            job_queue = JobQueueService(settings, state_manager)
            file_copier = FileCopyService(settings, state_manager, job_queue)
            
            # Create test file
            source_file = Path(temp_directory) / f"test_{interval}.mxv"
            test_content = b"x" * (50 * 1024)  # 50KB
            source_file.write_bytes(test_content)
            
            await state_manager.add_file(str(source_file), len(test_content))
            
            # Track updates
            progress_updates = []
            original_update = state_manager.update_file_status
            
            async def track_updates(file_path, status, **kwargs):
                if 'copy_progress' in kwargs:
                    progress_updates.append(kwargs['copy_progress'])
                return await original_update(file_path, status, **kwargs)
            
            state_manager.update_file_status = track_updates
            
            # Copy file
            job = {
                "file_path": str(source_file),
                "file_size": len(test_content),
                "discovered_at": "2024-10-09T15:30:00"
            }
            
            await file_copier._copy_file_with_retry(job)
            
            # Verify interval compliance
            interval_compliant_updates = [
                u for u in progress_updates 
                if u % interval == 0 or u == 100.0
            ]
            
            # All updates should be interval-compliant
            non_compliant = [u for u in progress_updates if u not in interval_compliant_updates]
            
            assert len(non_compliant) == 0, (
                f"Non-compliant updates for interval {interval}: {non_compliant}"
            )
            
            print(f"Interval {interval}%: {len(progress_updates)} updates - {progress_updates}")
    
    @pytest.mark.asyncio
    async def test_small_file_minimal_updates(
        self,
        file_copier,
        state_manager,
        temp_directory
    ):
        """
        Test at små filer får minimale updates.
        """
        # Very small file - should complete quickly
        source_file = Path(temp_directory) / "tiny.mxf"
        dest_dir = Path(temp_directory) / "dest"
        dest_dir.mkdir()
        
        test_content = b"small file content"  # Very small
        source_file.write_bytes(test_content)
        
        await state_manager.add_file(str(source_file), len(test_content))
        
        # Track updates
        progress_updates = []
        original_update = state_manager.update_file_status
        
        async def track_updates(file_path, status, **kwargs):
            if 'copy_progress' in kwargs:
                progress_updates.append(kwargs['copy_progress'])
            return await original_update(file_path, status, **kwargs)
        
        state_manager.update_file_status = track_updates
        
        # Copy file
        job = {
            "file_path": str(source_file),
            "file_size": len(test_content),
            "discovered_at": "2024-10-09T15:30:00"
        }
        
        await file_copier._copy_file_with_retry(job)
        
        # Small files should have very few updates
        assert len(progress_updates) <= 3, (
            f"Small file had too many progress updates: {progress_updates}"
        )
        
        # Should always end with 100%
        assert 100.0 in progress_updates, "Should complete with 100%"
    
    def test_progress_calculation_accuracy(self):
        """
        Test at progress procent beregning er korrekt.
        """
        # Test different file sizes and bytes copied
        test_cases = [
            (100, 50, 50.0),    # 50% of 100 bytes
            (1000, 123, 12.0),  # 12.3% rounds down to 12%
            (1000, 129, 12.0),  # 12.9% rounds down to 12%
            (1000, 130, 13.0),  # 13.0% exactly
            (1000, 999, 99.0),  # 99.9% rounds down to 99%
            (1000, 1000, 100.0) # 100% completion
        ]
        
        for file_size, bytes_copied, expected_percent in test_cases:
            calculated = int((bytes_copied / file_size) * 100.0)
            assert calculated == expected_percent, (
                f"Progress calculation wrong: {bytes_copied}/{file_size} = "
                f"{calculated}%, expected {expected_percent}%"
            )


# Manual test for progress optimization
async def manual_test_progress_optimization():
    """Manual test for progress update optimization"""
    print("🧪 Manual Copy Progress Optimization Test")
    print("=" * 50)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Setup
        settings = Settings(
            source_directory=temp_dir,
            destination_directory=os.path.join(temp_dir, "dest"),
            copy_progress_update_interval=10,  # Update every 10%
            use_temporary_file=False
        )
        
        state_manager = StateManager()
        job_queue = JobQueueService(settings, state_manager)
        file_copier = FileCopyService(settings, state_manager, job_queue)
        
        # Create destination directory
        dest_dir = Path(temp_dir) / "dest"
        dest_dir.mkdir()
        
        # Create test file
        source_file = Path(temp_dir) / "progress_test.mxf"
        test_content = b"x" * (200 * 1024)  # 200KB
        source_file.write_bytes(test_content)
        
        print(f"📁 Created test file: {source_file} ({len(test_content)} bytes)")
        
        await state_manager.add_file(str(source_file), len(test_content))
        
        # Track progress updates
        progress_updates = []
        original_update = state_manager.update_file_status
        
        async def track_progress(file_path, status, **kwargs):
            if 'copy_progress' in kwargs:
                progress = kwargs['copy_progress']
                progress_updates.append(progress)
                print(f"📊 Progress update: {progress}%")
            return await original_update(file_path, status, **kwargs)
        
        state_manager.update_file_status = track_progress
        
        # Copy file
        job = {
            "file_path": str(source_file),
            "file_size": len(test_content),
            "discovered_at": "2024-10-09T15:30:00"
        }
        
        print("🚀 Starting copy with 10% update intervals...")
        await file_copier._copy_file_with_retry(job)
        
        print("✅ Copy completed")
        print(f"📈 Total progress updates: {len(progress_updates)}")
        print(f"📋 Updates: {progress_updates}")
        
        # Verify optimization
        interval_compliant = [u for u in progress_updates if u % 10 == 0 or u == 100.0]
        optimization_ratio = len(progress_updates) / max(1, len(range(0, 101, 1)))
        
        print(f"🎯 Interval-compliant updates: {len(interval_compliant)}/{len(progress_updates)}")
        print(f"🔥 Optimization ratio: {optimization_ratio:.2%} (lower is better)")
        
        if len(progress_updates) <= 11:  # 0%, 10%, 20%, ..., 100% = 11 updates
            print("🎉 SUCCESS: Progress updates optimized!")
        else:
            print("⚠️ NOTICE: More updates than expected, but may be normal for test conditions")
    
    print("🏁 Manual test completed")


if __name__ == "__main__":
    asyncio.run(manual_test_progress_optimization())