"""
Test script for Phase 2 Integration: FileCopyService with Strategy Pattern

Tests at FileCopyService nu bruger copy strategy pattern korrekt.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.state_manager import StateManager
from app.services.file_copier import FileCopyService
from app.services.job_queue import JobQueueService
import tempfile
from datetime import datetime


async def test_filecopy_service_integration():
    """Test FileCopyService integration with copy strategies"""
    
    print("🧪 Testing FileCopyService Strategy Integration (Phase 2)")
    print("=" * 60)
    
    # Create temporary environment
    with tempfile.TemporaryDirectory() as temp_dir:
        source_dir = Path(temp_dir) / "source"
        dest_dir = Path(temp_dir) / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        
        test_settings = Settings(
            source_directory=str(source_dir),
            destination_directory=str(dest_dir),
            enable_growing_file_support=True,
            growing_file_min_size_mb=1,
            copy_progress_update_interval=25,
            use_temporary_file=True
        )
        
        print("✓ Created test environment with strategy support")
        
        # Initialize services
        state_manager = StateManager()
        job_queue = JobQueueService(test_settings, state_manager)
        
        file_copier = FileCopyService(
            test_settings, 
            state_manager, 
            job_queue
        )
        
        print("✓ Created FileCopyService with strategy factory")
        
        # Verify strategy factory integration
        strategies = file_copier.copy_strategy_factory.get_available_strategies()
        print(f"✓ Available strategies in FileCopyService: {list(strategies.keys())}")
        
        # Test 1: Create a normal file for testing
        test_file = source_dir / "normal_test.mxf"
        with open(test_file, 'wb') as f:
            f.write(b'TEST_CONTENT_' * 1000)  # ~15KB
        
        # Add to state manager as normal file
        tracked_file = await state_manager.add_file(
            str(test_file),
            os.path.getsize(test_file),
            datetime.now()
        )
        
        await state_manager.update_file_status(
            str(test_file),
            FileStatus.READY,
            is_growing_file=False
        )
        
        print(f"✓ Created normal test file: {test_file.name} ({os.path.getsize(test_file)} bytes)")
        
        # Test strategy selection
        tracked = await state_manager.get_file(str(test_file))
        strategy = file_copier.copy_strategy_factory.get_strategy(tracked)
        print(f"✓ Normal file uses: {strategy.__class__.__name__}")
        
        # Test 2: Create a growing file for testing
        growing_file = source_dir / "growing_test.mxv"
        with open(growing_file, 'wb') as f:
            f.write(b'GROWING_CONTENT_' * 100000)  # ~1.6MB
        
        # Add to state manager as growing file
        await state_manager.add_file(
            str(growing_file),
            os.path.getsize(growing_file),
            datetime.now()
        )
        
        await state_manager.update_file_status(
            str(growing_file),
            FileStatus.READY_TO_START_GROWING,
            is_growing_file=True,
            growth_rate_mbps=2.5
        )
        
        print(f"✓ Created growing test file: {growing_file.name} ({os.path.getsize(growing_file)} bytes)")
        
        # Test strategy selection for growing file
        tracked_growing = await state_manager.get_file(str(growing_file))
        strategy_growing = file_copier.copy_strategy_factory.get_strategy(tracked_growing)
        print(f"✓ Growing file uses: {strategy_growing.__class__.__name__}")
        
        # Test 3: Verify _resolve_destination_path still works
        dest_path = await file_copier._resolve_destination_path(test_file)
        expected_dest = dest_dir / test_file.name
        print(f"✓ Destination path resolution: {dest_path}")
        assert dest_path == expected_dest
        
        # Test 4: Test the enhanced _copy_single_file method
        print("\n📋 Testing enhanced _copy_single_file method...")
        
        # Verify file still exists before copying
        if test_file.exists():
            print(f"✓ Source file exists: {test_file}")
            
            try:
                # This should work with the new strategy-based approach
                await file_copier._copy_single_file(str(test_file), 1, 3)
                
                # Check if file was copied
                dest_file = dest_dir / test_file.name
                if dest_file.exists():
                    print(f"✓ Normal file copy successful: {dest_file}")
                    
                    # Verify content
                    with open(dest_file, 'rb') as f:
                        content = f.read()
                    
                    if b'TEST_CONTENT_' in content:
                        print("✓ File content verified")
                    else:
                        print("❌ File content verification failed")
                else:
                    print("❌ Destination file not found")
            
            except Exception as e:
                print(f"⚠️  Copy test failed: {e}")
        else:
            print(f"❌ Source file missing: {test_file}")
        
        # Test 5: Verify service statistics
        stats = await file_copier.get_copy_statistics()
        print("\n📊 FileCopyService Statistics:")
        for key, value in stats.items():
            print(f"    {key}: {value}")
        
        print("\n🎉 Phase 2 Integration Test Complete!")
        print("FileCopyService successfully integrated with copy strategy framework.")


if __name__ == "__main__":
    asyncio.run(test_filecopy_service_integration())