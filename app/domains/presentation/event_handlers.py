import logging
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger(__name__)

from app.core.events.file_events import FileStatusChangedEvent, FileCopyProgressEvent, FileDiscoveredEvent, FileCopyCompletedEvent
from app.core.events.scanner_events import ScannerStatusChangedEvent
from app.core.events.storage_events import MountStatusChangedEvent, StorageStatusChangedEvent
from app.core.events.ingest_events import (
    IngestStatusUpdatedEvent, 
    ChannelErrorDetectedEvent,
    IngestOnlineEvent,
    IngestOfflineEvent,
    RecordingPathsDiscoveredEvent,
    AutoStopWarningEvent,
    AutoStopTriggeredEvent,
)
from app.core.events.tally_events import (
    TallySwitchStatusUpdatedEvent, 
    TallySwitchOnlineEvent, 
    TallySwitchOfflineEvent
)
from app.core.events.audio_events import (
    AudioRecordingStartedEvent,
    AudioRecordingStoppedEvent,
    AudioRecordingErrorEvent,
    AudioDeviceDisconnectedEvent,
    AudioOverflowWarningEvent,
    AudioLevelsEvent,
)
from app.core.file_repository import FileRepository
from app.domains.presentation.websocket_manager import WebSocketManager
from app.models import FileStatus


def _serialize_storage_info(storage_info) -> dict | None:
    if not storage_info:
        return None
    return {
        "path": storage_info.path,
        "is_accessible": storage_info.is_accessible,
        "has_write_access": storage_info.has_write_access,
        "free_space_gb": round(storage_info.free_space_gb, 2),
        "total_space_gb": round(storage_info.total_space_gb, 2),
        "used_space_gb": round(storage_info.used_space_gb, 2),
        "status": storage_info.status.value,
        "warning_threshold_gb": storage_info.warning_threshold_gb,
        "critical_threshold_gb": storage_info.critical_threshold_gb,
        "last_checked": storage_info.last_checked.isoformat(),
        "error_message": storage_info.error_message,
    }


def _serialize_tracked_file(tracked_file) -> Dict[str, Any]:
    data = tracked_file.model_dump(mode="json")
    data["file_size_mb"] = round(tracked_file.file_size / (1024 * 1024), 2)
    return data


