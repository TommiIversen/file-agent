"""Tests for MacOSMounter.attempt_mount — all branches, mocked subprocess."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.network_mount.macos_mounter import MacOSMounter


SHARE_URL = "smb://user@server.local/share/VOL1"


def _make_process(returncode=0, stdout=b"", stderr=b""):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


@pytest.fixture
def mounter():
    m = MacOSMounter(mount_point="/Volumes/VOL1")
    # Mock all collaborators
    m._network_checker = AsyncMock()
    m._mount_validator = AsyncMock()
    m._mount_cleaner = AsyncMock()
    return m


class TestAttemptMount:

    async def test_already_mounted_returns_true(self, mounter):
        """Step 1: if verify_mount_accessible returns truthy, skip mount."""
        mounter.verify_mount_accessible = AsyncMock(return_value=(True, True))

        result = await mounter.attempt_mount(SHARE_URL)

        assert result is True
        mounter._network_checker.is_network_available.assert_not_awaited()

    async def test_mounted_but_not_accessible_does_not_skip(self, mounter):
        """Regression: mounted=True but accessible=False must NOT short-circuit.

        Before bugfix, `if await self.verify_mount_accessible(...)` always
        returned truthy because any tuple (even (False, False)) is truthy.
        """
        mounter.verify_mount_accessible = AsyncMock(
            side_effect=[(True, False), (True, True)]
        )
        mounter._network_checker.is_network_available.return_value = True
        mounter._mount_validator.find_ghost_mounts.return_value = []

        proc = _make_process(returncode=0)
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await mounter.attempt_mount(SHARE_URL)

        assert result is True
        # Must have proceeded to network check + mount, not short-circuited
        mounter._network_checker.is_network_available.assert_awaited_once()

    async def test_network_unavailable_returns_false(self, mounter):
        """Step 2: if network check fails, return False."""
        mounter.verify_mount_accessible = AsyncMock(return_value=(False, False))
        mounter._network_checker.is_network_available.return_value = False

        result = await mounter.attempt_mount(SHARE_URL)

        assert result is False

    async def test_ghost_mounts_cleaned(self, mounter):
        """Step 3: ghost mounts are cleaned before mount attempt."""
        mounter.verify_mount_accessible = AsyncMock(
            side_effect=[(False, False), (True, True)]
        )
        mounter._network_checker.is_network_available.return_value = True
        mounter._mount_validator.find_ghost_mounts.return_value = ["/Volumes/VOL1_1"]

        proc = _make_process(returncode=0)
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await mounter.attempt_mount(SHARE_URL)

        assert result is True
        mounter._mount_cleaner.cleanup_ghost_mounts.assert_awaited_once()
        mounter._mount_cleaner.cleanup_invalid_mount_point.assert_awaited_once()

    async def test_successful_mount(self, mounter):
        """Happy path: mount succeeds, verify returns True."""
        mounter.verify_mount_accessible = AsyncMock(
            side_effect=[(False, False), (True, True)]
        )
        mounter._network_checker.is_network_available.return_value = True
        mounter._mount_validator.find_ghost_mounts.return_value = []

        proc = _make_process(returncode=0)
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await mounter.attempt_mount(SHARE_URL)

        assert result is True

    async def test_mount_succeeds_but_verify_fails(self, mounter):
        """Mount command returns 0 but mount point not accessible."""
        mounter.verify_mount_accessible = AsyncMock(return_value=(False, False))
        mounter._network_checker.is_network_available.return_value = True
        mounter._mount_validator.find_ghost_mounts.return_value = []

        proc = _make_process(returncode=0)
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await mounter.attempt_mount(SHARE_URL)

        assert result is False

    async def test_mount_command_fails(self, mounter):
        """Mount command returns non-zero."""
        mounter.verify_mount_accessible = AsyncMock(return_value=(False, False))
        mounter._network_checker.is_network_available.return_value = True
        mounter._mount_validator.find_ghost_mounts.return_value = []

        proc = _make_process(returncode=1, stderr=b"mount failed")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await mounter.attempt_mount(SHARE_URL)

        assert result is False

    async def test_mount_timeout(self, mounter):
        """Subprocess times out after 30s."""
        mounter.verify_mount_accessible = AsyncMock(return_value=(False, False))
        mounter._network_checker.is_network_available.return_value = True
        mounter._mount_validator.find_ghost_mounts.return_value = []

        proc = AsyncMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        proc.kill = MagicMock()
        proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await mounter.attempt_mount(SHARE_URL)

        assert result is False
        proc.kill.assert_called_once()

    async def test_unexpected_exception_returns_false(self, mounter):
        """Any unhandled exception should return False, not crash."""
        mounter.verify_mount_accessible = AsyncMock(side_effect=RuntimeError("boom"))

        result = await mounter.attempt_mount(SHARE_URL)

        assert result is False
