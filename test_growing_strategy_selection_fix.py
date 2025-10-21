#!/usr/bin/env python3
"""
Test for growing file strategy selection bug fix.

Scenario:
1. Growing file starts offline -> WAITING_FOR_NETWORK (is_growing_file=False)
2. Network comes online -> READY -> IN_QUEUE
3. Strategy selection should detect real-time growth and select GrowingFileCopyStrategy
"""

import asyncio
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.consumer.job_file_preparation_service import JobFilePreparationService
from app.services.consumer.job_models import QueueJob
from app.services.copy_strategies import CopyStrategyFactory
from app.services.state_manager import StateManager
from app.utils.output_folder_template import OutputFolderTemplateEngine


@pytest.mark.asyncio
async def test_growing_strategy_selection_after_network_recovery():
    """Test that strategy selection works correctly after network recovery."""
    
    # Create temporary test environment
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "growing_test.mxf"
        
        # Create initial small file
        initial_content = b"x" * 1000
        source_path.write_bytes(initial_content)
        
        # Create minimal settings
        settings = Settings()
        settings.source_directory = temp_dir
        settings.destination_directory = temp_dir + "_dest"
        settings.growing_file_min_size_mb = 0.001  # Very small for testing
        
        # Create components
        state_manager = StateManager(settings)
        copy_strategy_factory = CopyStrategyFactory(
            settings=settings,
            state_manager=state_manager,
            enable_resume=False
        )
        template_engine = OutputFolderTemplateEngine(settings)
        
        preparation_service = JobFilePreparationService(
            settings=settings,
            state_manager=state_manager,
            copy_strategy_factory=copy_strategy_factory,
            template_engine=template_engine
        )
        
        # 1. Simulate file discovered offline (scanner would set is_growing_file=False)
        tracked_file = await state_manager.add_file(str(source_path), len(initial_content))
        
        # Simulate it was discovered while offline (network down status)
        await state_manager.update_file_status_by_id(
            tracked_file.id,
            FileStatus.WAITING_FOR_NETWORK,
            is_growing_file=False  # This simulates the bug - offline detection didn't mark as growing
        )
        print(f"📍 INITIAL STATE: {tracked_file.file_path}")
        print(f"   Status: {tracked_file.status}")
        print(f"   Size: {tracked_file.file_size}")
        print(f"   is_growing_file: {tracked_file.is_growing_file}")
        
        # 2. Simulate network recovery - file goes to READY
        await state_manager.update_file_status_by_id(
            tracked_file.id,
            FileStatus.READY
        )
        
        ready_file = await state_manager.get_file_by_id(tracked_file.id)
        print(f"\n🌐 NETWORK RECOVERY: {ready_file.file_path}")
        print(f"   Status: {ready_file.status}")
        print(f"   is_growing_file: {ready_file.is_growing_file}")
        
        # 3. Simulate file growth during/after network recovery
        time.sleep(0.1)  # Small delay
        grown_content = initial_content + b"y" * 2000  # File grows
        source_path.write_bytes(grown_content)
        
        print(f"\n🌱 FILE GROWS: {len(grown_content)} bytes (was {len(initial_content)})")
        
        # 4. Create job and test strategy selection
        job = QueueJob(
            tracked_file=ready_file,
            added_to_queue_at=datetime.now(),
            retry_count=0
        )
        
        # 5. Test preparation service (this should detect growth and select correct strategy)
        prepared_file = await preparation_service.prepare_file_for_copy(job)
        
        print(f"\n🎯 STRATEGY SELECTION RESULT:")
        print(f"   Strategy: {prepared_file.strategy_name}")
        print(f"   Updated is_growing_file: {prepared_file.tracked_file.is_growing_file}")
        print(f"   Updated file_size: {prepared_file.tracked_file.file_size}")
        
        # Verify the fix worked
        assert prepared_file.strategy_name == "GrowingFileCopyStrategy", \
            f"Expected GrowingFileCopyStrategy, got {prepared_file.strategy_name}"
        
        assert prepared_file.tracked_file.is_growing_file == True, \
            "File should be marked as growing after real-time detection"
            
        assert prepared_file.tracked_file.file_size == len(grown_content), \
            f"File size should be updated to {len(grown_content)}, got {prepared_file.tracked_file.file_size}"
        
        print(f"\n✅ SUCCESS: Strategy selection correctly detected real-time growth!")
        print(f"   File that was offline with is_growing_file=False")
        print(f"   Now correctly selects GrowingFileCopyStrategy after growth detection")


if __name__ == "__main__":
    asyncio.run(test_growing_strategy_selection_after_network_recovery())