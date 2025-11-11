"""
Power Switch Factory

Factory function for creating power switch instances based on configuration.
"""
import logging
from app.config import Settings
from .protocols import PowerSwitchProtocol, PowerSwitchType
from .switch_clients import IPPower9255Client, MockPowerSwitchClient


def create_power_switch(settings: Settings) -> PowerSwitchProtocol:
    """
    Factory function to create the appropriate power switch client
    based on the configuration.
    
    Args:
        settings: Application settings containing switch configuration
        
    Returns:
        PowerSwitchProtocol: Configured power switch client
        
    Raises:
        ValueError: If an unsupported switch type is specified
    """
    switch_type = settings.tally_light_switch_type.lower()
    
    if switch_type == PowerSwitchType.IP_POWER_9255.value:
        logging.info(f"Creating IP Power 9255 client for {settings.tally_light_switch_ip}")
        return IPPower9255Client(
            ip_address=settings.tally_light_switch_ip,
            timeout_seconds=settings.tally_light_api_timeout_seconds
        )
    
    elif switch_type == PowerSwitchType.MOCK.value:
        logging.info(f"Creating Mock power switch client (simulating {settings.tally_light_switch_ip})")
        return MockPowerSwitchClient(
            simulate_ip=settings.tally_light_switch_ip
        )
    
    else:
        # Log available options for debugging
        available_types = [t.value for t in PowerSwitchType]
        logging.error(f"Unsupported switch type '{switch_type}'. Available types: {available_types}")
        raise ValueError(
            f"Unsupported power switch type: '{switch_type}'. "
            f"Supported types are: {', '.join(available_types)}"
        )