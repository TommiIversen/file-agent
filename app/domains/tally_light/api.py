"""
Tally Light API

Provides a test endpoint so users can verify connectivity
and credentials from the Settings UI.
"""
import asyncio
import logging
from typing import Dict, Any

from fastapi import APIRouter

from app.dependencies.tally import get_tally_light_event_handler
from .protocols import PowerSwitchConnectionError, PowerSwitchCommandError, PowerSwitchError

router = APIRouter(prefix="/api/tally", tags=["Tally Light"])


@router.post("/test")
async def test_tally_light() -> Dict[str, Any]:
    """
    Test the tally light by turning it ON for 2 seconds, then OFF.

    Returns a JSON object with:
      - success: bool
      - message: human-readable result
      - error:   error details (only on failure)
    """
    handler = get_tally_light_event_handler()
    switch = handler._power_switch

    try:
        # 1. Turn ON
        await switch.turn_on()

        # 2. Keep it on for 2 seconds so the user can see it
        await asyncio.sleep(2)

        # 3. Turn OFF
        await switch.turn_off()

        logging.info("Tally light test: OK")
        return {"success": True, "message": "Tally lampen lyste i 2 sekunder — forbindelsen virker!"}

    except PowerSwitchConnectionError as e:
        logging.warning(f"Tally light test: connection failed — {e}")
        return {
            "success": False,
            "message": "Kan ikke nå tally lampen på netværket.",
            "error": str(e),
        }
    except PowerSwitchCommandError as e:
        logging.warning(f"Tally light test: command rejected — {e}")
        return {
            "success": False,
            "message": "Tally lampen afviste kommandoen (tjek brugernavn/password).",
            "error": str(e),
        }
    except PowerSwitchError as e:
        logging.error(f"Tally light test: unexpected error — {e}")
        return {
            "success": False,
            "message": "Uventet fejl ved test af tally lampen.",
            "error": str(e),
        }
