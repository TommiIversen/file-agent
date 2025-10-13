"""
Integration test for WebSocket mount status broadcasting.

Tests the complete flow from StorageMonitorService mount operations
to WebSocket notifications for real-time UI feedback.
"""

from datetime import datetime
from unittest.mock import Mock, AsyncMock

import pytest

from app.services.storage_monitor.storage_monitor import StorageMonitorService
from app.services.websocket_manager import WebSocketManager
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
    def mock_websocket_manager(self):
        """Mock WebSocket manager with mount status broadcasting."""
        manager = Mock(spec=WebSocketManager)
        manager.broadcast_storage_status = AsyncMock()
        manager.broadcast_mount_status = AsyncMock()
        return manager

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
        self, settings, websocket_manager, network_mount_service
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
            websocket_manager=websocket_manager,
            network_mount_service=network_mount_service,
        )

    @pytest.mark.asyncio
    async def test_mount_success_websocket_broadcast(
        self,
        mock_settings,
        mock_websocket_manager,
        mock_network_mount_service_configured,
    ):
        """Test successful mount operation broadcasts correct WebSocket messages."""

        # Create service with configured mount service
        service = self.create_storage_monitor_with_mocks(
            mock_settings, mock_websocket_manager, mock_network_mount_service_configured
        )

        # Execute storage check to trigger mount operation
        await service._check_single_storage(
            storage_type="destination",
            path=r"\\nas\shared\dest",
            warning_threshold=5.0,
            critical_threshold=1.0,
        )

        # Verify mount status broadcasts were made
        assert mock_websocket_manager.broadcast_mount_status.call_count >= 2

        # Check specific mount status calls
        calls = mock_websocket_manager.broadcast_mount_status.call_args_list

        # First call should be ATTEMPTING status
        attempting_call = calls[0][0][0]  # First positional argument of first call
        assert attempting_call.storage_type == "destination"
        assert attempting_call.mount_status == MountStatus.ATTEMPTING
        assert attempting_call.share_url == "//nas/shared"
        assert attempting_call.target_path == r"\\nas\shared\dest"

        # Second call should be SUCCESS status
        success_call = calls[1][0][0]  # First positional argument of second call
        assert success_call.storage_type == "destination"
        assert success_call.mount_status == MountStatus.SUCCESS
        assert success_call.share_url == "//nas/shared"
        assert success_call.target_path == r"\\nas\shared\dest"

    @pytest.mark.asyncio
    async def test_mount_failure_websocket_broadcast(
        self, mock_settings, mock_websocket_manager, mock_network_mount_service_failed
    ):
        """Test failed mount operation broadcasts correct WebSocket messages."""

        service = self.create_storage_monitor_with_mocks(
            mock_settings, mock_websocket_manager, mock_network_mount_service_failed
        )

        # Execute storage check to trigger failed mount operation
        await service._check_single_storage(
            storage_type="destination",
            path=r"\\nas\shared\dest",
            warning_threshold=5.0,
            critical_threshold=1.0,
        )

        # Verify mount status broadcasts were made
        assert mock_websocket_manager.broadcast_mount_status.call_count >= 2

        calls = mock_websocket_manager.broadcast_mount_status.call_args_list

        # First call: ATTEMPTING
        attempting_call = calls[0][0][0]
        assert attempting_call.mount_status == MountStatus.ATTEMPTING

        # Second call: FAILED
        failed_call = calls[1][0][0]
        assert failed_call.mount_status == MountStatus.FAILED
        assert failed_call.error_message == "Network mount operation failed"

    @pytest.mark.asyncio
    async def test_mount_not_configured_websocket_broadcast(
        self,
        mock_settings,
        mock_websocket_manager,
        mock_network_mount_service_not_configured,
    ):
        """Test not configured mount service broadcasts correct WebSocket message."""

        service = self.create_storage_monitor_with_mocks(
            mock_settings,
            mock_websocket_manager,
            mock_network_mount_service_not_configured,
        )

        # Execute storage check
        await service._check_single_storage(
            storage_type="destination",
            path=r"\\nas\shared\dest",
            warning_threshold=5.0,
            critical_threshold=1.0,
        )

        # Verify NOT_CONFIGURED status was broadcast
        mock_websocket_manager.broadcast_mount_status.assert_called_once()

        call = mock_websocket_manager.broadcast_mount_status.call_args[0][0]
        assert call.mount_status == MountStatus.NOT_CONFIGURED
        assert call.error_message == "Network mount not configured in settings"

    @pytest.mark.asyncio
    async def test_source_storage_no_mount_broadcast(
        self,
        mock_settings,
        mock_websocket_manager,
        mock_network_mount_service_configured,
    ):
        """Test that source storage doesn't trigger mount broadcasts."""

        service = self.create_storage_monitor_with_mocks(
            mock_settings, mock_websocket_manager, mock_network_mount_service_configured
        )

        # Execute source storage check
        await service._check_single_storage(
            storage_type="source",
            path=r"C:\temp\source",
            warning_threshold=5.0,
            critical_threshold=1.0,
        )

        # Verify NO mount status broadcasts for source storage
        mock_websocket_manager.broadcast_mount_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_websocket_manager_mount_status_message_format(self):
        """Test WebSocketManager formats mount status messages correctly."""

        # Mock WebSocket connections
        mock_websocket = Mock()
        mock_websocket.send_text = AsyncMock()

        # Create WebSocketManager with mock connections
        ws_manager = WebSocketManager(state_manager=Mock(), storage_monitor=Mock())
        ws_manager._connections = [mock_websocket]

        # Create mount status update
        mount_update = MountStatusUpdate(
            storage_type="destination",
            mount_status=MountStatus.ATTEMPTING,
            share_url="//nas/shared",
            mount_path="/Volumes/shared",
            target_path="/Volumes/shared/ingest",
            error_message=None,
        )

        # Test broadcasting
        await ws_manager.broadcast_mount_status(mount_update)

        # Verify message was sent
        mock_websocket.send_text.assert_called_once()

        # Parse sent message
        import json

        sent_message = json.loads(mock_websocket.send_text.call_args[0][0])

        # Verify message structure
        assert sent_message["type"] == "mount_status"
        assert sent_message["data"]["storage_type"] == "destination"
        assert sent_message["data"]["mount_status"] == "ATTEMPTING"
        assert sent_message["data"]["share_url"] == "//nas/shared"
        assert sent_message["data"]["mount_path"] == "/Volumes/shared"
        assert sent_message["data"]["target_path"] == "/Volumes/shared/ingest"
        assert sent_message["data"]["error_message"] is None
        assert "timestamp" in sent_message["data"]


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

    def test_websocket_manager_size_after_mount_support(self):
        """Verify WebSocketManager stays within limits after mount status support."""
        from pathlib import Path

        file_path = Path("app/services/websocket_manager.py")
        with open(file_path, "r") as f:
            lines = f.readlines()

        code_lines = [
            line for line in lines if line.strip() and not line.strip().startswith("#")
        ]

        print(f"WebSocketManager code lines: {len(code_lines)}")
        assert len(code_lines) <= 400, (
            f"WebSocketManager exceeds 400 lines: {len(code_lines)}"
        )
