"""Tests for MacOSMountValidator.find_ghost_mounts — all branches."""
import pytest
from unittest.mock import patch, AsyncMock

from app.domains.network_mount.macos_mount_utils import MacOSMountValidator


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
