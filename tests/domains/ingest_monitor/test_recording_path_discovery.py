"""
Tests for Just In Engine recording path discovery feature.

Covers:
- New Pydantic models for recording configuration & destination presets
- API client 3-step discovery flow (mocked httpx)
- StateService recording-path caching + change detection + event publishing
- RecordingPathsDiscoveredEvent structure
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.domains.ingest_monitor.api_client import IngestApiClient
from app.domains.ingest_monitor.state_service import IngestStateService
from app.domains.ingest_monitor.events import RecordingPathsDiscoveredEvent
from app.domains.ingest_monitor.models import (
    JustInConfigurationEntry,
    JustInRecordingConfiguration,
    JustInDestinationPresets,
    JustInDestinationPath,
    JustInDestinationPresetDetail,
    JustInLoadDestinationPresetResponse,
)


# ── Model tests ─────────────────────────────────────────────────────────────


class TestRecordingConfigurationModels:
    def test_configuration_entry(self):
        entry = JustInConfigurationEntry(
            destinationPreset="Default", capturePreset="HD 1080i"
        )
        assert entry.destinationPreset == "Default"
        assert entry.capturePreset == "HD 1080i"

    def test_recording_configuration(self):
        cfg = JustInRecordingConfiguration(
            channel="KAM_1",
            name="KAM 1",
            configurations=[
                JustInConfigurationEntry(
                    destinationPreset="Default", capturePreset="ProRes 422"
                )
            ],
        )
        assert cfg.channel == "KAM_1"
        assert len(cfg.configurations) == 1
        assert cfg.configurations[0].destinationPreset == "Default"

    def test_recording_configuration_empty_configs(self):
        cfg = JustInRecordingConfiguration(channel="X", name="X")
        assert cfg.configurations == []

    def test_destination_presets(self):
        dp = JustInDestinationPresets(
            channel="KAM_1",
            name="KAM 1",
            preset=["Default", "Backup", "External"],
        )
        assert dp.preset == ["Default", "Backup", "External"]
        assert dp.preset.index("Default") == 0

    def test_destination_path_with_aliases(self):
        """Test that hyphenated JSON keys are handled via aliases."""
        raw = {
            "path": "/Volumes/NLE-External",
            "redundancy-type": 0,
            "container-type": 2,
            "file-buffer-size": 4096,
            "path-type": 1,
        }
        dp = JustInDestinationPath.model_validate(raw)
        assert dp.path == "/Volumes/NLE-External"
        assert dp.redundancy_type == 0
        assert dp.container_type == 2
        assert dp.file_buffer_size == 4096
        assert dp.path_type == 1

    def test_destination_path_python_names(self):
        """Test creation with Python-style attribute names (populate_by_name)."""
        dp = JustInDestinationPath(
            path="/mnt/storage",
            redundancy_type=1,
            container_type=3,
            file_buffer_size=8192,
            path_type=0,
        )
        assert dp.path == "/mnt/storage"

    def test_preset_detail_with_alias(self):
        raw = {
            "name": "Default",
            "destination-path": [
                {"path": "/Volumes/A", "redundancy-type": 0, "container-type": 2,
                 "file-buffer-size": 4096, "path-type": 1},
                {"path": "/Volumes/B", "redundancy-type": 0, "container-type": 2,
                 "file-buffer-size": 4096, "path-type": 0},
            ],
        }
        detail = JustInDestinationPresetDetail.model_validate(raw)
        assert detail.name == "Default"
        assert len(detail.destination_path) == 2
        assert detail.destination_path[0].path == "/Volumes/A"
        assert detail.destination_path[1].path == "/Volumes/B"

    def test_load_destination_preset_response(self):
        raw = {
            "destination-preset-id": 0,
            "channel": "KAM_1",
            "name": "KAM 1",
            "justin-destination-preset": {
                "name": "Default",
                "destination-path": [
                    {"path": "/Volumes/NLE-External", "redundancy-type": 0,
                     "container-type": 2, "file-buffer-size": 4096, "path-type": 1},
                ],
            },
        }
        resp = JustInLoadDestinationPresetResponse.model_validate(raw)
        assert resp.destination_preset_id == 0
        assert resp.channel == "KAM_1"
        preset = resp.justin_destination_preset
        assert preset.name == "Default"
        assert len(preset.destination_path) == 1
        assert preset.destination_path[0].path == "/Volumes/NLE-External"


# ── RecordingPathsDiscoveredEvent tests ──────────────────────────────────────


class TestRecordingPathsDiscoveredEvent:
    def test_event_creation(self):
        evt = RecordingPathsDiscoveredEvent(
            paths=("/Volumes/A", "/Volumes/B"),
            preset_name="Default",
            channel_name="KAM_1",
        )
        assert evt.paths == ("/Volumes/A", "/Volumes/B")
        assert evt.preset_name == "Default"
        assert evt.channel_name == "KAM_1"

    def test_event_is_frozen(self):
        evt = RecordingPathsDiscoveredEvent(
            paths=("/X",), preset_name="P", channel_name="C"
        )
        with pytest.raises(AttributeError):
            evt.paths = ("/Y",)

    def test_event_defaults(self):
        evt = RecordingPathsDiscoveredEvent(paths=())
        assert evt.preset_name == ""
        assert evt.channel_name == ""


# ── StateService recording-path cache tests ──────────────────────────────────


class TestStateServiceRecordingPaths:
    @pytest.fixture
    def event_bus(self):
        bus = DomainEventBus()
        return bus

    @pytest.fixture
    def state_service(self, event_bus):
        return IngestStateService(event_bus)

    async def test_initial_recording_paths_empty(self, state_service):
        assert state_service.get_recording_paths() == {}

    async def test_update_recording_paths_publishes_event(self, state_service, event_bus):
        received = []
        await event_bus.subscribe(
            RecordingPathsDiscoveredEvent, lambda e: received.append(e)
        )
        changed = await state_service.update_recording_paths(
            channel_name="KAM_1",
            paths=["/Volumes/NLE"],
            preset_name="Default",
        )
        assert changed is True
        assert len(received) == 1
        evt = received[0]
        assert evt.paths == ("/Volumes/NLE",)
        assert evt.preset_name == "Default"
        assert evt.channel_name == "KAM_1"

    async def test_update_same_paths_no_event(self, state_service, event_bus):
        received = []
        await event_bus.subscribe(
            RecordingPathsDiscoveredEvent, lambda e: received.append(e)
        )
        await state_service.update_recording_paths("KAM_1", ["/Volumes/A"], "Default")
        assert len(received) == 1

        changed = await state_service.update_recording_paths("KAM_1", ["/Volumes/A"], "Default")
        assert changed is False
        assert len(received) == 1  # no duplicate

    async def test_update_paths_change_triggers_event(self, state_service, event_bus):
        received = []
        await event_bus.subscribe(
            RecordingPathsDiscoveredEvent, lambda e: received.append(e)
        )
        await state_service.update_recording_paths("KAM_1", ["/Volumes/A"], "Default")
        await state_service.update_recording_paths("KAM_1", ["/Volumes/B"], "Default")
        assert len(received) == 2
        assert received[1].paths == ("/Volumes/B",)

    async def test_update_preset_change_triggers_event(self, state_service, event_bus):
        received = []
        await event_bus.subscribe(
            RecordingPathsDiscoveredEvent, lambda e: received.append(e)
        )
        await state_service.update_recording_paths("KAM_1", ["/Volumes/A"], "Default")
        await state_service.update_recording_paths("KAM_1", ["/Volumes/A"], "Backup")
        assert len(received) == 2
        assert received[1].preset_name == "Backup"

    async def test_get_recording_paths_snapshot(self, state_service):
        await state_service.update_recording_paths("KAM_1", ["/A", "/B"], "Default")
        await state_service.update_recording_paths("KAM_2", ["/C"], "Ext")

        snap = state_service.get_recording_paths()
        assert snap == {
            "KAM_1": {"preset_name": "Default", "paths": ["/A", "/B"]},
            "KAM_2": {"preset_name": "Ext", "paths": ["/C"]},
        }

    async def test_clear_cache_resets_recording_paths(self, state_service):
        await state_service.update_recording_paths("KAM_1", ["/A"], "P")
        state_service.clear_cache()
        assert state_service.get_recording_paths() == {}

    async def test_multiple_channels(self, state_service, event_bus):
        received = []
        await event_bus.subscribe(
            RecordingPathsDiscoveredEvent, lambda e: received.append(e)
        )
        await state_service.update_recording_paths("KAM_1", ["/A"], "P1")
        await state_service.update_recording_paths("KAM_2", ["/B"], "P2")
        assert len(received) == 2
        assert {e.channel_name for e in received} == {"KAM_1", "KAM_2"}


# ── API Client discover_recording_paths tests (mocked HTTP) ─────────────────


def _make_mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.is_success = status_code < 400
    return resp


class TestApiClientDiscoverRecordingPaths:
    @pytest.fixture
    def settings(self):
        s = Settings()
        s.justin_api_base_url = "http://test:8080"
        s.justin_api_timeout_seconds = 1.0
        return s

    @pytest.fixture
    def api_client(self, settings):
        with patch("app.domains.ingest_monitor.api_client.httpx.AsyncClient"):
            client = IngestApiClient(settings)
        return client

    async def test_full_discovery_flow(self, api_client):
        """Happy path: 3-step flow returns paths and preset name."""
        step1_resp = _make_mock_response({
            "channel": "KAM_1", "name": "KAM 1",
            "configurations": [{"destinationPreset": "Default", "capturePreset": "X"}]
        })
        step2_resp = _make_mock_response({
            "channel": "KAM_1", "name": "KAM 1",
            "preset": ["Default", "Backup"]
        })
        step3_resp = _make_mock_response({
            "destination-preset-id": 0, "channel": "KAM_1", "name": "KAM 1",
            "justin-destination-preset": {
                "name": "Default",
                "destination-path": [
                    {"path": "/Volumes/NLE", "redundancy-type": 0, "container-type": 2,
                     "file-buffer-size": 4096, "path-type": 1}
                ],
            },
        })

        api_client._client = AsyncMock()
        api_client._client.post = AsyncMock(side_effect=[step1_resp, step2_resp, step3_resp])

        result = await api_client.discover_recording_paths("KAM_1")
        assert result is not None
        paths, preset_name = result
        assert paths == ["/Volumes/NLE"]
        assert preset_name == "Default"

    async def test_discovery_no_config(self, api_client):
        """Step 1 returns empty configurations -> None."""
        step1_resp = _make_mock_response({
            "channel": "KAM_1", "name": "KAM 1", "configurations": []
        })
        api_client._client = AsyncMock()
        api_client._client.post = AsyncMock(return_value=step1_resp)

        result = await api_client.discover_recording_paths("KAM_1")
        assert result is None

    async def test_discovery_preset_not_in_list(self, api_client):
        """Step 2 does not contain the preset from step 1 -> None."""
        step1_resp = _make_mock_response({
            "channel": "KAM_1", "name": "KAM 1",
            "configurations": [{"destinationPreset": "Missing", "capturePreset": ""}]
        })
        step2_resp = _make_mock_response({
            "channel": "KAM_1", "name": "KAM 1",
            "preset": ["Default", "Backup"]
        })
        api_client._client = AsyncMock()
        api_client._client.post = AsyncMock(side_effect=[step1_resp, step2_resp])

        result = await api_client.discover_recording_paths("KAM_1")
        assert result is None

    async def test_discovery_no_destination_paths(self, api_client):
        """Step 3 returns preset with empty destination-path list -> None."""
        step1_resp = _make_mock_response({
            "channel": "KAM_1", "name": "KAM 1",
            "configurations": [{"destinationPreset": "Default", "capturePreset": ""}]
        })
        step2_resp = _make_mock_response({
            "channel": "KAM_1", "name": "KAM 1",
            "preset": ["Default"]
        })
        step3_resp = _make_mock_response({
            "destination-preset-id": 0, "channel": "KAM_1", "name": "KAM 1",
            "justin-destination-preset": {"name": "Default", "destination-path": []},
        })
        api_client._client = AsyncMock()
        api_client._client.post = AsyncMock(side_effect=[step1_resp, step2_resp, step3_resp])

        result = await api_client.discover_recording_paths("KAM_1")
        assert result is None

    async def test_discovery_multiple_paths(self, api_client):
        """Preset with two destination paths returns both."""
        step1_resp = _make_mock_response({
            "channel": "KAM_1", "name": "KAM 1",
            "configurations": [{"destinationPreset": "Dual", "capturePreset": ""}]
        })
        step2_resp = _make_mock_response({
            "channel": "KAM_1", "name": "KAM 1",
            "preset": ["Dual"]
        })
        step3_resp = _make_mock_response({
            "destination-preset-id": 0, "channel": "KAM_1", "name": "KAM 1",
            "justin-destination-preset": {
                "name": "Dual",
                "destination-path": [
                    {"path": "/Volumes/A", "redundancy-type": 0, "container-type": 2,
                     "file-buffer-size": 4096, "path-type": 1},
                    {"path": "/Volumes/B", "redundancy-type": 0, "container-type": 2,
                     "file-buffer-size": 4096, "path-type": 0},
                ],
            },
        })
        api_client._client = AsyncMock()
        api_client._client.post = AsyncMock(side_effect=[step1_resp, step2_resp, step3_resp])

        result = await api_client.discover_recording_paths("KAM_1")
        assert result is not None
        paths, preset_name = result
        assert paths == ["/Volumes/A", "/Volumes/B"]
        assert preset_name == "Dual"

    async def test_discovery_preset_dash_returns_none(self, api_client):
        """Preset name '-' means not configured -> None."""
        step1_resp = _make_mock_response({
            "channel": "KAM_1", "name": "KAM 1",
            "configurations": [{"destinationPreset": "-", "capturePreset": ""}]
        })
        api_client._client = AsyncMock()
        api_client._client.post = AsyncMock(return_value=step1_resp)

        result = await api_client.discover_recording_paths("KAM_1")
        assert result is None

    async def test_discovery_step1_http_error(self, api_client):
        """HTTP error on step 1 -> None."""
        error_resp = _make_mock_response({}, status_code=500)
        api_client._client = AsyncMock()
        api_client._client.post = AsyncMock(return_value=error_resp)

        result = await api_client.discover_recording_paths("KAM_1")
        assert result is None
