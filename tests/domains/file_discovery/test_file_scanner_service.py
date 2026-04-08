"""Tests for FileScannerService — CQRS adapter around FileScanner."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.file_discovery.file_scanner_service import FileScannerService
from app.core.events.scanner_events import ScannerStatusChangedEvent


def _make_settings():
    s = MagicMock()
    s.source_directory = "/src"
    s.polling_interval_seconds = 5
    s.file_stable_time_seconds = 10
    s.keep_files_hours = 24
    s.growing_file_poll_interval_seconds = 5
    s.growing_file_safety_margin_mb = 50
    s.growing_file_growth_timeout_seconds = 300
    s.growing_file_chunk_size_kb = 1024
    return s


@pytest.fixture
def deps():
    return {
        "settings": _make_settings(),
        "command_bus": MagicMock(),
        "query_bus": MagicMock(),
        "event_bus": AsyncMock(),
    }


@pytest.fixture
def service(deps):
    with patch("app.domains.file_discovery.file_scanner_service.FileScanner") as MockScanner:
        mock_scanner = AsyncMock()
        mock_scanner.is_scanning.return_value = False
        MockScanner.return_value = mock_scanner
        svc = FileScannerService(**deps)
        svc._mock_scanner = mock_scanner  # Stash for assertions
    return svc


class TestStartScanning:
    @pytest.mark.asyncio
    async def test_publishes_scanner_event_and_delegates(self, service, deps):
        await service.start_scanning()

        # Should publish ScannerStatusChangedEvent
        deps["event_bus"].publish.assert_called_once()
        event = deps["event_bus"].publish.call_args[0][0]
        assert isinstance(event, ScannerStatusChangedEvent)
        assert event.is_scanning is True
        assert event.is_paused is False

        # Should delegate to file scanner
        service._mock_scanner.start_scanning.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_scanning_without_event_bus(self, deps):
        deps["event_bus"] = None
        with patch("app.domains.file_discovery.file_scanner_service.FileScanner") as MockScanner:
            mock_scanner = AsyncMock()
            MockScanner.return_value = mock_scanner
            svc = FileScannerService(**deps)
            await svc.start_scanning()
            mock_scanner.start_scanning.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_scanning_event_publish_failure_continues(self, service, deps):
        deps["event_bus"].publish.side_effect = RuntimeError("bus error")
        # Should not raise — warning logged, scanning still starts
        await service.start_scanning()
        service._mock_scanner.start_scanning.assert_awaited_once()


class TestStopScanning:
    @pytest.mark.asyncio
    async def test_publishes_stopped_event_and_delegates(self, service, deps):
        await service.stop_scanning()

        service._mock_scanner.stop_scanning.assert_awaited_once()
        deps["event_bus"].publish.assert_called_once()
        event = deps["event_bus"].publish.call_args[0][0]
        assert isinstance(event, ScannerStatusChangedEvent)
        assert event.is_scanning is False
        assert event.is_paused is True

    @pytest.mark.asyncio
    async def test_stop_scanning_event_publish_failure_continues(self, service, deps):
        deps["event_bus"].publish.side_effect = RuntimeError("bus error")
        await service.stop_scanning()
        service._mock_scanner.stop_scanning.assert_awaited_once()


class TestIsScanning:
    def test_delegates_to_file_scanner(self, service):
        service._file_scanner.is_scanning = MagicMock(return_value=True)
        assert service.is_scanning() is True
