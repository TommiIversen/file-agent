"""
Test script for Phase 2: Copy Strategy Framework

Tests at copy strategy pattern implementering fungerer korrekt.
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
from app.services.copy_strategies import FileCopyStrategyFactory, NormalFileCopyStrategy, GrowingFileCopyStrategy
import tempfile
from datetime import datetime


async def test_copy_strategy_framework():
    """Test copy strategy framework"""
    
    print("🧪 Testing Copy Strategy Framework (Phase 2)")
    print("=" * 50)
    
    # Create temporary settings for testing
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
            growing_file_safety_margin_mb=1,
            growing_file_chunk_size_kb=64,
            copy_progress_update_interval=25  # Every 25%
        )
        
        print("✓ Created test settings with copy strategy support")
        
        # Test StateManager
        state_manager = StateManager()
        print("✓ Created StateManager")
        
        # Test strategy factory
        factory = FileCopyStrategyFactory(test_settings, state_manager)
        print("✓ Created FileCopyStrategyFactory")
        
        # Test available strategies
        strategies = factory.get_available_strategies()
        print(f"✓ Available strategies: {list(strategies.keys())}")
        
        # Test 1: Normal file should use normal strategy
        normal_file = TrackedFile(
            file_path=str(source_dir / "normal.mxf"),
            status=FileStatus.READY,
            file_size=1000000,
            is_growing_file=False
        )
        
        strategy = factory.get_strategy(normal_file)
        print(f"✓ Normal file -> {strategy.__class__.__name__}")
        assert isinstance(strategy, NormalFileCopyStrategy)
        assert strategy.supports_file(normal_file)
        
        # Test 2: Growing file should use growing strategy
        growing_file = TrackedFile(
            file_path=str(source_dir / "growing.mxf"),
            status=FileStatus.READY_TO_START_GROWING,
            file_size=5000000,
            is_growing_file=True,
            growth_rate_mbps=2.5
        )
        
        strategy = factory.get_strategy(growing_file)
        print(f"✓ Growing file -> {strategy.__class__.__name__}")
        assert isinstance(strategy, GrowingFileCopyStrategy)
        assert strategy.supports_file(growing_file)
        
        # Test 3: Normal strategy with growing file support disabled
        test_settings_no_growing = Settings(
            source_directory=str(source_dir),
            destination_directory=str(dest_dir),
            enable_growing_file_support=False
        )
        
        factory_no_growing = FileCopyStrategyFactory(test_settings_no_growing, state_manager)
        strategy = factory_no_growing.get_strategy(growing_file)
        print(f"✓ Growing file (support disabled) -> {strategy.__class__.__name__}")
        assert isinstance(strategy, NormalFileCopyStrategy)
        
        # Test 4: Create test files and verify strategy selection
        test_file_path = source_dir / "test.mxf"
        with open(test_file_path, 'wb') as f:
            f.write(b'x' * 1024 * 1024)  # 1MB
        
        # Add file to state manager
        await state_manager.add_file(
            str(test_file_path),
            1024 * 1024,
            datetime.now()
        )
        
        # Test normal strategy selection
        tracked = await state_manager.get_file(str(test_file_path))
        await state_manager.update_file_status(
            str(test_file_path),
            FileStatus.READY,
            is_growing_file=False
        )
        
        tracked = await state_manager.get_file(str(test_file_path))
        strategy = factory.get_strategy(tracked)
        print(f"✓ Tracked normal file -> {strategy.__class__.__name__}")
        assert isinstance(strategy, NormalFileCopyStrategy)
        
        # Test growing strategy selection
        await state_manager.update_file_status(
            str(test_file_path),
            FileStatus.READY_TO_START_GROWING,
            is_growing_file=True,
            growth_rate_mbps=1.5
        )
        
        tracked = await state_manager.get_file(str(test_file_path))
        strategy = factory.get_strategy(tracked)
        print(f"✓ Tracked growing file -> {strategy.__class__.__name__}")
        assert isinstance(strategy, GrowingFileCopyStrategy)
        
        print(f"✓ Strategy selection logic verified")
        
    print("\n🎉 Phase 2 Copy Strategy Framework Test Complete!")
    print("All copy strategy components are working correctly.")


if __name__ == "__main__":
    asyncio.run(test_copy_strategy_framework())