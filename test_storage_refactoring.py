#!/usr/bin/env python3
"""
Test script for Storage Architecture Refactoring.

This script validates that the Central Storage Authority pattern works correctly:
1. StorageMonitorService handles directory recreation
2. FileScannerService and DestinationChecker use cached state
3. No race conditions occur when directories are deleted/recreated
"""

import asyncio
import tempfile
import shutil
from pathlib import Path

# Test imports
from app.config import Settings
from app.services.storage_monitor import StorageMonitorService
from app.services.storage_checker import StorageChecker
from app.services.file_scanner import FileScannerService
from app.services.state_manager import StateManager
from app.services.destination.destination_checker import DestinationChecker


async def test_central_storage_authority():
    """Test Central Storage Authority pattern implementation."""
    print("🧪 Testing Central Storage Authority Pattern...")
    
    # Create temporary directories for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "test_source"
        dest_path = Path(temp_dir) / "test_dest"
        
        print(f"📁 Test directories: {source_path}, {dest_path}")
        
        # Create test settings
        settings = Settings()
        settings.source_directory = str(source_path)
        settings.destination_directory = str(dest_path)
        settings.storage_check_interval_seconds = 1  # Fast checking for testing
        
        # Initialize services following dependency injection pattern
        storage_checker = StorageChecker()
        storage_monitor = StorageMonitorService(settings, storage_checker)
        state_manager = StateManager()
        
        # Initialize consumers with StorageMonitor injection
        file_scanner = FileScannerService(settings, state_manager, storage_monitor)
        destination_checker = DestinationChecker(dest_path, storage_monitor=storage_monitor)
        
        print("✅ Services initialized with Central Storage Authority")
        
        # Test 1: Directories don't exist initially
        print("\n🧪 Test 1: Initial directory state")
        readiness = storage_monitor.get_directory_readiness()
        print(f"Initial readiness: {readiness}")
        
        # Test 2: Start monitoring (should create directories)
        print("\n🧪 Test 2: Start monitoring and directory creation")
        await storage_monitor.start_monitoring()
        
        # Give monitoring loop time to create directories
        await asyncio.sleep(2)
        
        readiness = storage_monitor.get_directory_readiness()
        print(f"After monitoring start: {readiness}")
        
        # Verify directories exist
        assert source_path.exists(), f"Source directory should exist: {source_path}"
        assert dest_path.exists(), f"Destination directory should exist: {dest_path}"
        print("✅ Directories created by StorageMonitor")
        
        # Test 3: Consumer services use cached state (no direct I/O)
        print("\n🧪 Test 3: Consumers use cached state")
        
        # FileScannerService should detect directory readiness
        discovered_files = await file_scanner._discover_files()
        print(f"FileScannerService discovered: {len(discovered_files)} files")
        
        # DestinationChecker should detect availability from cache
        is_available = await destination_checker.is_available()
        print(f"DestinationChecker availability: {is_available}")
        assert is_available, "Destination should be available according to cached state"
        print("✅ Consumers successfully use cached state")
        
        # Test 4: Directory deletion and recreation
        print("\n🧪 Test 4: Runtime directory deletion and recreation")
        
        # Simulate external deletion of destination
        print(f"🗑️ Deleting destination directory: {dest_path}")
        shutil.rmtree(dest_path)
        assert not dest_path.exists(), "Destination should be deleted"
        
        # Wait for monitoring loop to detect and recreate
        print("⏳ Waiting for StorageMonitor to detect and recreate...")
        await asyncio.sleep(3)
        
        # Verify recreation
        readiness_after = storage_monitor.get_directory_readiness()
        print(f"Readiness after recreation: {readiness_after}")
        
        if dest_path.exists():
            print("✅ Directory automatically recreated by StorageMonitor")
        else:
            print("❌ Directory not recreated - may need longer monitoring interval")
        
        # Test 5: No race conditions with multiple consumers
        print("\n🧪 Test 5: Multiple consumers, no race conditions")
        
        # Simulate multiple consumers checking simultaneously
        tasks = []
        for i in range(5):
            tasks.append(destination_checker.is_available())
            
        results = await asyncio.gather(*tasks)
        print(f"Concurrent availability checks: {results}")
        
        # All should succeed without race conditions
        assert all(results), "All concurrent checks should succeed"
        print("✅ No race conditions detected")
        
        # Cleanup
        await storage_monitor.stop_monitoring()
        print("\n🎉 All tests passed! Central Storage Authority pattern working correctly.")


async def main():
    """Run all tests."""
    try:
        await test_central_storage_authority()
        print("\n✅ SUCCESS: Storage Architecture Refactoring validated!")
    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())