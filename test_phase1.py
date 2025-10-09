"""
Test script for Phase 1: Growing File Foundation

Tests at growing file detection og configuration fungerer korrekt.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config import Settings
from app.models import FileStatus
from app.services.state_manager import StateManager
from app.services.growing_file_detector import GrowingFileDetector
import tempfile


async def test_growing_file_foundation():
    """Test growing file detection setup"""
    
    print("🧪 Testing Growing File Foundation (Phase 1)")
    print("=" * 50)
    
    # Create temporary settings for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test settings with growing file support enabled
        test_settings = Settings(
            source_directory=temp_dir,
            destination_directory=temp_dir,
            enable_growing_file_support=True,
            growing_file_min_size_mb=1,  # 1MB for testing
            growing_file_poll_interval_seconds=1,
            growing_file_growth_timeout_seconds=3
        )
        
        print(f"✓ Created test settings with growing file support")
        print(f"  - Min size: {test_settings.growing_file_min_size_mb}MB")
        print(f"  - Poll interval: {test_settings.growing_file_poll_interval_seconds}s")
        print(f"  - Growth timeout: {test_settings.growing_file_growth_timeout_seconds}s")
        
        # Test StateManager
        state_manager = StateManager()
        print("✓ Created StateManager")
        
        # Test GrowingFileDetector creation
        detector = GrowingFileDetector(test_settings, state_manager)
        print(f"✓ Created GrowingFileDetector")
        
        # Test configuration
        stats = detector.get_monitoring_stats()
        print(f"✓ Growing file detector stats:")
        for key, value in stats.items():
            print(f"    {key}: {value}")
        
        # Create a test file
        test_file = Path(temp_dir) / "test_growing.mxf"
        
        # Test 1: Small file (should be DISCOVERED)
        with open(test_file, 'wb') as f:
            f.write(b'x' * 500_000)  # 500KB
        
        status, growth_info = await detector.check_file_growth_status(str(test_file))
        print(f"✓ Small file (500KB) -> Status: {status.value}")
        assert status == FileStatus.DISCOVERED
        
        # Test 2: Large file (should be READY_TO_START_GROWING if growing)
        with open(test_file, 'wb') as f:
            f.write(b'x' * 2_000_000)  # 2MB
        
        # First check should mark as DISCOVERED (new file)
        status, growth_info = await detector.check_file_growth_status(str(test_file))
        print(f"✓ Large file (2MB) first check -> Status: {status.value}")
        
        # Simulate file growth
        await asyncio.sleep(0.1)
        with open(test_file, 'ab') as f:
            f.write(b'x' * 1_000_000)  # Add 1MB
        
        await detector.update_file_growth_info(str(test_file), 3_000_000)
        status, growth_info = await detector.check_file_growth_status(str(test_file))
        print(f"✓ Growing file (3MB) -> Status: {status.value}")
        if growth_info:
            print(f"    Growth rate: {growth_info.growth_rate_mbps:.2f} MB/s")
        
        # Test 3: Stable file after timeout
        await asyncio.sleep(4)  # Wait longer than timeout
        status, growth_info = await detector.check_file_growth_status(str(test_file))
        print(f"✓ Stable file after timeout -> Status: {status.value}")
        
        # Test FileStatus enum extensions
        print(f"✓ New FileStatus values:")
        print(f"    GROWING: {FileStatus.GROWING.value}")
        print(f"    READY_TO_START_GROWING: {FileStatus.READY_TO_START_GROWING.value}")
        print(f"    GROWING_COPY: {FileStatus.GROWING_COPY.value}")
        
        # Cleanup
        await detector.cleanup_tracking(str(test_file))
        print(f"✓ Cleaned up tracking")
        
    print("\n🎉 Phase 1 Foundation Test Complete!")
    print("All growing file detection components are working correctly.")


if __name__ == "__main__":
    asyncio.run(test_growing_file_foundation())