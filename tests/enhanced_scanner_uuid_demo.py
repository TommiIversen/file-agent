"""
Enhanced Scanner Service with UUID-based Event Sourcing.

This demonstrates how the scanner can be enhanced to use UUID-based operations
for better event sourcing and precise file tracking throughout the discovery
and stability checking phases.
"""

import asyncio
import logging
from datetime import datetime
from typing import Set, Dict

from app.models import FileStatus, TrackedFile
from app.services.state_manager import StateManager
from app.services.scanner.domain_objects import FileMetadata


class UUIDEnhancedFileScanOrchestrator:
    """
    Enhanced scanner that leverages UUID-based StateManager operations 
    for precise event sourcing and robust file lifecycle management.

    Key Enhancements:
    1. UUID-based updates for precise file reference
    2. Event sourcing approach - files can disappear/reappear with full history
    3. Robust handling of file changes during scan cycles
    4. Better tracking of file lifecycle events
    """

    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        
        # Track files by UUID during scan cycle for precise updates
        self._current_scan_files: Dict[str, str] = {}  # file_path -> uuid
        self._running = False

    async def discover_and_process_files(self, discovered_paths: Set[str]) -> None:
        """
        Enhanced file discovery with UUID-based tracking.
        
        Uses event sourcing approach where files can disappear/reappear
        with complete history preservation.
        """
        logging.info(f"🔍 Enhanced UUID-based file discovery started ({len(discovered_paths)} paths)")
        
        # Step 1: Process all discovered files
        for file_path in discovered_paths:
            await self._process_discovered_file(file_path)
        
        # Step 2: Handle files that disappeared (event sourcing!)
        await self._handle_disappeared_files(discovered_paths)
        
        logging.info("✅ Enhanced file discovery completed")

    async def _process_discovered_file(self, file_path: str) -> None:
        """
        Process a discovered file using UUID-based operations.
        
        Event sourcing benefit: If file disappeared and returned,
        it gets new UUID while preserving previous history.
        """
        try:
            # Get file metadata
            metadata = await FileMetadata.from_path(file_path)
            if metadata is None or metadata.is_empty():
                return

            # Check current state (UUID-aware)
            existing_file = await self.state_manager.get_file(file_path)
            
            if existing_file is None:
                # File is new or returned after being REMOVED
                tracked_file = await self.state_manager.add_file(
                    file_path=file_path,
                    file_size=metadata.size,
                    last_write_time=metadata.last_write_time,
                )
                
                # Track UUID for this scan cycle
                self._current_scan_files[file_path] = tracked_file.id
                
                logging.info(f"📁 NEW FILE: {metadata.path.name} (UUID: {tracked_file.id[:8]}...)")
                
            else:
                # File already exists - track its UUID for updates
                self._current_scan_files[file_path] = existing_file.id
                
                # Check for changes using UUID-based updates
                await self._check_file_changes_by_uuid(existing_file, metadata)

        except Exception as e:
            logging.error(f"❌ Error processing {file_path}: {e}")

    async def _check_file_changes_by_uuid(self, tracked_file: TrackedFile, metadata: FileMetadata) -> None:
        """
        Check file changes and update using precise UUID-based operations.
        
        Event sourcing benefit: All updates are precisely targeted to specific
        file UUID, avoiding any ambiguity with same-name files.
        """
        file_uuid = tracked_file.id
        
        # Check for size changes
        if metadata.size != tracked_file.file_size:
            logging.info(f"📊 SIZE CHANGE: {tracked_file.file_path} "
                        f"({tracked_file.file_size} → {metadata.size} bytes) "
                        f"[UUID: {file_uuid[:8]}...]")
            
            # Use UUID-based update for precision
            await self.state_manager.update_file_status_by_id(
                file_id=file_uuid,
                status=FileStatus.DISCOVERED,  # Reset to discovered due to change
                file_size=metadata.size,
                last_write_time=metadata.last_write_time
            )
        
        # Check stability and update status if needed
        if await self._is_file_stable(tracked_file, metadata):
            if tracked_file.status != FileStatus.READY:
                logging.info(f"✅ FILE STABLE: {tracked_file.file_path} "
                           f"[UUID: {file_uuid[:8]}...]")
                
                # Use UUID-based update for precision
                await self.state_manager.update_file_status_by_id(
                    file_id=file_uuid,
                    status=FileStatus.READY
                )

    async def _handle_disappeared_files(self, discovered_paths: Set[str]) -> None:
        """
        Handle files that disappeared since last scan - EVENT SOURCING MAGIC!
        
        Instead of just deleting, we mark as REMOVED to preserve history.
        If file returns later, it gets new UUID while old history is preserved.
        """
        # Get all current active files (excludes REMOVED)
        all_current_files = await self.state_manager.get_all_files()
        
        # Find files that disappeared
        current_paths = {f.file_path for f in all_current_files}
        disappeared_paths = current_paths - discovered_paths
        
        if not disappeared_paths:
            return

        logging.info(f"🗑️  DISAPPEARED: {len(disappeared_paths)} files missing from scan")
        
        # Mark disappeared files as REMOVED (preserves history!)
        removed_count = await self.state_manager.cleanup_missing_files(discovered_paths)
        
        if removed_count > 0:
            logging.info(f"📚 EVENT SOURCING: {removed_count} files marked as REMOVED "
                        f"(history preserved for future reference)")
            
            # Log each disappeared file for audit trail
            for file_path in disappeared_paths:
                # Get history to show what happened
                history = await self.state_manager.get_file_history(file_path)
                if history:
                    last_entry = history[0]  # Most recent
                    logging.info(f"📊 REMOVED: {file_path} "
                               f"(was {last_entry.status}, UUID: {last_entry.id[:8]}...)")

    async def _is_file_stable(self, tracked_file: TrackedFile, metadata: FileMetadata) -> bool:
        """
        Check if file is stable (simplified for demo).
        
        In real implementation, this would use FileStabilityTracker.
        """
        # Simple heuristic: if size hasn't changed and file is older than 2 seconds
        if tracked_file.file_size == metadata.size:
            if metadata.last_write_time and tracked_file.discovered_at:
                age_seconds = (datetime.now() - tracked_file.discovered_at).total_seconds()
                return age_seconds >= 2
        return False

    async def get_scan_statistics(self) -> Dict:
        """
        Get enhanced statistics with UUID-based insights.
        
        Event sourcing benefit: We can provide rich analytics about
        file patterns, return rates, etc.
        """
        stats = await self.state_manager.get_statistics()
        
        # Add UUID-specific insights
        stats.update({
            "current_scan_files": len(self._current_scan_files),
            "uuid_tracking_active": True,
            "event_sourcing_enabled": True,
        })
        
        return stats

    async def demonstrate_uuid_benefits(self, file_path: str) -> None:
        """
        Demonstrate the benefits of UUID-based operations.
        
        Shows how we can track file through multiple cycles with full history.
        """
        logging.info(f"🎭 DEMO: UUID benefits for {file_path}")
        
        # Get current file (if exists)
        current_file = await self.state_manager.get_file(file_path)
        if current_file:
            logging.info(f"📋 CURRENT: UUID {current_file.id[:8]}..., Status: {current_file.status}")
        
        # Get full history
        history = await self.state_manager.get_file_history(file_path)
        if history:
            logging.info(f"📚 HISTORY: {len(history)} entries for this file path")
            for i, entry in enumerate(history[:3]):  # Show last 3
                logging.info(f"   {i+1}. UUID {entry.id[:8]}..., Status: {entry.status}, "
                           f"Size: {entry.file_size}, Discovered: {entry.discovered_at}")
        
        # Demonstrate UUID-based lookup
        if current_file:
            by_uuid = await self.state_manager.get_file_by_id(current_file.id)
            if by_uuid:
                logging.info(f"🎯 UUID LOOKUP: Successfully found file by UUID {current_file.id[:8]}...")


