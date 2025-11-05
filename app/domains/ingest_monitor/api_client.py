"""
Ingest API Client

Håndterer al direkte HTTP-kommunikation med Just In Engine API'en.
Denne klasse er ansvarlig for at abstraktere httpx-kommunikation og
validere API-svar med Pydantic-modeller.
"""
import logging
import httpx
from typing import List, Optional, Tuple
from app.config import Settings
from .models import JustInActiveChannels, JustInRecordingStatus, JustInErrors, JustInError


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

    async def get_active_channels(self) -> List[str]:
        """
        Henter den aktive kanalliste fra Just In Engine.
        
        Returns:
            List[str]: Liste af aktive kanalnavne. Returnerer tom liste ved fejl.
        """
        try:
            response = await self._client.get("/ingest/activeChannels")
            response.raise_for_status()
            data = JustInActiveChannels.model_validate(response.json())
            logging.debug(f"Retrieved {len(data.channel_names)} active channels: {data.channel_names}")
            return data.channel_names
        except httpx.RequestError as e:
            logging.warning(f"Could not fetch activeChannels: {e}")
            return []  # Return empty list on error
        except Exception as e:
            logging.error(f"Unexpected error fetching activeChannels: {e}")
            return []

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

    async def get_all_channel_statuses(self, channel_names: List[str]) -> List[Tuple[str, JustInRecordingStatus]]:
        """
        Fetch recording status for multiple channels in parallel.
        
        Used by the fast polling loop to efficiently update all channel statuses.
        
        Args:
            channel_names: List of channel names to fetch status for
            
        Returns:
            List of (channel_name, status_data) tuples for successful fetches
        """
        if not channel_names:
            return []

        logging.debug(f"Fetching status for {len(channel_names)} channels: {channel_names}")

        async def fetch_single(name: str) -> Optional[Tuple[str, JustInRecordingStatus]]:
            status = await self.get_channel_status(name)
            return (name, status) if status else None

        # Fetch all statuses in parallel
        import asyncio
        tasks = [fetch_single(name) for name in channel_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out None results and exceptions
        successful_results = [
            result for result in results 
            if result is not None and not isinstance(result, Exception)
        ]
        
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
        import asyncio
        tasks = [fetch_single(name) for name in channel_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions, keep empty error lists
        successful_results = [
            result for result in results 
            if not isinstance(result, Exception)
        ]
        
        logging.debug(f"Successfully fetched errors for {len(successful_results)}/{len(channel_names)} channels")
        return successful_results

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
        import asyncio
        tasks = [clear_single(name) for name in channel_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count successful clears
        successful_clears = sum(
            1 for result in results 
            if result is True and not isinstance(result, Exception)
        )
        
        logging.info(f"Successfully cleared errors for {successful_clears}/{len(channel_names)} channels")
        return successful_clears