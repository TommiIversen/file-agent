"""
IP Power Switch Implementations

Concrete implementations of power switch protocols for various hardware models.
"""
import asyncio
import logging
import httpx
from typing import Optional

from .protocols import (
    PowerSwitchProtocol, 
    PowerSwitchType, 
    PowerSwitchError, 
    PowerSwitchConnectionError,
    PowerSwitchCommandError
)


class IPPower9255Client(PowerSwitchProtocol):
    """
    Implementation for IP Power 9255 switch.
    
    This switch uses HTTP GET requests with basic authentication
    and specific command syntax for power control.
    
    Hardware specs:
    - Model: IP Power 9255
    - Control: HTTP GET with embedded credentials
    - Default outlet: p61 (port 1)
    """

    DEFAULT_OUTLET = "p61" # Port 1

    def __init__(self, ip_address: str, username: str = "admin", password: str = "", timeout_seconds: float = 2.0):
        """
        Initialize IP Power 9255 client.
        
        Args:
            ip_address: IP address of the switch (e.g., "10.65.77.9")
            username: HTTP Basic Auth username
            password: HTTP Basic Auth password
            timeout_seconds: HTTP timeout for requests
        """
        self._ip_address = ip_address
        self._base_url = f"http://{username}:{password}@{ip_address}"
        self._timeout = timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None
        
        logging.info(f"IPPower9255Client initialized for {ip_address}")

    @property
    def switch_type(self) -> PowerSwitchType:
        """Get the switch type identifier."""
        return PowerSwitchType.IP_POWER_9255

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure HTTP client is initialized."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def turn_on(self) -> bool:
        """
        Turn the power switch ON.
        
        Sends: GET http://admin:12345678@10.65.77.9/Set.cmd?cmd=setpower+p61=1
        """
        try:
            client = await self._ensure_client()
            url = f"{self._base_url}/Set.cmd?cmd=setpower+{self.DEFAULT_OUTLET}=1"
            
            logging.debug(f"Sending ON command to IP Power 9255: {self._ip_address}")
            response = await client.get(url)
            response.raise_for_status()
            
            logging.info(f" IP Power 9255 turned ON (outlet {self.DEFAULT_OUTLET})")
            return True
            
        except httpx.RequestError as e:
            logging.error(f"Network error turning ON IP Power 9255: {e}", exc_info=True)
            raise PowerSwitchConnectionError(f"Failed to connect to switch at {self._ip_address}: {e}")
        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error turning ON IP Power 9255: {e}", exc_info=True)
            raise PowerSwitchCommandError(f"Switch rejected ON command: {e}")
        except Exception as e:
            logging.error(f"Unexpected error turning ON IP Power 9255: {e}", exc_info=True)
            raise PowerSwitchError(f"Unexpected error: {e}")

    async def turn_off(self) -> bool:
        """
        Turn the power switch OFF.
        
        Sends: GET http://admin:12345678@10.65.77.9/Set.cmd?cmd=setpower+p61=0
        """
        try:
            client = await self._ensure_client()
            url = f"{self._base_url}/Set.cmd?cmd=setpower+{self.DEFAULT_OUTLET}=0"
            
            logging.debug(f"Sending OFF command to IP Power 9255: {self._ip_address}")
            response = await client.get(url)
            response.raise_for_status()
            
            logging.info(f" IP Power 9255 turned OFF (outlet {self.DEFAULT_OUTLET})")
            return True
            
        except httpx.RequestError as e:
            logging.error(f"Network error turning OFF IP Power 9255: {e}", exc_info=True)
            raise PowerSwitchConnectionError(f"Failed to connect to switch at {self._ip_address}: {e}")
        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error turning OFF IP Power 9255: {e}", exc_info=True)
            raise PowerSwitchCommandError(f"Switch rejected OFF command: {e}")
        except Exception as e:
            logging.error(f"Unexpected error turning OFF IP Power 9255: {e}", exc_info=True)
            raise PowerSwitchError(f"Unexpected error: {e}")

    async def get_status(self) -> bool:
        """
        Get current power switch status.
        
        Note: IP Power 9255 doesn't provide a simple status endpoint,
        so we'll implement a basic connectivity check instead.
        """
        try:
            client = await self._ensure_client()
            # Try to access the main page to verify connectivity
            url = f"{self._base_url}/"
            
            logging.debug(f"Checking connectivity to IP Power 9255: {self._ip_address}")
            response = await client.get(url)
            response.raise_for_status()
            
            # We can't determine the actual outlet state without parsing HTML,
            # so we'll just return True if the device is reachable
            logging.debug(f"IP Power 9255 is reachable at {self._ip_address}")
            return True # Device is reachable
            
        except httpx.RequestError as e:
            logging.warning(f"Cannot reach IP Power 9255 at {self._ip_address}: {e}")
            raise PowerSwitchConnectionError(f"Switch unreachable: {e}")
        except httpx.HTTPStatusError as e:
            logging.warning(f"HTTP error checking IP Power 9255 status: {e}")
            raise PowerSwitchCommandError(f"Status check failed: {e}")
        except Exception as e:
            logging.error(f"Unexpected error checking IP Power 9255 status: {e}", exc_info=True)
            raise PowerSwitchError(f"Unexpected error: {e}")

    async def is_online(self) -> bool:
        """
        Check if the IP Power 9255 switch is reachable on the network.
        
        Uses a simple TCP connectivity check to port 80 with 3-second timeout.
        This is much more reliable than HTTP requests for basic connectivity.
        """
        try:
            # Simple TCP connectivity check to port 80
            future = asyncio.open_connection(self._ip_address, 80)
            
            try:
                # 3 second timeout for TCP connection
                reader, writer = await asyncio.wait_for(future, timeout=3.0)
                
                # Successfully connected - close immediately
                writer.close()
                await writer.wait_closed()
                
                logging.debug(f"TCP connection successful to {self._ip_address}:80 (online)")
                return True
                
            except asyncio.TimeoutError:
                logging.debug(f"TCP connection to {self._ip_address}:80 timed out (offline)")
                return False
            except (ConnectionRefusedError, OSError) as e:
                logging.debug(f"TCP connection to {self._ip_address}:80 failed: {e} (offline)")
                return False
                
        except Exception as e:
            logging.warning(f"Unexpected error checking TCP connectivity to {self._ip_address}: {e}")
            return False

    async def close(self) -> None:
        """Clean up HTTP client resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logging.debug(f"IP Power 9255 client closed for {self._ip_address}")


class MockPowerSwitchClient(PowerSwitchProtocol):
    """
    Mock implementation for development and testing.
    
    This client simulates power switch behavior without
    requiring actual hardware.
    """

    def __init__(self, simulate_ip: str = "localhost:8001"):
        """
        Initialize mock client.
        
        Args:
            simulate_ip: Simulated IP address for logging
        """
        self._simulate_ip = simulate_ip
        self._current_state = False # OFF by default
        
        logging.info(f"MockPowerSwitchClient initialized (simulating {simulate_ip})")

    @property
    def switch_type(self) -> PowerSwitchType:
        """Get the switch type identifier."""
        return PowerSwitchType.MOCK

    async def turn_on(self) -> bool:
        """Simulate turning the switch ON."""
        self._current_state = True
        logging.info(f" Mock Switch ON (simulating {self._simulate_ip})")
        return True

    async def turn_off(self) -> bool:
        """Simulate turning the switch OFF."""
        self._current_state = False
        logging.info(f" Mock Switch OFF (simulating {self._simulate_ip})")
        return True

    async def get_status(self) -> bool:
        """Get simulated switch status."""
        logging.debug(f"Mock Switch status: {'ON' if self._current_state else 'OFF'}")
        return self._current_state

    async def is_online(self) -> bool:
        """Simulate online check - mock is always online in development."""
        logging.debug(f"Mock Switch is always online (simulating {self._simulate_ip})")
        return True

    async def close(self) -> None:
        """Mock cleanup - nothing to do."""
        logging.debug(f"Mock Switch client closed (simulating {self._simulate_ip})")