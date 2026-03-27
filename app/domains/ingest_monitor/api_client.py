"""
Ingest API Client

Håndterer al direkte HTTP-kommunikation med Just In Engine API'en.
Denne klasse er ansvarlig for at abstraktere httpx-kommunikation og
validere API-svar med Pydantic-modeller.
"""
import asyncio
import logging
import httpx
from typing import List, Optional, Tuple
from app.config import Settings
from .models import (
    JustInActiveChannels,
    JustInRecordingStatus,
    JustInErrors,
    JustInError,
    JustInRecordingConfiguration,
    JustInDestinationPresets,
    JustInLoadDestinationPresetResponse,
)


class IngestApiClient:
    """
    Håndterer al direkte HTTP-kommunikation med Just In Engine API'en.
    
    Denne klasse følger Single Responsibility Principle ved udelukkende
    at fokusere på API-kommunikation og data-validering.
    """

    def __init__(self, settings: Settings):
        """Initialize HTTP client with base URL and timeout from settings."""
        self._client = httpx.AsyncClient(
            base_url=settings.justin_api_base_url, 
            timeout=settings.justin_api_timeout_seconds
        )
        logging.debug(f"IngestApiClient initialized with base_url: {settings.justin_api_base_url}")

    async def aclose(self) -> None:
        """Cleanup HTTP client resources."""
        await self._client.aclose()
        logging.debug("IngestApiClient HTTP client closed")

    async def close(self) -> None:
        """Alias for aclose for convenience."""
        await self.aclose()

    async def get_active_channels(self) -> Optional[List[str]]:
        """
        Henter den aktive kanalliste fra Just In Engine.
        
        Returns:
            Optional[List[str]]: Liste af aktive kanalnavne eller None ved fejl.
        """
        try:
            response = await self._client.get("/ingest/activeChannels")
            response.raise_for_status()
            data = JustInActiveChannels.model_validate(response.json())
            logging.debug(f"Retrieved {len(data.channel_names)} active channels: {data.channel_names}")
            return data.channel_names
        except httpx.RequestError as e:
            logging.warning(f"Could not fetch activeChannels: {e}")
            return None # Return None on error to indicate API failure
        except Exception as e:
            logging.error(f"Unexpected error fetching activeChannels: {e}")
            return None

    async def get_channel_status(self, channel_name: str) -> Optional[JustInRecordingStatus]:
        """
        Henter recording status for én enkelt kanal.
        
        Args:
            channel_name (str): Navnet på kanalen at hente status for
            
        Returns:
            Optional[JustInRecordingStatus]: Recording status eller None ved fejl
        """
        try:
            payload = {"channel": channel_name}
            response = await self._client.post("/ingest/requestRecordingStatus", json=payload)
            response.raise_for_status()
            status_data = JustInRecordingStatus.model_validate(response.json())
            logging.debug(f"Retrieved status for {channel_name}: recording={status_data.rec}")
            return status_data
        except httpx.RequestError as e:
            logging.warning(f"Could not fetch status for {channel_name}: {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error fetching status for {channel_name}: {e}")
            return None

    async def get_channel_errors(self, channel_name: str, clear: bool = False) -> List[JustInError]:
        """
        Henter fejl for én enkelt kanal med mulighed for at cleare dem.
        
        Args:
            channel_name (str): Navnet på kanalen at hente fejl for
            clear (bool): Om fejlene skal cleares (default: False)
            
        Returns:
            List[JustInError]: Liste af fejl. Returnerer tom liste ved fejl.
        """
        try:
            payload = {"channel": channel_name, "clear": 1 if clear else 0}
            response = await self._client.post("/ingest/errors", json=payload)
            response.raise_for_status()
            data = JustInErrors.model_validate(response.json())
            
            if clear:
                logging.info(f"Cleared errors for {channel_name}")
            else:
                logging.debug(f"Retrieved {len(data.errors)} errors for {channel_name}")
            return data.errors
        except httpx.RequestError as e:
            logging.warning(f"Could not fetch errors for {channel_name}: {e}")
            return []
        except Exception as e:
            logging.error(f"Unexpected error fetching errors for {channel_name}: {e}")
            return []

    async def get_all_channel_statuses(self, channel_names: List[str]) -> Optional[List[Tuple[str, JustInRecordingStatus]]]:
        """
        Fetch recording status for multiple channels in parallel.
        
        Used by the fast polling loop to efficiently update all channel statuses.
        
        Args:
            channel_names: List of channel names to fetch status for
            
        Returns:
            Optional[List]: List of (channel_name, status_data) tuples for successful fetches,
                          or None if API calls are failing (indicating connection issues)
        """
        if not channel_names:
            return [] # Empty input is valid, return empty list

        logging.debug(f"Fetching status for {len(channel_names)} channels: {channel_names}")

        async def fetch_single(name: str) -> Optional[Tuple[str, JustInRecordingStatus]]:
            status = await self.get_channel_status(name)
            return (name, status) if status else None

        # Fetch all statuses in parallel
        tasks = [fetch_single(name) for name in channel_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out None results and exceptions
        successful_results: list[tuple[str, JustInRecordingStatus]] = [
            result for result in results 
            if result is not None and not isinstance(result, BaseException)
        ]
        
        # If we got no successful results and we had channels to check, API might be down
        if len(channel_names) > 0 and len(successful_results) == 0:
            logging.warning(f"Failed to fetch status for all {len(channel_names)} channels - API might be down")
            return None # Indicates API connection failure
        
        logging.debug(f"Successfully fetched status for {len(successful_results)}/{len(channel_names)} channels")
        return successful_results

    async def get_all_channel_errors(self, channel_names: List[str]) -> List[Tuple[str, List[JustInError]]]:
        """
        Fetch errors for multiple channels in parallel.
        
        Used by the slow polling loop to check for errors on all channels.
        
        Args:
            channel_names: List of channel names to fetch errors for
            
        Returns:
            List of (channel_name, errors_list) tuples for all channels
        """
        if not channel_names:
            return []

        logging.debug(f"Fetching errors for {len(channel_names)} channels")

        async def fetch_single(name: str) -> Tuple[str, List[JustInError]]:
            errors = await self.get_channel_errors(name)
            return (name, errors)

        # Fetch all errors in parallel
        tasks = [fetch_single(name) for name in channel_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions, keep empty error lists
        successful_results: list[tuple[str, list[JustInError]]] = [
            result for result in results 
            if not isinstance(result, BaseException)
        ]
        
        logging.debug(f"Successfully fetched errors for {len(successful_results)}/{len(channel_names)} channels")
        return successful_results

    async def start_channel(self, channel_name: str) -> bool:
        """
        Start a single channel.
        
        Args:
            channel_name (str): Name of channel to start
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            payload = {
                "channel": channel_name,
                "proposed-filename": "",
                "metadata": {
                    "toa-just-in-engine-alternative-start-timecode-frames": 0,
                    "tal-ingest-engine-override-naming-preset": 0,
                    "toa-just-in-engine-alternative-start-timecode-active": 0
                }
            }
            response = await self._client.post("/ingest/startRecordingWithFilename", json=payload)
            response.raise_for_status()
            logging.info(f"Successfully started channel {channel_name}")
            return True
        except httpx.RequestError as e:
            logging.warning(f"Could not start channel {channel_name}: {e}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error starting channel {channel_name}: {e}")
            return False

    async def stop_channel(self, channel_name: str) -> bool:
        """
        Stop a single channel.
        
        Args:
            channel_name (str): Name of channel to stop
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            payload = {
                "channel": channel_name,
                "metadata": {
                    "toa-just-in-engine-alternative-stop-timecode-active": 0,
                    "toa-just-in-engine-alternative-stop-timecode-frames": 0
                }
            }
            response = await self._client.post("/ingest/stopRecording", json=payload)
            response.raise_for_status()
            logging.info(f"Successfully stopped channel {channel_name}")
            return True
        except httpx.RequestError as e:
            logging.warning(f"Could not stop channel {channel_name}: {e}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error stopping channel {channel_name}: {e}")
            return False

    async def start_all_channels(self, channel_names: List[str]) -> int:
        """
        Start multiple channels in parallel.
        
        Used to bulk start all channels.
        
        Args:
            channel_names: List of channel names to start
            
        Returns:
            int: Number of channels successfully started
        """
        if not channel_names:
            return 0

        logging.info(f"Starting {len(channel_names)} channels: {channel_names}")

        async def start_single(name: str) -> bool:
            return await self.start_channel(name)

        # Start all channels in parallel
        tasks = [start_single(name) for name in channel_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count successful starts
        successful_starts = sum(
            1 for result in results 
            if result is True and not isinstance(result, Exception)
        )
        
        logging.info(f"Successfully started {successful_starts}/{len(channel_names)} channels")
        return successful_starts

    async def stop_all_channels(self, channel_names: List[str]) -> int:
        """
        Stop multiple channels in parallel.
        
        Used to bulk stop all channels.
        
        Args:
            channel_names: List of channel names to stop
            
        Returns:
            int: Number of channels successfully stopped
        """
        if not channel_names:
            return 0

        logging.info(f"Stopping {len(channel_names)} channels: {channel_names}")

        async def stop_single(name: str) -> bool:
            return await self.stop_channel(name)

        # Stop all channels in parallel
        tasks = [stop_single(name) for name in channel_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count successful stops
        successful_stops = sum(
            1 for result in results 
            if result is True and not isinstance(result, Exception)
        )
        
        logging.info(f"Successfully stopped {successful_stops}/{len(channel_names)} channels")
        return successful_stops

    async def clear_all_channel_errors(self, channel_names: List[str]) -> int:
        """
        Clear errors for multiple channels in parallel.
        
        Used to bulk clear errors across all channels.
        
        Args:
            channel_names: List of channel names to clear errors for
            
        Returns:
            int: Number of channels successfully cleared
        """
        if not channel_names:
            return 0

        logging.info(f"Clearing errors for {len(channel_names)} channels: {channel_names}")

        async def clear_single(name: str) -> bool:
            try:
                await self.get_channel_errors(name, clear=True)
                return True
            except Exception as e:
                logging.error(f"Failed to clear errors for {name}: {e}")
                return False

        # Clear all errors in parallel
        tasks = [clear_single(name) for name in channel_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count successful clears
        successful_clears = sum(
            1 for result in results 
            if result is True and not isinstance(result, Exception)
        )
        
        logging.info(f"Successfully cleared errors for {successful_clears}/{len(channel_names)} channels")
        return successful_clears

    # ── Destination / Recording Path Discovery ───────────────────────────────

    async def get_recording_configuration(self, channel_name: str) -> Optional[JustInRecordingConfiguration]:
        """
        Henter recording configuration for en kanal.
        Returnerer bl.a. destinationPreset-navnet.

        POST /ingest/recordingConfiguration  {"channel": "Channel1"}
        """
        try:
            payload = {"channel": channel_name}
            response = await self._client.post("/ingest/recordingConfiguration", json=payload)
            response.raise_for_status()
            data = JustInRecordingConfiguration.model_validate(response.json())
            logging.debug(f"Recording config for {channel_name}: {data.configurations}")
            return data
        except httpx.RequestError as e:
            logging.warning(f"Could not fetch recordingConfiguration for {channel_name}: {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error fetching recordingConfiguration for {channel_name}: {e}")
            return None

    async def get_destination_presets(self, channel_name: str) -> Optional[JustInDestinationPresets]:
        """
        Henter listen af destination-presets for en kanal.

        POST /ingest/requestDestinationPresets  {"channel": "Channel1"}
        """
        try:
            payload = {"channel": channel_name}
            response = await self._client.post("/ingest/requestDestinationPresets", json=payload)
            response.raise_for_status()
            data = JustInDestinationPresets.model_validate(response.json())
            logging.debug(f"Destination presets for {channel_name}: {data.preset}")
            return data
        except httpx.RequestError as e:
            logging.warning(f"Could not fetch destination presets for {channel_name}: {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error fetching destination presets for {channel_name}: {e}")
            return None

    async def load_destination_preset(
        self, channel_name: str, preset_id: int, preset_name: str
    ) -> Optional[JustInLoadDestinationPresetResponse]:
        """
        Loader et specifikt destination-preset for at hente stier.

        POST /ingest/requestLoadDestinationPreset
        {"channel": "Channel1", "destination-preset-id": 1, "destination-preset-name": "Default"}
        """
        try:
            payload = {
                "channel": channel_name,
                "destination-preset-id": preset_id,
                "destination-preset-name": preset_name,
            }
            response = await self._client.post("/ingest/requestLoadDestinationPreset", json=payload)
            response.raise_for_status()
            data = JustInLoadDestinationPresetResponse.model_validate(response.json())
            logging.debug(f"Loaded destination preset for {channel_name}: {data.justin_destination_preset.name}")
            return data
        except httpx.RequestError as e:
            logging.warning(f"Could not load destination preset for {channel_name}: {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error loading destination preset for {channel_name}: {e}")
            return None

    async def discover_recording_paths(
        self, channel_name: str
    ) -> Optional[tuple[List[str], str]]:
        """
        3-step discovery flow: henter de faktiske recording-stier fra Just In Engine.

        1. recordingConfiguration -> finder preset-navn (f.eks. "Default")
        2. requestDestinationPresets -> finder listen + index
        3. requestLoadDestinationPreset -> henter de faktiske stier

        Returns:
            Tuple af (paths, preset_name) eller None hvis discovery fejlede.
        """
        # Step 1: Get the active destination preset name
        config = await self.get_recording_configuration(channel_name)
        if not config or not config.configurations:
            logging.warning(f"No recording configuration found for {channel_name}")
            return None

        preset_name = config.configurations[0].destinationPreset
        if not preset_name or preset_name == "-":
            logging.warning(f"No destination preset configured for {channel_name}")
            return None

        # Step 2: Get the preset list and find the index
        presets = await self.get_destination_presets(channel_name)
        if not presets or not presets.preset:
            logging.warning(f"No destination presets available for {channel_name}")
            return None

        try:
            preset_id = presets.preset.index(preset_name)
        except ValueError:
            logging.warning(f"Preset '{preset_name}' not found in preset list: {presets.preset}")
            return None

        # Step 3: Load the preset to get the actual paths
        loaded = await self.load_destination_preset(channel_name, preset_id, preset_name)
        if not loaded or not loaded.justin_destination_preset.destination_path:
            logging.warning(f"No destination paths in preset '{preset_name}' for {channel_name}")
            return None

        paths = [
            dp.path
            for dp in loaded.justin_destination_preset.destination_path
            if dp.path
        ]

        logging.info(
            f"Discovered recording paths for {channel_name} "
            f"(preset='{preset_name}'): {paths}"
        )
        return paths, preset_name