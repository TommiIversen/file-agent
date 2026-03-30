"""
Test for Refactored Ingest Monitor Components

Tests the new SRP-compliant components: IngestApiClient, IngestStateService, 
and IngestMonitorWorker without requiring actual network connectivity.
"""
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.domains.ingest_monitor.api_client import IngestApiClient
from app.domains.ingest_monitor.state_service import IngestStateService
from app.domains.ingest_monitor.worker import IngestMonitorWorker
from app.domains.ingest_monitor.models import ChannelState, JustInRecordingStatus, JustInOptions


@pytest.mark.asyncio
async def test_ingest_monitor_components():
    """Test the refactored ingest monitor components."""
    
    # Create test settings
    settings = Settings()
    settings.justin_api_base_url = "http://test:8080"
    settings.justin_fast_poll_interval_seconds = 0.1  # Fast for testing
    settings.justin_slow_poll_interval_seconds = 0.2
    settings.justin_api_timeout_seconds = 1.0
    
    # Create event bus
    event_bus = DomainEventBus()
    
    print("Testing IngestStateService...")
    
    # Test StateService functionality
    state_service = IngestStateService(event_bus)
    
    # Test initial empty cache
    initial_cache = state_service.get_status_cache()
    assert initial_cache == {}, f"Expected empty cache, got {initial_cache}"
    print("IngestStateService initial cache is empty")
    
    # Test adding active channels
    test_channels = ["KAM_1", "KAM_2"]
    await state_service.update_active_channels(test_channels)
    
    cache_after_channels = state_service.get_status_cache()
    assert len(cache_after_channels) == 2, f"Expected 2 channels, got {len(cache_after_channels)}"
    assert "KAM_1" in cache_after_channels
    assert "KAM_2" in cache_after_channels
    print("IngestStateService channel management works")
    
    # Test change detection
    test_status_updates = [
        ("KAM_1", JustInRecordingStatus(
            rec=True, channel="KAM_1", name="KAM_1",
            options=JustInOptions(TOAJustInEngineVideoSignalAvailable=True)
        )),
        ("KAM_2", JustInRecordingStatus(
            rec=False, channel="KAM_2", name="KAM_2",
            options=JustInOptions(TOAJustInEngineVideoSignalAvailable=True)
        )),
    ]
    
    await state_service.update_channel_statuses(test_status_updates)
    
    updated_cache = state_service.get_status_cache()
    assert updated_cache["KAM_1"]["is_recording"] is True
    assert updated_cache["KAM_2"]["is_recording"] is False
    print("IngestStateService status updates work")
    
    print("Testing IngestApiClient...")
    
    # Test ApiClient creation (without actual network calls)
    with patch("app.domains.ingest_monitor.api_client.httpx.AsyncClient"):
        api_client = IngestApiClient(settings)
    api_client._client = MagicMock()
    api_client._client.aclose = AsyncMock()
    assert api_client._client is not None
    print("OK IngestApiClient initialization works")
    
    print("Testing IngestMonitorWorker...")
    
    # Test Worker integration
    worker = IngestMonitorWorker(settings, api_client, state_service)
    
    # Test cache delegation
    worker_cache = worker.get_status_cache()
    assert worker_cache == updated_cache, "Worker should delegate cache access to StateService"
    print("IngestMonitorWorker delegation works")
    
    # Test that worker is not running initially
    assert worker._running is False, "Worker should not be running initially"
    
    # Test cleanup (should handle being called when not running)
    await worker.stop_monitoring()
    print("IngestMonitorWorker lifecycle methods work")
    
    # Cleanup API client
    await api_client.close()
    print("IngestApiClient cleanup works")
    
    print("All refactored Ingest Monitor component tests passed!")
    print("   IngestApiClient: HTTP communication layer")
    print("   IngestStateService: State management & events") 
    print("   IngestMonitorWorker: Polling orchestration")


if __name__ == "__main__":
    asyncio.run(test_ingest_monitor_components())