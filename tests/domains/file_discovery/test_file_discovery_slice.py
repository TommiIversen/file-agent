"""Tests for FileDiscoverySlice — discovery, status, and growth management."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.domains.file_discovery.file_discovery_slice import FileDiscoverySlice
from app.core.exceptions import InvalidTransitionError
from app.models import TrackedFile, FileStatus


def _tf(path="/src/test.mxf", status=FileStatus.DISCOVERED, **kw):
    """Shorthand TrackedFile factory."""
    defaults = dict(file_path=path, file_size=1000, status=status)
    defaults.update(kw)
    return TrackedFile(**defaults)


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def sm():
    return AsyncMock()


@pytest.fixture
def bus():
    return AsyncMock()


@pytest.fixture
def slice(repo, sm, bus):
    return FileDiscoverySlice(
        file_repository=repo,
        state_machine=sm,
        event_bus=bus,
        cooldown_minutes=60,
    )


# ── get_active_file_by_path / get_current_file_for_path ────────

class TestFilePathLookups:
    @pytest.mark.asyncio
    async def test_get_active_file_by_path_finds_active(self, slice, repo):
        f = _tf(status=FileStatus.COPYING)
        repo.get_all.return_value = [f]

        result = await slice.get_active_file_by_path("/src/test.mxf")
        assert result is not None
        assert result.status == FileStatus.COPYING

    @pytest.mark.asyncio
    async def test_get_active_returns_none_for_terminal(self, slice, repo):
        f = _tf(status=FileStatus.COMPLETED)
        repo.get_all.return_value = [f]

        result = await slice.get_active_file_by_path("/src/test.mxf")
        # FileSelectionLogic.select_active_for_path returns None for COMPLETED
        assert result is None

    @pytest.mark.asyncio
    async def test_get_current_file_for_path(self, slice, repo):
        f = _tf(status=FileStatus.COMPLETED)
        repo.get_all.return_value = [f]

        result = await slice.get_current_file_for_path("/src/test.mxf")
        assert result is not None


# ── should_skip_file_processing ─────────────────────────────────

class TestShouldSkipFileProcessing:
    @pytest.mark.asyncio
    async def test_no_existing_file_returns_false(self, slice, repo):
        repo.get_all.return_value = []
        assert await slice.should_skip_file_processing("/src/new.mxf") is False

    @pytest.mark.asyncio
    async def test_completed_delete_failed_returns_true(self, slice, repo):
        f = _tf(status=FileStatus.COMPLETED_DELETE_FAILED)
        repo.get_all.return_value = [f]
        assert await slice.should_skip_file_processing("/src/test.mxf") is True

    @pytest.mark.asyncio
    async def test_space_error_in_cooldown_returns_true(self, slice, repo):
        f = _tf(
            status=FileStatus.SPACE_ERROR,
            space_error_at=datetime.now() - timedelta(minutes=30),
        )
        repo.get_all.return_value = [f]
        assert await slice.should_skip_file_processing("/src/test.mxf") is True

    @pytest.mark.asyncio
    async def test_space_error_past_cooldown_returns_false(self, slice, repo):
        f = _tf(
            status=FileStatus.SPACE_ERROR,
            space_error_at=datetime.now() - timedelta(minutes=120),
        )
        repo.get_all.return_value = [f]
        assert await slice.should_skip_file_processing("/src/test.mxf") is False

    @pytest.mark.asyncio
    async def test_active_file_returns_false(self, slice, repo):
        f = _tf(status=FileStatus.COPYING)
        repo.get_all.return_value = [f]
        assert await slice.should_skip_file_processing("/src/test.mxf") is False


# ── add_discovered_file ─────────────────────────────────────────

class TestAddDiscoveredFile:
    @pytest.mark.asyncio
    async def test_creates_new_file_and_publishes_event(self, slice, repo, bus):
        repo.get_all.return_value = []  # No existing files

        result = await slice.add_discovered_file("/src/new.mxf", 5000)

        assert result.file_path == "/src/new.mxf"
        assert result.status == FileStatus.DISCOVERED
        repo.add.assert_awaited_once()
        bus.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_existing_active_file(self, slice, repo, bus):
        existing = _tf(status=FileStatus.COPYING)
        repo.get_all.return_value = [existing]

        result = await slice.add_discovered_file("/src/test.mxf", 5000)

        assert result is existing
        repo.add.assert_not_awaited()
        bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_completed_delete_failed(self, slice, repo, bus):
        existing = _tf(status=FileStatus.COMPLETED_DELETE_FAILED)
        repo.get_all.return_value = [existing]

        result = await slice.add_discovered_file("/src/test.mxf", 5000)

        assert result is existing
        repo.add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_new_for_removed_file(self, slice, repo, bus):
        removed = _tf(status=FileStatus.REMOVED)
        repo.get_all.return_value = [removed]

        result = await slice.add_discovered_file("/src/test.mxf", 5000)

        # Should create a new entry (not return the old one)
        assert result.status == FileStatus.DISCOVERED
        repo.add.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_new_for_completed_file(self, slice, repo, bus):
        completed = _tf(status=FileStatus.COMPLETED)
        repo.get_all.return_value = [completed]

        result = await slice.add_discovered_file("/src/test.mxf", 5000)

        assert result.status == FileStatus.DISCOVERED
        repo.add.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_event_bus_still_works(self, repo, sm):
        s = FileDiscoverySlice(file_repository=repo, state_machine=sm, event_bus=None)
        repo.get_all.return_value = []

        result = await s.add_discovered_file("/src/new.mxf", 5000)
        assert result.status == FileStatus.DISCOVERED


# ── mark_file_ready ──────────────────────────────────────────────

class TestMarkFileReady:
    @pytest.mark.asyncio
    async def test_success_transitions_and_publishes(self, slice, sm, bus):
        tf = _tf()
        sm.transition.return_value = tf

        result = await slice.mark_file_ready("f1")

        assert result is True
        sm.transition.assert_awaited_once_with(file_id="f1", new_status=FileStatus.READY)
        bus.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_transition_returns_false(self, slice, sm):
        sm.transition.side_effect = InvalidTransitionError("f.mxf", "Discovered", "Ready")

        result = await slice.mark_file_ready("f1")
        assert result is False

    @pytest.mark.asyncio
    async def test_value_error_returns_false(self, slice, sm):
        sm.transition.side_effect = ValueError("not found")

        result = await slice.mark_file_ready("f1")
        assert result is False


# ── mark_file_growing / mark_file_ready_to_start_growing ────────

class TestMarkFileGrowing:
    @pytest.mark.asyncio
    async def test_success(self, slice, sm):
        result = await slice.mark_file_growing("f1")
        assert result is True
        sm.transition.assert_awaited_once_with(file_id="f1", new_status=FileStatus.GROWING)

    @pytest.mark.asyncio
    async def test_invalid_transition(self, slice, sm):
        sm.transition.side_effect = InvalidTransitionError("f.mxf", "Completed", "Growing")
        assert await slice.mark_file_growing("f1") is False


class TestMarkFileReadyToStartGrowing:
    @pytest.mark.asyncio
    async def test_success_publishes_ready_event(self, slice, sm, bus):
        tf = _tf()
        sm.transition.return_value = tf

        result = await slice.mark_file_ready_to_start_growing("f1")

        assert result is True
        sm.transition.assert_awaited_once_with(
            file_id="f1", new_status=FileStatus.READY_TO_START_GROWING
        )
        bus.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_transition(self, slice, sm):
        sm.transition.side_effect = InvalidTransitionError("f.mxf", "Copying", "ReadyToStartGrowing")
        assert await slice.mark_file_ready_to_start_growing("f1") is False


# ── get_files_by_status ──────────────────────────────────────────

class TestGetFilesByStatus:
    @pytest.mark.asyncio
    async def test_returns_matching_files(self, slice, repo):
        ready = _tf(status=FileStatus.READY)
        copying = _tf(path="/src/other.mxf", status=FileStatus.COPYING)
        repo.get_all.return_value = [ready, copying]

        result = await slice.get_files_by_status(FileStatus.READY)
        assert len(result) == 1
        assert result[0].status == FileStatus.READY

    @pytest.mark.asyncio
    async def test_deduplicates_by_path_keeping_most_current(self, slice, repo):
        old = _tf(status=FileStatus.READY, discovered_at=datetime(2026, 1, 1))
        new = _tf(status=FileStatus.READY, discovered_at=datetime(2026, 3, 1))
        repo.get_all.return_value = [old, new]

        result = await slice.get_files_by_status(FileStatus.READY)
        assert len(result) == 1
        assert result[0].discovered_at == datetime(2026, 3, 1)


# ── get_files_needing_growth_monitoring ──────────────────────────

class TestGetFilesNeedingGrowthMonitoring:
    @pytest.mark.asyncio
    async def test_returns_growing_files_with_growth_check(self, slice, repo):
        growing = _tf(status=FileStatus.GROWING, last_growth_check=datetime.now())
        no_check = _tf(path="/src/b.mxf", status=FileStatus.GROWING, last_growth_check=None)
        completed = _tf(path="/src/c.mxf", status=FileStatus.COMPLETED, last_growth_check=datetime.now())
        repo.get_all.return_value = [growing, no_check, completed]

        result = await slice.get_files_needing_growth_monitoring()
        assert len(result) == 1
        assert result[0] is growing


# ── update_file_growth_info ──────────────────────────────────────

class TestUpdateFileGrowthInfo:
    @pytest.mark.asyncio
    async def test_updates_fields_and_saves(self, slice, repo):
        f = _tf()
        repo.get_by_id.return_value = f

        result = await slice.update_file_growth_info(
            "f1", file_size=2000, previous_file_size=1000, growth_rate_mbps=10.5
        )

        assert result is True
        assert f.file_size == 2000
        assert f.previous_file_size == 1000
        assert f.growth_rate_mbps == 10.5
        repo.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_file_not_found_returns_false(self, slice, repo):
        repo.get_by_id.return_value = None
        assert await slice.update_file_growth_info("unknown", file_size=1000) is False


# ── _is_more_current ────────────────────────────────────────────

class TestIsMoreCurrent:
    def test_active_status_beats_terminal(self, slice):
        copying = _tf(status=FileStatus.COPYING)
        completed = _tf(status=FileStatus.COMPLETED)
        assert slice._is_more_current(copying, completed) is True
        assert slice._is_more_current(completed, copying) is False

    def test_same_status_newer_discovered_wins(self, slice):
        old = _tf(status=FileStatus.READY, discovered_at=datetime(2026, 1, 1))
        new = _tf(status=FileStatus.READY, discovered_at=datetime(2026, 3, 1))
        assert slice._is_more_current(new, old) is True
        assert slice._is_more_current(old, new) is False