class PresentationEventHandlers:
    def __init__(self, websocket_manager: WebSocketManager, file_repository: FileRepository):
        self.websocket_manager = websocket_manager
        self.file_repository = file_repository
        self._scanner_status = {"scanning": True, "paused": False} # Initial state

    def _get_timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    async def handle_file_discovered_event(self, event: FileDiscoveredEvent) -> None:
        """Handle when a new file is discovered by the scanner."""
        logging.info(f"File discovered event: {event.file_path} ({event.file_size} bytes)")
        
        message_data = {
            "type": "file_discovered",
            "data": {
                "file_path": event.file_path,
                "file_size": event.file_size,
                "file_size_mb": round(event.file_size / (1024 * 1024), 2),
                "last_write_time": datetime.fromtimestamp(event.last_write_time).isoformat(),
                "status": FileStatus.DISCOVERED.value,
                "timestamp": event.timestamp.isoformat(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_file_status_changed_event(self, update: FileStatusChangedEvent) -> None:
        logging.info(f"Received event: {update.file_path} -> {update.new_status.value}")
        tracked_file = await self.file_repository.get_by_id(update.file_id)
        if not tracked_file:
            logging.warning(f"Received FileStatusChangedEvent for unknown file ID: {update.file_id}")
            return

        message_data = {
            "type": "file_update",
            "data": {
                "file_path": update.file_path,
                "old_status": update.old_status.value if update.old_status else None,
                "new_status": update.new_status.value,
                "file": _serialize_tracked_file(tracked_file),
                "timestamp": update.timestamp.isoformat(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_file_copy_progress(self, event: FileCopyProgressEvent) -> None:
        progress_percent = (event.bytes_copied / event.total_bytes) * 100 if event.total_bytes > 0 else 0
        message_data = {
            "type": "file_progress_update",
            "data": {
                "file_id": event.file_id,
                "bytes_copied": event.bytes_copied,
                "total_bytes": event.total_bytes,
                "copy_speed_mbps": round(event.copy_speed_mbps, 2),
                "progress_percent": round(progress_percent, 2),
                "timestamp": event.timestamp.isoformat(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_file_copy_completed(self, event: FileCopyCompletedEvent) -> None:
        """Handle when a file copy operation completes - send final progress update."""
        logging.info(f"File copy completed: {event.file_path} ({event.bytes_copied} bytes)")
        
        # Send final progress update to ensure UI shows 100%
        message_data = {
            "type": "file_progress_update",
            "data": {
                "file_id": event.file_id,
                "bytes_copied": event.bytes_copied,
                "total_bytes": event.bytes_copied, # Use actual copied bytes for final update
                "copy_speed_mbps": 0.0, # Speed is 0 since copy is done
                "progress_percent": 100.0, # Explicitly set to 100%
                "timestamp": event.timestamp.isoformat(),
                "is_final": True, # Flag to indicate this is the final progress update
            },
        }
        self.websocket_manager.broadcast_message(message_data)

        # Also send a completion notification with both source and destination info
        completion_data = {
            "type": "file_copy_completed",
            "data": {
                "file_id": event.file_id,
                "file_path": event.file_path,
                "destination_path": event.destination_path,
                "bytes_copied": event.bytes_copied, # Faktiske kopierede bytes
                "source_size": event.source_size,    # Original source størrelse
                "dest_size": event.dest_size,        # Destination størrelse
                "is_growing_file": event.source_size != event.dest_size, # Flag for growing files
                "timestamp": event.timestamp.isoformat(),
            },
        }
        self.websocket_manager.broadcast_message(completion_data)

    async def handle_scanner_status_event(self, event: ScannerStatusChangedEvent) -> None:
        self._scanner_status = {"scanning": event.is_scanning, "paused": event.is_paused}
        message_data = {
            "type": "scanner_status",
            "data": {
                "scanning": event.is_scanning,
                "paused": event.is_paused,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_storage_status_event(self, event: StorageStatusChangedEvent) -> None:
        update_data = event.update
        message_data = {
            "type": "storage_update",
            "data": {
                "storage_type": update_data.storage_type,
                "old_status": update_data.old_status.value if update_data.old_status else None,
                "new_status": update_data.new_status.value,
                "storage_info": _serialize_storage_info(update_data.storage_info),
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_mount_status_event(self, event: MountStatusChangedEvent) -> None:
        update_data = event.update
        message_data = {
            "type": "mount_status",
            "data": {
                "storage_type": update_data.storage_type,
                "mount_status": update_data.mount_status.value,
                "share_url": update_data.share_url,
                "mount_path": update_data.mount_path,
                "target_path": update_data.target_path,
                "error_message": update_data.error_message,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_ingest_status_updated_event(self, event: IngestStatusUpdatedEvent) -> None:
        """Handle ingest status updates from Just In Engine monitoring."""
        logging.debug(f"Broadcasting ingest status update with {len(event.status_snapshot)} channels")
        
        message_data = {
            "type": "ingest_status_update",
            "data": {
                "channels": event.status_snapshot,
                "auto_stop": event.auto_stop_info,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_channel_error_detected_event(self, event: ChannelErrorDetectedEvent) -> None:
        """Handle channel error events from Just In Engine monitoring."""
        logging.warning(f"Broadcasting channel error: {event.channel_name} - {event.error_message}")
        
        data: dict = {
            "channel_name": event.channel_name,
            "error_message": event.error_message,
            "error_code": event.error_code,
            "timestamp": self._get_timestamp(),
        }
        if event.error_domain:
            data["error_domain"] = event.error_domain
        if event.error_description:
            data["error_description"] = event.error_description
        if event.error_type is not None:
            data["error_type"] = event.error_type

        message_data = {
            "type": "channel_error",
            "data": data,
        }
        self.websocket_manager.broadcast_message(message_data)

    # === INGEST CONNECTION EVENT HANDLERS ===

    async def handle_ingest_online_event(self, event: IngestOnlineEvent) -> None:
        """Handle ingest monitor connecting to Just In Engine."""
        logging.info(" Ingest monitor connected to Just In Engine")
        
        message_data = {
            "type": "ingest_online",
            "data": {
                "is_connected": True,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_ingest_offline_event(self, event: IngestOfflineEvent) -> None:
        """Handle ingest monitor disconnecting from Just In Engine."""
        logging.warning(" Ingest monitor disconnected from Just In Engine")
        
        message_data = {
            "type": "ingest_offline",
            "data": {
                "is_connected": False,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    # === RECORDING PATHS EVENT HANDLERS ===

    async def handle_recording_paths_discovered_event(
        self, event: RecordingPathsDiscoveredEvent
    ) -> None:
        """Handle recording paths discovered from Just In Engine."""
        logging.info(
            "Broadcasting recording paths for %s (preset=%s): %s",
            event.channel_name,
            event.preset_name,
            event.paths,
        )

        message_data = {
            "type": "recording_paths_update",
            "data": {
                "channel_name": event.channel_name,
                "preset_name": event.preset_name,
                "paths": list(event.paths),
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    # === AUTO-STOP EVENT HANDLERS ===

    async def handle_auto_stop_warning_event(self, event: AutoStopWarningEvent) -> None:
        """Broadcast auto-stop warning to all connected clients."""
        logging.warning(
            "Broadcasting auto-stop warning: %s at %ds, %ds remaining",
            event.channel_name,
            event.recording_seconds,
            event.remaining_seconds,
        )

        message_data = {
            "type": "auto_stop_warning",
            "data": {
                "channel_name": event.channel_name,
                "recording_seconds": event.recording_seconds,
                "limit_seconds": event.limit_seconds,
                "remaining_seconds": event.remaining_seconds,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_auto_stop_triggered_event(self, event: AutoStopTriggeredEvent) -> None:
        """Broadcast auto-stop triggered notification to all connected clients."""
        logging.warning(
            "Broadcasting auto-stop triggered: %s at %ds (limit=%ds)",
            event.channel_name,
            event.recording_seconds,
            event.limit_seconds,
        )

        message_data = {
            "type": "auto_stop_triggered",
            "data": {
                "channel_name": event.channel_name,
                "recording_seconds": event.recording_seconds,
                "limit_seconds": event.limit_seconds,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    # === TALLY SWITCH EVENT HANDLERS ===

    async def handle_tally_switch_status_updated_event(self, event: TallySwitchStatusUpdatedEvent) -> None:
        """Handle tally switch status updates (online/offline changes)."""
        status = event.status
        
        logging.info(f"Broadcasting tally switch status: {status.ip_address} - {'ONLINE' if status.is_online else 'OFFLINE'}")
        
        message_data = {
            "type": "tally_switch_status_update",
            "data": {
                "is_online": status.is_online,
                "switch_type": status.switch_type,
                "ip_address": status.ip_address,
                "last_checked": status.last_checked.isoformat() if status.last_checked else None,
                "error_message": status.error_message,
                "status_changed": event.status_changed,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_tally_switch_online_event(self, event: TallySwitchOnlineEvent) -> None:
        """Handle tally switch coming online."""
        status = event.status
        
        logging.info(f" Tally switch {status.ip_address} came ONLINE")
        
        message_data = {
            "type": "tally_switch_online",
            "data": {
                "is_online": True,
                "switch_type": status.switch_type,
                "ip_address": status.ip_address,
                "last_checked": status.last_checked.isoformat() if status.last_checked else None,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_tally_switch_offline_event(self, event: TallySwitchOfflineEvent) -> None:
        """Handle tally switch going offline."""
        status = event.status
        
        logging.warning(f" Tally switch {status.ip_address} went OFFLINE")
        
        message_data = {
            "type": "tally_switch_offline",
            "data": {
                "is_online": False,
                "switch_type": status.switch_type,
                "ip_address": status.ip_address,
                "last_checked": status.last_checked.isoformat() if status.last_checked else None,
                "error_message": status.error_message,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    # === AUDIO RECORDING EVENT HANDLERS ===

    async def handle_audio_recording_started_event(self, event: AudioRecordingStartedEvent) -> None:
        """Broadcast audio recording started to all connected clients."""
        logging.info(
            "Audio recording started: session=%s, %d tracks @ %dHz",
            event.session_id,
            len(event.tracks),
            event.samplerate,
        )

        message_data = {
            "type": "audio_recording_started",
            "data": {
                "session_id": event.session_id,
                "tracks": event.tracks,
                "samplerate": event.samplerate,
                "files": event.files,
                "track_count": len(event.tracks),
                "timestamp": event.timestamp.isoformat(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_audio_recording_stopped_event(self, event: AudioRecordingStoppedEvent) -> None:
        """Broadcast audio recording stopped to all connected clients."""
        logging.info(
            "Audio recording stopped: session=%s, duration=%.1fs, overflows=%d",
            event.session_id,
            event.duration_seconds,
            event.overflow_count,
        )

        message_data = {
            "type": "audio_recording_stopped",
            "data": {
                "session_id": event.session_id,
                "files": event.files,
                "duration_seconds": round(event.duration_seconds, 1),
                "overflow_count": event.overflow_count,
                "timestamp": event.timestamp.isoformat(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_audio_recording_error_event(self, event: AudioRecordingErrorEvent) -> None:
        """Broadcast audio recording error to all connected clients."""
        logging.error(
            "Audio recording error: %s (recoverable=%s, session=%s)",
            event.error,
            event.recoverable,
            event.session_id,
        )

        message_data = {
            "type": "audio_recording_error",
            "data": {
                "error": event.error,
                "recoverable": event.recoverable,
                "session_id": event.session_id,
                "timestamp": event.timestamp.isoformat(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_audio_device_disconnected_event(self, event: AudioDeviceDisconnectedEvent) -> None:
        """Broadcast audio device disconnection to all connected clients."""
        logging.warning("Audio device disconnected: %s", event.device_name)

        message_data = {
            "type": "audio_device_disconnected",
            "data": {
                "device_name": event.device_name,
                "timestamp": event.timestamp.isoformat(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_audio_overflow_warning_event(self, event: AudioOverflowWarningEvent) -> None:
        """Broadcast audio overflow warning to all connected clients."""
        logging.warning(
            "Audio overflow warning: dropped=%d, total=%d, session=%s",
            event.dropped_count,
            event.total_drops,
            event.session_id,
        )

        message_data = {
            "type": "audio_overflow_warning",
            "data": {
                "dropped_count": event.dropped_count,
                "total_drops": event.total_drops,
                "session_id": event.session_id,
                "timestamp": event.timestamp.isoformat(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_audio_levels_event(self, event: AudioLevelsEvent) -> None:
        """Broadcast audio peak levels to all connected clients (~8 Hz)."""
        message_data = {
            "type": "audio_levels",
            "data": {
                "session_id": event.session_id,
                "tracks": event.track_peaks,
            },
        }
        self.websocket_manager.broadcast_message(message_data)
