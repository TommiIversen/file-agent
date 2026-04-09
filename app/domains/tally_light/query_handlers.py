"""
Tally Light Query Handlers.
"""
from typing import Any, Dict

from app.core.cqrs.shared_queries import GetTallySwitchStatusQuery
from .monitor_service import TallySwitchMonitorService


class GetTallySwitchStatusQueryHandler:
    """Returns current tally switch hardware status as a dict."""

    def __init__(self, switch_monitor: TallySwitchMonitorService) -> None:
        self._monitor = switch_monitor

    async def handle(self, query: GetTallySwitchStatusQuery) -> Dict[str, Any]:
        if self._monitor.current_status:
            status = self._monitor.current_status
            return {
                "is_online": status.is_online,
                "switch_type": "IP Power 9255",
                "ip_address": self._monitor._ip_address,
                "last_checked": status.last_checked.isoformat() if status.last_checked else None,
                "error_message": status.error_message,
                "is_monitoring": self._monitor.is_monitoring,
            }
        return {
            "is_online": False,
            "switch_type": "IP Power 9255",
            "ip_address": self._monitor._ip_address,
            "last_checked": None,
            "error_message": "Not yet checked",
            "is_monitoring": self._monitor.is_monitoring,
        }
