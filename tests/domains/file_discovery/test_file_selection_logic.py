"""Tests for FileSelectionLogic — 0 mocks, pure logic."""

from datetime import datetime

from app.domains.file_discovery.file_selection_logic import FileSelectionLogic
from app.models import FileStatus, TrackedFile


def _make_file(
    path: str = "/test/file.mxf",
    status: FileStatus = FileStatus.DISCOVERED,
    discovered_at: datetime | None = None,
) -> TrackedFile:
    return TrackedFile(
        file_path=path,
        status=status,
        discovered_at=discovered_at or datetime(2025, 1, 1, 12, 0, 0),
    )


class TestActiveSortKey:
    def test_copying_highest_priority(self):
        f = _make_file(status=FileStatus.COPYING)
        assert FileSelectionLogic.active_sort_key(f)[0] == 1

    def test_priority_order(self):
        """COPYING < IN_QUEUE < GROWING_COPY < READY_TO_START < READY < GROWING < DISCOVERED."""
        statuses = [
            FileStatus.COPYING,
            FileStatus.IN_QUEUE,
            FileStatus.GROWING_COPY,
            FileStatus.READY_TO_START_GROWING,
            FileStatus.READY,
            FileStatus.GROWING,
            FileStatus.DISCOVERED,
            FileStatus.WAITING_FOR_SPACE,
            FileStatus.SPACE_ERROR,
        ]
        files = [_make_file(status=s) for s in statuses]
        priorities = [FileSelectionLogic.active_sort_key(f)[0] for f in files]
        assert priorities == sorted(priorities)

    def test_time_tiebreaker_newer_wins(self):
        older = _make_file(status=FileStatus.READY, discovered_at=datetime(2025, 1, 1))
        newer = _make_file(status=FileStatus.READY, discovered_at=datetime(2025, 1, 2))
        # Newer file should have lower sort key (negative timestamp = more negative)
        assert FileSelectionLogic.active_sort_key(newer) < FileSelectionLogic.active_sort_key(older)

    def test_unknown_status_gets_low_priority(self):
        f = _make_file(status=FileStatus.COMPLETED)
        assert FileSelectionLogic.active_sort_key(f)[0] == 99

    def test_waiting_for_network_same_as_waiting_for_space(self):
        net = _make_file(status=FileStatus.WAITING_FOR_NETWORK)
        space = _make_file(status=FileStatus.WAITING_FOR_SPACE)
        assert FileSelectionLogic.active_sort_key(net)[0] == FileSelectionLogic.active_sort_key(space)[0]


class TestAllSortKey:
    def test_completed_after_active(self):
        active = _make_file(status=FileStatus.DISCOVERED)
        completed = _make_file(status=FileStatus.COMPLETED)
        assert FileSelectionLogic.all_sort_key(active) < FileSelectionLogic.all_sort_key(completed)

    def test_terminal_priority_order(self):
        """COMPLETED < COMPLETED_DELETE_FAILED < FAILED < REMOVED < SPACE_ERROR."""
        terminal = [
            FileStatus.COMPLETED,
            FileStatus.COMPLETED_DELETE_FAILED,
            FileStatus.FAILED,
            FileStatus.REMOVED,
            FileStatus.SPACE_ERROR,
        ]
        files = [_make_file(status=s) for s in terminal]
        priorities = [FileSelectionLogic.all_sort_key(f)[0] for f in files]
        assert priorities == sorted(priorities)


class TestSelectActiveForPath:
    def test_returns_highest_priority_active(self):
        files = [
            _make_file("/a.mxf", FileStatus.DISCOVERED),
            _make_file("/a.mxf", FileStatus.COPYING),
            _make_file("/a.mxf", FileStatus.READY),
        ]
        result = FileSelectionLogic.select_active_for_path(files, "/a.mxf")
        assert result is not None
        assert result.status == FileStatus.COPYING

    def test_returns_none_when_all_terminal(self):
        files = [
            _make_file("/a.mxf", FileStatus.COMPLETED),
            _make_file("/a.mxf", FileStatus.FAILED),
        ]
        result = FileSelectionLogic.select_active_for_path(files, "/a.mxf")
        assert result is None

    def test_returns_none_when_no_match(self):
        files = [_make_file("/b.mxf", FileStatus.COPYING)]
        result = FileSelectionLogic.select_active_for_path(files, "/a.mxf")
        assert result is None

    def test_filters_by_path(self):
        files = [
            _make_file("/a.mxf", FileStatus.DISCOVERED),
            _make_file("/b.mxf", FileStatus.COPYING),
        ]
        result = FileSelectionLogic.select_active_for_path(files, "/a.mxf")
        assert result is not None
        assert result.file_path == "/a.mxf"
        assert result.status == FileStatus.DISCOVERED

    def test_empty_list_returns_none(self):
        assert FileSelectionLogic.select_active_for_path([], "/a.mxf") is None


class TestSelectCurrentForPath:
    def test_includes_terminal_states(self):
        files = [
            _make_file("/a.mxf", FileStatus.COMPLETED),
            _make_file("/a.mxf", FileStatus.FAILED),
        ]
        result = FileSelectionLogic.select_current_for_path(files, "/a.mxf")
        assert result is not None
        assert result.status == FileStatus.COMPLETED

    def test_active_beats_terminal(self):
        files = [
            _make_file("/a.mxf", FileStatus.COMPLETED),
            _make_file("/a.mxf", FileStatus.READY),
        ]
        result = FileSelectionLogic.select_current_for_path(files, "/a.mxf")
        assert result is not None
        assert result.status == FileStatus.READY


class TestIsMoreCurrent:
    def test_copying_beats_discovered(self):
        a = _make_file(status=FileStatus.COPYING)
        b = _make_file(status=FileStatus.DISCOVERED)
        assert FileSelectionLogic.is_more_current(a, b) is True
        assert FileSelectionLogic.is_more_current(b, a) is False

    def test_same_status_newer_wins(self):
        a = _make_file(status=FileStatus.READY, discovered_at=datetime(2025, 1, 2))
        b = _make_file(status=FileStatus.READY, discovered_at=datetime(2025, 1, 1))
        assert FileSelectionLogic.is_more_current(a, b) is True

    def test_same_file_returns_false(self):
        a = _make_file(status=FileStatus.READY)
        assert FileSelectionLogic.is_more_current(a, a) is False


class TestDeduplicateByPath:
    def test_keeps_highest_priority_per_path(self):
        files = [
            _make_file("/a.mxf", FileStatus.DISCOVERED),
            _make_file("/a.mxf", FileStatus.COPYING),
            _make_file("/b.mxf", FileStatus.READY),
            _make_file("/b.mxf", FileStatus.COMPLETED),
        ]
        result = FileSelectionLogic.deduplicate_by_path(files)
        assert len(result) == 2
        assert result["/a.mxf"].status == FileStatus.COPYING
        assert result["/b.mxf"].status == FileStatus.READY

    def test_empty_list(self):
        assert FileSelectionLogic.deduplicate_by_path([]) == {}

    def test_single_file(self):
        f = _make_file("/a.mxf", FileStatus.DISCOVERED)
        result = FileSelectionLogic.deduplicate_by_path([f])
        assert result["/a.mxf"] is f
