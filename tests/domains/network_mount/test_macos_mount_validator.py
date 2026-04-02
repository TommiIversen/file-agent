"""Tests for MacOSMountValidator + MacOSMountCleaner — all branches."""
import pytest
from unittest.mock import patch, AsyncMock

from app.domains.network_mount.macos_mount_utils import MacOSMountValidator, MacOSMountCleaner


@pytest.fixture
def validator():
    return MacOSMountValidator()


# ------------------------------------------------------------------
# _find_ghost_dirs (sync helper — uses real filesystem via tmp_path)
# ------------------------------------------------------------------

class TestFindGhostDirs:

    def test_no_ghosts(self, tmp_path):
        base = tmp_path / "SK6402"
        base.mkdir()
        assert MacOSMountValidator._find_ghost_dirs(str(base)) == []

    def test_finds_numbered_variants(self, tmp_path):
        base = tmp_path / "SK6402"
        base.mkdir()
        (tmp_path / "SK6402_1").mkdir()
        (tmp_path / "SK6402_2").mkdir()

        result = MacOSMountValidator._find_ghost_dirs(str(base))
        assert sorted(result) == sorted([
            str(tmp_path / "SK6402_1"),
            str(tmp_path / "SK6402_2"),
        ])

    def test_ignores_non_numeric_suffix(self, tmp_path):
        base = tmp_path / "VOL"
        base.mkdir()
        (tmp_path / "VOL_abc").mkdir()
        (tmp_path / "VOL_").mkdir()

        assert MacOSMountValidator._find_ghost_dirs(str(base)) == []

    def test_ignores_files(self, tmp_path):
        base = tmp_path / "VOL"
        base.mkdir()
        (tmp_path / "VOL_1").write_text("file")  # file, not dir

        assert MacOSMountValidator._find_ghost_dirs(str(base)) == []

    def test_parent_does_not_exist(self, tmp_path):
        fake = tmp_path / "nonexistent_parent" / "VOL"
        assert MacOSMountValidator._find_ghost_dirs(str(fake)) == []

    def test_ignores_similar_prefix(self, tmp_path):
        """SK6402X_1 should NOT match SK6402."""
        base = tmp_path / "SK6402"
        base.mkdir()
        (tmp_path / "SK6402X_1").mkdir()

        assert MacOSMountValidator._find_ghost_dirs(str(base)) == []


# ------------------------------------------------------------------
# find_ghost_mounts (async wrapper)
# ------------------------------------------------------------------

class TestFindGhostMounts:

    async def test_delegates_to_sync_helper(self, validator, tmp_path):
        base = tmp_path / "VOL"
        base.mkdir()
        (tmp_path / "VOL_3").mkdir()

        result = await validator.find_ghost_mounts(str(base))
        assert result == [str(tmp_path / "VOL_3")]

    async def test_exception_returns_empty(self, validator):
        with patch.object(
            MacOSMountValidator,
            "_find_ghost_dirs",
            side_effect=RuntimeError("boom"),
        ):
            result = await validator.find_ghost_mounts("/Volumes/X")
        assert result == []


# ------------------------------------------------------------------
# is_local_folder_at_mount_point
# ------------------------------------------------------------------

class TestIsLocalFolderAtMountPoint:

    async def test_path_does_not_exist(self, validator, tmp_path):
        result = await validator.is_local_folder_at_mount_point(str(tmp_path / "nope"))
        assert result is False

    async def test_path_is_file(self, validator, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        result = await validator.is_local_folder_at_mount_point(str(f))
        assert result is False

    async def test_listable_dir_is_not_problematic(self, validator, tmp_path):
        result = await validator.is_local_folder_at_mount_point(str(tmp_path))
        assert result is False

    async def test_permission_error_is_problematic(self, validator, tmp_path):
        """Directory exists but can't be listed -> problematic local folder."""
        d = tmp_path / "mount"
        d.mkdir()
        # Patch os-level iterdir to raise PermissionError
        with patch.object(type(d), "iterdir", side_effect=PermissionError("denied")):
            result = await validator.is_local_folder_at_mount_point(str(d))
        assert result is True

    async def test_outer_exception_returns_false(self, validator):
        with patch("app.domains.network_mount.macos_mount_utils.Path", side_effect=RuntimeError("boom")):
            result = await validator.is_local_folder_at_mount_point("/Volumes/X")
        assert result is False


# ------------------------------------------------------------------
# MacOSMountCleaner.cleanup_invalid_mount_point
# ------------------------------------------------------------------

@pytest.fixture
def cleaner():
    mock_validator = AsyncMock()
    return MacOSMountCleaner(mock_validator)


class TestCleanupInvalidMountPoint:

    async def test_non_volumes_path_returns_true(self, cleaner):
        """Safety check: paths outside /Volumes/ are ignored."""
        # On Windows str(Path("/tmp/something")) won't start with /Volumes/
        result = await cleaner.cleanup_invalid_mount_point("/tmp/something")
        assert result is True

    async def test_no_problematic_folder(self, cleaner):
        """Not a problematic folder — nothing to do."""
        cleaner._validator.is_local_folder_at_mount_point.return_value = False
        # Patch str(path_obj) to return a /Volumes/ path regardless of OS
        with patch("app.domains.network_mount.macos_mount_utils.Path") as MockPath:
            MockPath.return_value.__str__ = lambda _: "/Volumes/VOL"
            result = await cleaner.cleanup_invalid_mount_point("/Volumes/VOL")
        assert result is True

    async def test_removes_problematic_folder(self, cleaner):
        """Problematic folder gets removed."""
        cleaner._validator.is_local_folder_at_mount_point.return_value = True
        with (
            patch("app.domains.network_mount.macos_mount_utils.Path") as MockPath,
            patch("app.domains.network_mount.macos_mount_utils.asyncio.to_thread") as mock_tt,
        ):
            MockPath.return_value.__str__ = lambda _: "/Volumes/VOL"
            result = await cleaner.cleanup_invalid_mount_point("/Volumes/VOL")
        assert result is True
        mock_tt.assert_awaited_once()

    async def test_rmdir_failure_returns_false(self, cleaner):
        """rmdir fails -> return False."""
        cleaner._validator.is_local_folder_at_mount_point.return_value = True
        with (
            patch("app.domains.network_mount.macos_mount_utils.Path") as MockPath,
            patch(
                "app.domains.network_mount.macos_mount_utils.asyncio.to_thread",
                side_effect=OSError("not empty"),
            ),
        ):
            MockPath.return_value.__str__ = lambda _: "/Volumes/VOL"
            result = await cleaner.cleanup_invalid_mount_point("/Volumes/VOL")
        assert result is False

    async def test_outer_exception_returns_true(self, cleaner):
        """Unexpected exception — don't fail the mount."""
        cleaner._validator.is_local_folder_at_mount_point.side_effect = RuntimeError("boom")
        with patch("app.domains.network_mount.macos_mount_utils.Path") as MockPath:
            MockPath.return_value.__str__ = lambda _: "/Volumes/VOL"
            result = await cleaner.cleanup_invalid_mount_point("/Volumes/VOL")
        assert result is True
