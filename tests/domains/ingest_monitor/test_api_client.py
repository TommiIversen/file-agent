"""Tests for IngestApiClient — HTTP communication with Just In Engine API."""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.ingest_monitor.api_client import IngestApiClient


def _settings():
    s = MagicMock()
    s.justin_api_base_url = "http://10.0.0.1:8080"
    s.justin_api_timeout_seconds = 5.0
    return s


def _mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


@pytest.fixture
def client():
    with patch("app.domains.ingest_monitor.api_client.httpx.AsyncClient"):
        c = IngestApiClient(_settings())
    c._client = AsyncMock(spec=httpx.AsyncClient)
    return c


# ── get_active_channels ─────────────────────────────────────────

class TestGetActiveChannels:
    @pytest.mark.asyncio
    async def test_returns_channel_names(self, client):
        client._client.get.return_value = _mock_response(
            {"channel-names": ["KAM_1", "KAM_2"]}
        )
        result = await client.get_active_channels()
        assert result == ["KAM_1", "KAM_2"]

    @pytest.mark.asyncio
    async def test_request_error_returns_none(self, client):
        client._client.get.side_effect = httpx.RequestError("timeout")
        result = await client.get_active_channels()
        assert result is None

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_none(self, client):
        client._client.get.side_effect = RuntimeError("unexpected")
        result = await client.get_active_channels()
        assert result is None


# ── get_channel_status ───────────────────────────────────────────

class TestGetChannelStatus:
    @pytest.mark.asyncio
    async def test_returns_recording_status(self, client):
        client._client.post.return_value = _mock_response({
            "rec": True,
            "frames": 100,
            "channel": "KAM_1",
            "hours": 0,
            "seconds": 10,
            "minutes": 5,
            "name": "KAM_1",
            "options": {"TOAJustInEngineVideoSignalAvailable": True},
        })
        result = await client.get_channel_status("KAM_1")
        assert result is not None
        assert result.rec is True
        assert result.channel == "KAM_1"

    @pytest.mark.asyncio
    async def test_request_error_returns_none(self, client):
        client._client.post.side_effect = httpx.RequestError("timeout")
        result = await client.get_channel_status("KAM_1")
        assert result is None


# ── get_channel_errors ───────────────────────────────────────────

class TestGetChannelErrors:
    @pytest.mark.asyncio
    async def test_returns_errors(self, client):
        client._client.post.return_value = _mock_response({
            "channel": "KAM_1",
            "name": "KAM_1",
            "errors": [
                {
                    "date": 1700000000.0,
                    "errorCode": 42,
                    "errorUIDescription": "Signal lost",
                }
            ],
        })
        result = await client.get_channel_errors("KAM_1")
        assert len(result) == 1
        assert result[0].errorCode == 42

    @pytest.mark.asyncio
    async def test_request_error_returns_empty(self, client):
        client._client.post.side_effect = httpx.RequestError("timeout")
        result = await client.get_channel_errors("KAM_1")
        assert result == []

    @pytest.mark.asyncio
    async def test_clear_flag_sent(self, client):
        client._client.post.return_value = _mock_response({
            "channel": "KAM_1", "name": "KAM_1", "errors": []
        })
        await client.get_channel_errors("KAM_1", clear=True)
        call_kwargs = client._client.post.call_args[1]
        assert call_kwargs["json"]["clear"] == 1


# ── get_all_channel_statuses ─────────────────────────────────────

class TestGetAllChannelStatuses:
    @pytest.mark.asyncio
    async def test_returns_successful_statuses(self, client):
        client._client.post.return_value = _mock_response({
            "rec": True, "frames": 0, "channel": "KAM_1",
            "hours": 0, "seconds": 0, "minutes": 0, "name": "KAM_1",
            "options": {},
        })
        result = await client.get_all_channel_statuses(["KAM_1"])
        assert result is not None
        assert len(result) == 1
        assert result[0][0] == "KAM_1"

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self, client):
        result = await client.get_all_channel_statuses([])
        assert result == []

    @pytest.mark.asyncio
    async def test_all_failures_returns_none(self, client):
        client._client.post.side_effect = httpx.RequestError("down")
        result = await client.get_all_channel_statuses(["KAM_1"])
        assert result is None


# ── start_channel / stop_channel ─────────────────────────────────

