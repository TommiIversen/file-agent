"""
Test event publishing for IngestMonitorService

Verify that events are properly published when channel states change.
"""
import asyncio
from typing import List

import pytest

from app.core.events.event_bus import DomainEventBus
from app.domains.ingest_monitor.events import (
    ChannelRecordingStartedEvent,
    ChannelRecordingStoppedEvent,
    IngestStatusUpdatedEvent
)


class EventCollector:
    """Helper class to collect published events for testing."""
    
    def __init__(self):
        self.events: List = []
    
    async def handle_recording_started(self, event: ChannelRecordingStartedEvent):
        self.events.append(("recording_started", event.channel_name))
    
    async def handle_recording_stopped(self, event: ChannelRecordingStoppedEvent):
        self.events.append(("recording_stopped", event.channel_name))
    
    async def handle_status_updated(self, event: IngestStatusUpdatedEvent):
        self.events.append(("status_updated", len(event.status_snapshot)))


@pytest.mark.asyncio
async def test_event_publishing():
    """Test that the event bus correctly publishes and delivers events."""
    
    print("Testing event publishing...")
    
    # Create event bus and collector
    event_bus = DomainEventBus()
    collector = EventCollector()
    
    # Subscribe to events
    await event_bus.subscribe(ChannelRecordingStartedEvent, collector.handle_recording_started)
    await event_bus.subscribe(ChannelRecordingStoppedEvent, collector.handle_recording_stopped)
    await event_bus.subscribe(IngestStatusUpdatedEvent, collector.handle_status_updated)
    
    # Test publishing events
    await event_bus.publish(ChannelRecordingStartedEvent(channel_name="KAM_1"))
    await event_bus.publish(ChannelRecordingStoppedEvent(channel_name="KAM_2"))
    await event_bus.publish(IngestStatusUpdatedEvent(status_snapshot={"KAM_1": {}, "KAM_2": {}}))
    
    # Verify events were received
    assert len(collector.events) == 3, f"Expected 3 events, got {len(collector.events)}"
    
    # Check event details
    assert collector.events[0] == ("recording_started", "KAM_1")
    assert collector.events[1] == ("recording_stopped", "KAM_2")
    assert collector.events[2] == ("status_updated", 2)  # 2 channels in snapshot
    
    print("✅ Event publishing works correctly")
    print(f"📨 Received events: {collector.events}")
    print("🎉 Event system test passed!")


if __name__ == "__main__":
    asyncio.run(test_event_publishing())