"""
Integration test for WebSocket mount status broadcasting.

Tests the complete flow from StorageMonitorService mount operations
to WebSocket notifications for real-time UI feedback.
"""

from datetime import datetime
from unittest.mock import Mock, AsyncMock

import pytest

from app.services.storage_monitor.storage_monitor import StorageMonitorService
from app.core.events.event_bus import DomainEventBus
from app.services.network_mount.mount_service import NetworkMountService
from app.config import Settings
from app.models import StorageInfo, StorageStatus, MountStatus, MountStatusUpdate


class TestMountStatusWebSocketIntegration:
    """Integration test for mount status WebSocket broadcasting."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings for testing."""
        settings = Mock(spec=Settings)
        settings.SOURCE_PATH = r"C:\temp\source"
        settings.DESTINATION_PATH = r"\\nas\shared\dest"
        settings.enable_auto_mount = True
        return settings

    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus for handling events."""
        event_bus = Mock(spec=DomainEventBus)
        event_bus.publish = AsyncMock()
        return event_bus

    @pytest.fixture
    def mock_network_mount_service_configured(self):
        """Mock NetworkMountService configured for mounting."""
        service = Mock(spec=NetworkMountService)
        service.is_network_mount_configured = Mock(return_value=True)
        service.get_network_share_url = Mock(return_value="//nas/shared")
        service.ensure_mount_available = AsyncMock(return_value=True)
        return service

    @pytest.fixture
    def mock_network_mount_service_failed(self):
        """Mock NetworkMountService that fails mounting."""
        service = Mock(spec=NetworkMountService)
        service.is_network_mount_configured = Mock(return_value=True)
        service.get_network_share_url = Mock(return_value="//nas/shared")
        service.ensure_mount_available = AsyncMock(return_value=False)
        return service

    @pytest.fixture
    def mock_network_mount_service_not_configured(self):
        """Mock NetworkMountService not configured."""
        service = Mock(spec=NetworkMountService)
        service.is_network_mount_configured = Mock(return_value=False)
        return service

    def create_storage_monitor_with_mocks(
        self, settings, event_bus, network_mount_service
    ):
        """Helper to create StorageMonitorService with all required mocks."""
        # Mock StorageChecker
        mock_storage_checker = Mock()

        inaccessible_info = StorageInfo(
            path=r"\\nas\shared\dest",
            is_accessible=False,
            has_write_access=False,
            free_space_gb=0.0,
            total_space_gb=100.0,
            used_space_gb=100.0,
            status=StorageStatus.ERROR,
            warning_threshold_gb=5.0,
            critical_threshold_gb=1.0,
            last_checked=datetime.now(),
        )

        mock_storage_checker.check_path = AsyncMock(return_value=inaccessible_info)

        return StorageMonitorService(
            settings=settings,
            storage_checker=mock_storage_checker,
            event_bus=event_bus,
            network_mount_service=network_mount_service,
        )

    @pytest.mark.asyncio
    async def test_mount_success_websocket_broadcast(
        self,
        mock_settings,
        mock_event_bus,
        mock_network_mount_service_configured,
    ):
        """Test successful mount operation broadcasts correct WebSocket messages."""

        # Create service with configured mount service
        service = self.create_storage_monitor_with_mocks(
            mock_settings, mock_event_bus, mock_network_mount_service_configured
        )

        # Execute storage check to trigger mount operation
        await service._check_single_storage(
            storage_type="destination",
            path=r"\\nas\shared\dest",
            warning_threshold=5.0,
            critical_threshold=1.0,
        )

        # Verify mount status events were published
        assert mock_event_bus.publish.call_count >= 2

        # Check specific mount status events
        calls = mock_event_bus.publish.call_args_list

        # Find MountStatusChangedEvent calls
        mount_events = []
        for call in calls:
            event = call[0][0]  # First positional argument
            if hasattr(event, 'update') and hasattr(event.update, 'mount_status'):
                mount_events.append(event.update)
        
        assert len(mount_events) >= 2

        # First event should be ATTEMPTING status
        attempting_update = mount_events[0]
        assert attempting_update.storage_type == "destination"
        assert attempting_update.mount_status == MountStatus.ATTEMPTING
        assert attempting_update.share_url == "//nas/shared"
        assert attempting_update.target_path == r"\\nas\shared\dest"

        # Second event should be SUCCESS status
        success_update = mount_events[1]
        assert success_update.storage_type == "destination"
        assert success_update.mount_status == MountStatus.SUCCESS
        assert success_update.share_url == "//nas/shared"
        assert success_update.target_path == r"\\nas\shared\dest"

    @pytest.mark.asyncio
    async def test_mount_failure_websocket_broadcast(
        self, mock_settings, mock_event_bus, mock_network_mount_service_failed
    ):
        """Test failed mount operation broadcasts correct WebSocket messages."""

        service = self.create_storage_monitor_with_mocks(
            mock_settings, mock_event_bus, mock_network_mount_service_failed
        )

        # Execute storage check to trigger failed mount operation
        await service._check_single_storage(
            storage_type="destination",
            path=r"\\nas\shared\dest",
            warning_threshold=5.0,
            critical_threshold=1.0,
        )

        # Verify mount status events were published
        assert mock_event_bus.publish.call_count >= 2

        calls = mock_event_bus.publish.call_args_list

        # Find MountStatusChangedEvent calls
        mount_events = []
        for call in calls:
            event = call[0][0]  # First positional argument
            if hasattr(event, 'update') and hasattr(event.update, 'mount_status'):
                mount_events.append(event.update)
        
        assert len(mount_events) >= 2

        # First event: ATTEMPTING
        attempting_update = mount_events[0]
        assert attempting_update.mount_status == MountStatus.ATTEMPTING

        # Second event: FAILED
        failed_update = mount_events[1]
        assert failed_update.mount_status == MountStatus.FAILED
        assert failed_update.error_message == "Network mount operation failed"

    @pytest.mark.asyncio
    async def test_mount_not_configured_websocket_broadcast(
        self,
        mock_settings,
        mock_event_bus,
        mock_network_mount_service_not_configured,
    ):
        """Test not configured mount service broadcasts correct WebSocket message."""

        service = self.create_storage_monitor_with_mocks(
            mock_settings,
            mock_event_bus,
            mock_network_mount_service_not_configured,
        )

        # Execute storage check
        await service._check_single_storage(
            storage_type="destination",
            path=r"\\nas\shared\dest",
            warning_threshold=5.0,
            critical_threshold=1.0,
        )

        # Verify NOT_CONFIGURED status was published as event
        calls = mock_event_bus.publish.call_args_list
        
        # Find the MountStatusChangedEvent
        mount_event = None
        for call in calls:
            event = call[0][0]
            if hasattr(event, 'update') and hasattr(event.update, 'mount_status'):
                mount_event = event.update
                break
        
        assert mount_event is not None
        assert mount_event.mount_status == MountStatus.NOT_CONFIGURED
        assert mount_event.error_message == "Network mount not configured in settings"

    @pytest.mark.asyncio
    async def test_source_storage_no_mount_broadcast(
        self,
        mock_settings,
        mock_event_bus,
        mock_network_mount_service_configured,
    ):
        """Test that source storage doesn't trigger mount broadcasts."""

        service = self.create_storage_monitor_with_mocks(
            mock_settings, mock_event_bus, mock_network_mount_service_configured
        )

        # Execute source storage check
        await service._check_single_storage(
            storage_type="source",
            path=r"C:\temp\source",
            warning_threshold=5.0,
            critical_threshold=1.0,
        )

        # Verify NO mount status events published for source storage
        # Check that no MountStatusChangedEvent was published
        calls = mock_event_bus.publish.call_args_list
        mount_events = []
        for call in calls:
            event = call[0][0]  # First positional argument
            if hasattr(event, 'update') and hasattr(event.update, 'mount_status'):
                mount_events.append(event.update)
        
        assert len(mount_events) == 0

class TestMountStatusSizeCompliance:
    """Verify mount status integration maintains size compliance."""

    def test_notification_handler_size_after_mount_integration(self):
        """Verify NotificationHandler stays within limits after mount status integration."""
        from pathlib import Path

        file_path = Path("app/services/storage_monitor/notification_handler.py")
        with open(file_path, "r") as f:
            lines = f.readlines()

        code_lines = [
            line for line in lines if line.strip() and not line.strip().startswith("#")
        ]

        print(f"NotificationHandler code lines: {len(code_lines)}")
        assert len(code_lines) <= 150, (
            f"NotificationHandler exceeds 150 lines: {len(code_lines)}"
        )

    def test_storage_monitor_size_after_mount_broadcasting(self):
        """Verify StorageMonitorService stays within limits after mount broadcasting."""
        from pathlib import Path

        file_path = Path("app/services/storage_monitor/storage_monitor.py")
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        code_lines = [
            line for line in lines if line.strip() and not line.strip().startswith("#")
        ]

        print(f"StorageMonitorService code lines: {len(code_lines)}")
        assert len(code_lines) <= 400, (
            f"StorageMonitorService exceeds 400 lines: {len(code_lines)}"
        )
