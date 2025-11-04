"""
Tally Light Domain Models

This module defines the data models for the Tally Light domain, responsible
for managing IP Power Switch states based on recording status.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel


class TallyState(Enum):
    """
    Represents the three possible states of a tally light.
    
    Maps to IP Power Switch control:
    - OFF: All lights off (no recording activity) 
    - SOLID_ON: Solid light (active recording)
    - BLINKING: Blinking light (recording with errors/warnings)
    """
    OFF = "off"
    SOLID_ON = "solid_on"
    BLINKING = "blinking"


class TallyLightStatus(BaseModel):
    """
    Current status of the tally light system.
    
    Used for status reporting and monitoring.
    """
    current_state: TallyState
    last_update: str  # ISO timestamp
    error_message: Optional[str] = None
    blink_active: bool = False
    
    class Config:
        """Pydantic configuration for the model"""
        use_enum_values = True


class TallyLightCommand(BaseModel):
    """
    Command to control tally light state.
    
    Used when manual control is needed.
    """
    target_state: TallyState
    duration_seconds: Optional[int] = None  # For timed operations
    
    class Config:
        """Pydantic configuration for the model"""
        use_enum_values = True