"""Tests for WindowsMounter.verify_mount_accessible — all branches."""
import pytest
from unittest.mock import patch, MagicMock

from app.domains.network_mount.windows_mounter import WindowsMounter


@pytest.fixture
def mounter():
    return WindowsMounter(drive_letter="Z")


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
