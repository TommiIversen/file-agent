"""Tests for NetworkMountService.ensure_mount_available — all branches."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.network_mount.mount_service import NetworkMountService


SHARE_URL = "smb://user@server.local/share"
LOCAL_PATH = "/Volumes/VOL"


@pytest.fixture
def service():
    """Build a NetworkMountService with mocked internals."""
    with patch.object(NetworkMountService, "_initialize_mounter"):
        svc = NetworkMountService.__new__(NetworkMountService)
        svc._config = MagicMock()
        svc._mounter = AsyncMock()
        svc._platform_factory = MagicMock()
        # Defaults: auto-mount enabled, mounter present
        svc._config.is_auto_mount_enabled.return_value = True
        return svc


class TestEnsureMountAvailable:

    async def test_auto_mount_disabled(self, service):
        service._config.is_auto_mount_enabled.return_value = False
        assert await service.ensure_mount_available(SHARE_URL, LOCAL_PATH) is False

    async def test_no_mounter(self, service):
        service._mounter = None
        assert await service.ensure_mount_available(SHARE_URL, LOCAL_PATH) is False

    async def test_empty_share_url(self, service):
        assert await service.ensure_mount_available("", LOCAL_PATH) is False

    async def test_already_accessible(self, service):
        """Mount already accessible → return True without attempting mount."""
        service._mounter.verify_mount_accessible.return_value = (True, True)

        result = await service.ensure_mount_available(SHARE_URL, LOCAL_PATH)

        assert result is True
        service._mounter.attempt_mount.assert_not_awaited()

    async def test_not_accessible_mount_succeeds_then_accessible(self, service):
        """Not accessible → mount succeeds → verify again → accessible."""
        service._mounter.verify_mount_accessible.side_effect = [
            (False, False),
            (True, True),
        ]
        service._mounter.attempt_mount.return_value = True

        assert await service.ensure_mount_available(SHARE_URL, LOCAL_PATH) is True

    async def test_not_accessible_mount_succeeds_still_not_accessible(self, service):
        """Mount succeeds but post-mount verify fails."""
        service._mounter.verify_mount_accessible.side_effect = [
            (False, False),
            (True, False),
        ]
        service._mounter.attempt_mount.return_value = True

        assert await service.ensure_mount_available(SHARE_URL, LOCAL_PATH) is False

    async def test_not_accessible_mount_fails(self, service):
        """Mount attempt fails → return False."""
        service._mounter.verify_mount_accessible.return_value = (False, False)
        service._mounter.attempt_mount.return_value = False

        assert await service.ensure_mount_available(SHARE_URL, LOCAL_PATH) is False

    async def test_exception_returns_false(self, service):
        """Unexpected exception → return False."""
        service._mounter.verify_mount_accessible.side_effect = RuntimeError("boom")

        assert await service.ensure_mount_available(SHARE_URL, LOCAL_PATH) is False

    async def test_mounted_but_not_accessible_triggers_remount(self, service):
        """Mounted=True but accessible=False → should attempt mount."""
        service._mounter.verify_mount_accessible.side_effect = [
            (True, False),
            (True, True),
        ]
        service._mounter.attempt_mount.return_value = True

        assert await service.ensure_mount_available(SHARE_URL, LOCAL_PATH) is True
        service._mounter.attempt_mount.assert_awaited_once()