# Usage Example Function
async def demonstrate_enhanced_scanner():
    """
    Demonstrate enhanced scanner with UUID-based event sourcing.
    """
    from app.dependencies import get_state_manager
    
    state_manager = get_state_manager()
    scanner = UUIDEnhancedFileScanOrchestrator(state_manager)
    
    # Simulate file discovery cycles
    logging.info("🚀 Starting UUID-enhanced scanner demonstration")
    
    # Cycle 1: Initial files
    discovered_files_1 = {
        "/test/video_001.mxf",
        "/test/video_002.mxf", 
        "/test/render_temp.mxf"
    }
    await scanner.discover_and_process_files(discovered_files_1)
    
    # Cycle 2: One file disappeared, one new appeared
    discovered_files_2 = {
        "/test/video_001.mxf",
        "/test/video_002.mxf",
        "/test/final_export.mxf"  # New file
        # render_temp.mxf disappeared!
    }
    await scanner.discover_and_process_files(discovered_files_2)
    
    # Cycle 3: render_temp.mxf returns (gets new UUID!)
    discovered_files_3 = {
        "/test/video_001.mxf",
        "/test/video_002.mxf", 
        "/test/final_export.mxf",
        "/test/render_temp.mxf"  # Returned!
    }
    await scanner.discover_and_process_files(discovered_files_3)
    
    # Show the magic of event sourcing
    await scanner.demonstrate_uuid_benefits("/test/render_temp.mxf")
    
    # Show statistics
    stats = await scanner.get_scan_statistics()
    logging.info(f"📊 FINAL STATS: {stats}")


if __name__ == "__main__":
    # Run the demonstration
    asyncio.run(demonstrate_enhanced_scanner())