"""Tests for MacOSNetworkChecker.is_network_available — all branches."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.network_mount.macos_mount_utils import MacOSNetworkChecker


def _make_process(returncode: int = 0):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


@pytest.fixture
def checker():
    return MacOSNetworkChecker()


# ------------------------------------------------------------------
# _extract_hostname (pure, sync)
# ------------------------------------------------------------------

class TestExtractHostname:

    def test_smb_with_user(self):
        result = MacOSNetworkChecker._extract_hostname(
            "smb://svcsk6402@net.dr.dk/nas/videopodcast/SK6402"
        )
        assert result == "net.dr.dk"

    def test_smb_without_user(self):
        result = MacOSNetworkChecker._extract_hostname(
            "smb://fileserver.local/share"
        )
        assert result == "fileserver.local"

    def test_no_scheme_returns_none(self):
        result = MacOSNetworkChecker._extract_hostname("just-a-path/share")
        assert result is None

    def test_afp_with_user(self):
        result = MacOSNetworkChecker._extract_hostname(
            "afp://admin@backup.local/vol"
        )
        assert result == "backup.local"


# ------------------------------------------------------------------
# is_network_available (async, subprocess mocked)
# ------------------------------------------------------------------

class TestIsNetworkAvailable:

    async def test_none_url_returns_true(self, checker):
        assert await checker.is_network_available(None) is True

    async def test_empty_url_returns_true(self, checker):
        assert await checker.is_network_available("") is True

    async def test_unparseable_url_returns_true(self, checker):
        """Cannot extract hostname -> don't block, return True."""
        assert await checker.is_network_available("no-scheme-path") is True

    async def test_ping_success(self, checker):
        proc = _make_process(returncode=0)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await checker.is_network_available(
                "smb://user@host.local/share"
            )
        assert result is True

    async def test_ping_failure(self, checker):
        proc = _make_process(returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await checker.is_network_available(
                "smb://user@host.local/share"
            )
        assert result is False

    async def test_ping_timeout(self, checker):
        proc = AsyncMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        proc.kill = MagicMock()
        proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await checker.is_network_available(
                "smb://user@host.local/share"
            )
        assert result is False

    async def test_unexpected_exception_returns_true(self, checker):
        """Don't block on errors — let the mount attempt decide."""
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("no such file"),
        ):
            result = await checker.is_network_available(
                "smb://user@host.local/share"
            )
        assert result is True
