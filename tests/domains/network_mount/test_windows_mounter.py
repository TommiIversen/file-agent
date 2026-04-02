"""Tests for WindowsMounter — verify_mount_accessible + attempt_mount."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.domains.network_mount.windows_mounter import WindowsMounter


def _make_process(returncode: int = 0, stderr: bytes = b""):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(b"", stderr))
    return proc


@pytest.fixture
def mounter():
    return WindowsMounter(drive_letter="Z")


@pytest.fixture
def mounter_no_drive():
    return WindowsMounter(drive_letter=None)


class TestVerifyMountAccessible:

    async def test_path_does_not_exist(self, mounter, tmp_path):
        """Non-existent path -> (False, False)."""
        result = await mounter.verify_mount_accessible(str(tmp_path / "nope"))
        assert result == (False, False)

    async def test_path_is_file_not_dir(self, mounter, tmp_path):
        """Exists but is a file -> (True, False)."""
        f = tmp_path / "somefile.txt"
        f.write_text("hi")
        result = await mounter.verify_mount_accessible(str(f))
        assert result == (True, False)

    async def test_accessible_directory(self, mounter, tmp_path):
        """Normal readable directory -> (True, True)."""
        result = await mounter.verify_mount_accessible(str(tmp_path))
        assert result == (True, True)

    async def test_directory_not_listable(self, mounter, tmp_path):
        """Directory exists but os.listdir raises OSError -> (True, False)."""
        with patch("os.listdir", side_effect=OSError("network error")):
            result = await mounter.verify_mount_accessible(str(tmp_path))
        assert result == (True, False)

    async def test_directory_permission_error(self, mounter, tmp_path):
        """Directory exists but os.listdir raises PermissionError -> (True, False)."""
        with patch("os.listdir", side_effect=PermissionError("access denied")):
            result = await mounter.verify_mount_accessible(str(tmp_path))
        assert result == (True, False)

    async def test_outer_exception_returns_false_false(self, mounter):
        """Unexpected exception in Path() -> (False, False)."""
        with patch(
            "app.domains.network_mount.windows_mounter.Path",
            side_effect=RuntimeError("boom"),
        ):
            result = await mounter.verify_mount_accessible("Z:\\")
        assert result == (False, False)


class TestAttemptMount:

    SHARE = "smb://server.local/share/VOL"

    async def test_success_with_drive_letter(self, mounter):
        proc = _make_process(returncode=0)
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            result = await mounter.attempt_mount(self.SHARE)

        assert result is True
        # Should include drive letter in command
        cmd = mock_exec.call_args[0]
        assert "Z:" in cmd

    async def test_success_without_drive_letter(self, mounter_no_drive):
        proc = _make_process(returncode=0)
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            result = await mounter_no_drive.attempt_mount(self.SHARE)

        assert result is True
        cmd = mock_exec.call_args[0]
        assert "Z:" not in cmd

    async def test_mount_failure(self, mounter):
        proc = _make_process(returncode=1, stderr=b"access denied")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await mounter.attempt_mount(self.SHARE)

        assert result is False

    async def test_mount_failure_empty_stderr(self, mounter):
        proc = _make_process(returncode=1, stderr=b"")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await mounter.attempt_mount(self.SHARE)

        assert result is False

    async def test_exception_returns_false(self, mounter):
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("no such file"),
        ):
            result = await mounter.attempt_mount(self.SHARE)

        assert result is False
