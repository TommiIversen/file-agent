"""Tests for _detect_justin_version() in app.config.

Uses realistic plist data matching the actual production Justin machine
(just in mac pro 2025.2.2 installed at /Applications/just in mac pro.app).
"""
import plistlib
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import _detect_justin_version


# --- Realistic plist fixtures (from ingest machine mf91328) ---

JUSTIN_2025_PLIST: dict = {
    "CFBundleName": "just in mac pro",
    "CFBundleIdentifier": "com.toolsonair.justinmacpro",
    "CFBundleShortVersionString": "2025.2.2",
    "CFBundleVersion": "2025.2.2",
    "CFBundleExecutable": "just in mac pro",
    "CFBundlePackageType": "APPL",
    "LSMinimumSystemVersion": "12.0",
}

JUSTIN_2026_PLIST: dict = {
    "CFBundleName": "just in mac pro 2026",
    "CFBundleIdentifier": "com.toolsonair.justinmacpro2026",
    "CFBundleShortVersionString": "2026.1.0",
    "CFBundleVersion": "2026.1.0",
    "CFBundleExecutable": "just in mac pro 2026",
    "CFBundlePackageType": "APPL",
    "LSMinimumSystemVersion": "13.0",
}


def _write_plist(path: Path, data: dict) -> None:
    """Write a plist file to disk (creating parent dirs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        plistlib.dump(data, f)


class TestDetectJustinVersion:
    """Tests for _detect_justin_version."""

    def test_returns_unknown_on_non_darwin(self):
        """On Windows/Linux the function exits immediately."""
        with patch("app.config.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert _detect_justin_version() == "unknown"

    @patch("app.config.sys")
    def test_detects_2025_version(self, mock_sys, tmp_path: Path):
        """Detects Justin 2025.2.2 from realistic macOS plist."""
        mock_sys.platform = "darwin"
        plist_path = tmp_path / "just in mac pro.app" / "Contents" / "Info.plist"
        _write_plist(plist_path, JUSTIN_2025_PLIST)

        result = _detect_justin_version(search_paths=[plist_path])
        assert result == "2025.2.2"

    @patch("app.config.sys")
    def test_detects_2026_version(self, mock_sys, tmp_path: Path):
        """Detects Justin 2026.1.0 from new app bundle name."""
        mock_sys.platform = "darwin"
        plist_path = tmp_path / "just in mac pro 2026.app" / "Contents" / "Info.plist"
        _write_plist(plist_path, JUSTIN_2026_PLIST)

        result = _detect_justin_version(search_paths=[plist_path])
        assert result == "2026.1.0"

    @patch("app.config.sys")
    def test_prefers_first_found(self, mock_sys, tmp_path: Path):
        """When both 2025 and 2026 are installed, returns the first match."""
        mock_sys.platform = "darwin"
        path_2025 = tmp_path / "just in mac pro.app" / "Contents" / "Info.plist"
        path_2026 = tmp_path / "just in mac pro 2026.app" / "Contents" / "Info.plist"
        _write_plist(path_2025, JUSTIN_2025_PLIST)
        _write_plist(path_2026, JUSTIN_2026_PLIST)

        result = _detect_justin_version(search_paths=[path_2025, path_2026])
        assert result == "2025.2.2"

    @patch("app.config.sys")
    def test_falls_through_to_second_path(self, mock_sys, tmp_path: Path):
        """If first path doesn't exist, tries the next one."""
        mock_sys.platform = "darwin"
        missing = tmp_path / "nonexistent.app" / "Contents" / "Info.plist"
        path_2026 = tmp_path / "just in mac pro 2026.app" / "Contents" / "Info.plist"
        _write_plist(path_2026, JUSTIN_2026_PLIST)

        result = _detect_justin_version(search_paths=[missing, path_2026])
        assert result == "2026.1.0"

    @patch("app.config.sys")
    def test_returns_unknown_when_not_installed(self, mock_sys, tmp_path: Path):
        """Returns 'unknown' on macOS when Justin is not installed."""
        mock_sys.platform = "darwin"
        missing_paths = [
            tmp_path / "nope1.app" / "Contents" / "Info.plist",
            tmp_path / "nope2.app" / "Contents" / "Info.plist",
        ]
        result = _detect_justin_version(search_paths=missing_paths)
        assert result == "unknown"

    @patch("app.config.sys")
    def test_returns_unknown_when_plist_missing_version_key(self, mock_sys, tmp_path: Path):
        """Returns 'unknown' if plist exists but lacks CFBundleShortVersionString."""
        mock_sys.platform = "darwin"
        plist_path = tmp_path / "app.app" / "Contents" / "Info.plist"
        _write_plist(plist_path, {"CFBundleName": "just in mac pro"})

        result = _detect_justin_version(search_paths=[plist_path])
        assert result == "unknown"

    @patch("app.config.sys")
    def test_handles_corrupt_plist(self, mock_sys, tmp_path: Path):
        """Gracefully handles a corrupt/unreadable plist file."""
        mock_sys.platform = "darwin"
        plist_path = tmp_path / "bad.app" / "Contents" / "Info.plist"
        plist_path.parent.mkdir(parents=True)
        plist_path.write_bytes(b"this is not valid plist data")

        result = _detect_justin_version(search_paths=[plist_path])
        assert result == "unknown"

