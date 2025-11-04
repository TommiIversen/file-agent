"""
Test for IngestMonitorService

Simple test to verify the service functionality without requiring
actual network connectivity to Just In Engine.
"""
import asyncio

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.domains.ingest_monitor.service import IngestMonitorService
from app.domains.ingest_monitor.models import ChannelState


async def test_ingest_monitor_service():
    """Test basic IngestMonitorService functionality."""
    
    # Create test settings
    settings = Settings()
    settings.justin_api_base_url = "http://test:8080"
    settings.justin_fast_poll_interval_seconds = 0.1  # Fast for testing
    settings.justin_slow_poll_interval_seconds = 0.2
    settings.justin_api_timeout_seconds = 1.0
    
    # Create event bus
    event_bus = DomainEventBus()
    
    # Create service
    service = IngestMonitorService(settings, event_bus)
    
    # Test cache functionality
    print("Testing cache functionality...")
    initial_cache = service.get_status_cache()
    assert initial_cache == {}, f"Expected empty cache, got {initial_cache}"
    print("✅ Initial cache is empty")
    
    # Manually add a test channel to cache
    test_channel = ChannelState(
        name="KAM_1",
        is_recording=True,
        has_signal=True,
        has_errors=False
    )
    service._status_cache["KAM_1"] = test_channel
    
    # Test cache retrieval
    cache_snapshot = service.get_status_cache()
    assert "KAM_1" in cache_snapshot, "KAM_1 not found in cache"
    assert cache_snapshot["KAM_1"]["is_recording"] is True
    assert cache_snapshot["KAM_1"]["has_signal"] is True
    print("✅ Cache storage and retrieval works")
    
    # Test change detection logic
    print("Testing change detection...")
    
    # Create a new state with different recording status
    new_state = ChannelState(
        name="KAM_1",
        is_recording=False,  # Changed from True to False
        has_signal=True,
        has_errors=False
    )
    
    # Test the change detection method
    events = service._update_cache_and_detect_changes([new_state])
    
    # Should detect one recording stopped event
    assert len(events) == 1, f"Expected 1 event, got {len(events)}"
    from app.domains.ingest_monitor.events import ChannelRecordingStoppedEvent
    assert isinstance(events[0], ChannelRecordingStoppedEvent)
    assert events[0].channel_name == "KAM_1"
    print("✅ Change detection works correctly")
    
    # Test cleanup
    print("Testing service lifecycle...")
    assert service._running is False, "Service should not be running initially"
    
    # Don't actually start monitoring (would require network)
    # Just test that the service can be created and configured
    await service.stop_monitoring()  # Should handle being called when not running
    print("✅ Service lifecycle methods work")
    
    print("🎉 All IngestMonitorService tests passed!")


if __name__ == "__main__":
    asyncio.run(test_ingest_monitor_service())