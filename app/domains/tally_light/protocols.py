"""
Tally Light Switch Protocols

Defines the abstract interface for different power switch implementations.
This allows for flexible support of various IP power switch models.
"""
from abc import ABC, abstractmethod
from enum import Enum


class PowerSwitchType(Enum):
    """Supported power switch types."""
    IP_POWER_9255 = "ip_power_9255"
    MOCK = "mock" # For development/testing


class PowerSwitchProtocol(ABC):
    """
    Abstract base class for power switch implementations.
    
    This protocol defines the interface that all power switch
    implementations must follow, ensuring consistency and
    enabling easy addition of new switch types.
    """

    @abstractmethod
    async def turn_on(self) -> bool:
        """
        Turn the power switch ON.
        
        Returns:
            bool: True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def turn_off(self) -> bool:
        """
        Turn the power switch OFF.
        
        Returns:
            bool: True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def get_status(self) -> bool:
        """
        Get current power switch status.
        
        Returns:
            bool: True if ON, False if OFF
            
        Raises:
            PowerSwitchError: If status cannot be determined
        """
        pass

    @abstractmethod
    async def is_online(self) -> bool:
        """
        Check if the power switch device is reachable on the network.
        
        This is a lightweight connectivity check, not the actual power state.
        Should use a short timeout (e.g., 1 second) for responsiveness.
        
        Returns:
            bool: True if device is reachable, False otherwise
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """
        Clean up resources (close HTTP clients, etc.).
        """
        pass

    @property
    @abstractmethod
    def switch_type(self) -> PowerSwitchType:
        """Get the switch type identifier."""
        pass


class PowerSwitchError(Exception):
    """Base exception for power switch operations."""
    pass


class PowerSwitchConnectionError(PowerSwitchError):
    """Raised when unable to connect to power switch."""
    pass


class PowerSwitchCommandError(PowerSwitchError):
    """Raised when a command fails to execute."""
    pass