class TestStartStopChannel:
    @pytest.mark.asyncio
    async def test_start_success(self, client):
        client._client.post.return_value = _mock_response({})
        result = await client.start_channel("KAM_1")
        assert result is True

    @pytest.mark.asyncio
    async def test_start_failure(self, client):
        client._client.post.side_effect = httpx.RequestError("timeout")
        result = await client.start_channel("KAM_1")
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_success(self, client):
        client._client.post.return_value = _mock_response({})
        result = await client.stop_channel("KAM_1")
        assert result is True

    @pytest.mark.asyncio
    async def test_stop_failure(self, client):
        client._client.post.side_effect = httpx.RequestError("timeout")
        result = await client.stop_channel("KAM_1")
        assert result is False


# ── start_all_channels / stop_all_channels ───────────────────────

class TestBulkOperations:
    @pytest.mark.asyncio
    async def test_start_all_channels(self, client):
        client._client.post.return_value = _mock_response({})
        result = await client.start_all_channels(["KAM_1", "KAM_2"])
        assert result == 2

    @pytest.mark.asyncio
    async def test_start_all_empty(self, client):
        result = await client.start_all_channels([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_stop_all_channels(self, client):
        client._client.post.return_value = _mock_response({})
        result = await client.stop_all_channels(["KAM_1", "KAM_2"])
        assert result == 2

    @pytest.mark.asyncio
    async def test_clear_all_errors(self, client):
        client._client.post.return_value = _mock_response({
            "channel": "KAM_1", "name": "KAM_1", "errors": []
        })
        result = await client.clear_all_channel_errors(["KAM_1"])
        assert result == 1

    @pytest.mark.asyncio
    async def test_clear_all_errors_empty(self, client):
        result = await client.clear_all_channel_errors([])
        assert result == 0


# ── discover_recording_paths (3-step flow) ───────────────────────

class TestDiscoverRecordingPaths:
    @pytest.mark.asyncio
    async def test_full_discovery_flow(self, client):
        # Step 1: recordingConfiguration
        config_resp = _mock_response({
            "channel": "KAM_1", "name": "KAM_1",
            "configurations": [{"destinationPreset": "Default", "capturePreset": "HD"}],
        })
        # Step 2: requestDestinationPresets
        presets_resp = _mock_response({
            "channel": "KAM_1", "name": "KAM_1",
            "preset": ["Default", "Backup"],
        })
        # Step 3: requestLoadDestinationPreset
        loaded_resp = _mock_response({
            "destination-preset-id": 0,
            "channel": "KAM_1", "name": "KAM_1",
            "justin-destination-preset": {
                "name": "Default",
                "destination-path": [{"path": "/recordings/KAM_1"}],
            },
        })

        client._client.post.side_effect = [config_resp, presets_resp, loaded_resp]

        result = await client.discover_recording_paths("KAM_1")
        assert result is not None
        paths, preset_name = result
        assert paths == ["/recordings/KAM_1"]
        assert preset_name == "Default"

    @pytest.mark.asyncio
    async def test_no_recording_config_returns_none(self, client):
        client._client.post.side_effect = httpx.RequestError("timeout")
        result = await client.discover_recording_paths("KAM_1")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_preset_configured_returns_none(self, client):
        config_resp = _mock_response({
            "channel": "KAM_1", "name": "KAM_1",
            "configurations": [{"destinationPreset": "-", "capturePreset": "HD"}],
        })
        client._client.post.return_value = config_resp
        result = await client.discover_recording_paths("KAM_1")
        assert result is None

    @pytest.mark.asyncio
    async def test_preset_not_found_in_list_returns_none(self, client):
        config_resp = _mock_response({
            "channel": "KAM_1", "name": "KAM_1",
            "configurations": [{"destinationPreset": "Missing", "capturePreset": "HD"}],
        })
        presets_resp = _mock_response({
            "channel": "KAM_1", "name": "KAM_1",
            "preset": ["Default", "Backup"],
        })
        client._client.post.side_effect = [config_resp, presets_resp]
        result = await client.discover_recording_paths("KAM_1")
        assert result is None


# ── close / aclose ───────────────────────────────────────────────

class TestCleanup:
    @pytest.mark.asyncio
    async def test_aclose(self, client):
        await client.aclose()
        client._client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_alias(self, client):
        await client.close()
        client._client.aclose.assert_awaited_once()
