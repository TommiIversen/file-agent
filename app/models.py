from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict


class FileStatus(str, Enum):
    """
    Status for en tracked fil gennem hele kopieringsprocessen.

    Normal Workflow: Discovered -> Ready -> InQueue -> Copying -> Completed
    Growing Workflow: Discovered -> Growing -> ReadyToStartGrowing -> InQueue -> GrowingCopy -> Copying -> Completed
    Alternative: -> Failed (ved fejl)
    Space Management: -> WaitingForSpace -> (retry) eller SpaceError (permanent)
    """

    DISCOVERED = "Discovered"  # Fil fundet, men ikke stabil endnu
    READY = "Ready"  # Fil er stabil og klar til kopiering
    IN_QUEUE = "InQueue"  # Fil er tilføjet til job queue
    COPYING = "Copying"  # Fil er ved at blive kopieret
    COMPLETED = "Completed"  # Fil er succesfuldt kopieret og slettet
    COMPLETED_DELETE_FAILED = "CompletedDeleteFailed"  # Fil er kopieret, men kunne ikke slettes
    FAILED = "Failed"  # Fil kunne ikke kopieres (permanent fejl)
    REMOVED = "Removed"  # Fil er forsvundet fra source (bevares som history)

    # Growing file states
    GROWING = "Growing"  # Fil er aktiv growing, størrelse ændres
    READY_TO_START_GROWING = (
        "ReadyToStartGrowing"  # Fil >= minimum size for growing copy
    )
    GROWING_COPY = "GrowingCopy"  # Aktiv growing copy i gang

    # Space management states
    WAITING_FOR_SPACE = "WaitingForSpace"  # Midlertidig plads mangel, venter på retry
    SPACE_ERROR = "SpaceError"  # Permanent plads problem, kræver indgriben

    # Network management states
    WAITING_FOR_NETWORK = (
        "WaitingForNetwork"  # Destination er offline, venter på netværk
    )

    # NOTE: Removed PAUSED_* states as part of fail-and-rediscover strategy
    # Network errors now cause immediate FAILED status instead of pause/resume


class StorageStatus(str, Enum):
    """Storage status levels for monitoring disk space and accessibility"""

    OK = "OK"  # Normal operation
    WARNING = "WARNING"  # Low space warning
    ERROR = "ERROR"  # Unmounted/inaccessible
    CRITICAL = "CRITICAL"  # Very low space / read-only


class MountStatus(str, Enum):
    """Network mount operation status for real-time UI feedback"""

    ATTEMPTING = "ATTEMPTING"  # Mount operation in progress
    SUCCESS = "SUCCESS"  # Mount completed successfully
    FAILED = "FAILED"  # Mount operation failed
    NOT_CONFIGURED = "NOT_CONFIGURED"  # Network mount not configured


class TrackedFile(BaseModel):
    """
    Central datastruktur der repræsenterer en fil gennem hele kopieringsprocessen.

    Bruges af StateManager til at holde styr på alle filer og deres tilstand.
    Indeholder både metadata og progress information.
    """

    # Auto-generated unique identifier for internal tracking
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this file entry",
    )

    file_path: str = Field(..., description="Absolut sti til kildefilen")

    status: FileStatus = Field(
        default=FileStatus.DISCOVERED,
        description="Filens nuværende status i workflow'et",
    )

    file_size: int = Field(default=0, ge=0, description="Filstørrelse i bytes")

    last_write_time: Optional[datetime] = Field(
        default=None,
        description="Sidste gang filen blev modificeret (til stabilitetschek)",
    )

    copy_progress: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Kopieringsprogress i procent (0-100)",
    )

    error_message: Optional[str] = Field(
        default=None, description="Fejlbesked hvis status er FAILED"
    )

    retry_count: int = Field(
        default=0, ge=0, description="Antal retry forsøg for denne fil"
    )

    discovered_at: datetime = Field(
        default_factory=datetime.now, description="Tidspunkt hvor filen blev opdaget"
    )

    started_copying_at: Optional[datetime] = Field(
        default=None, description="Tidspunkt hvor kopiering startede"
    )

    completed_at: Optional[datetime] = Field(
        default=None, description="Tidspunkt hvor kopiering blev færdig"
    )

    failed_at: Optional[datetime] = Field(
        default=None, description="Tidspunkt hvor filen fejlede permanent"
    )

    space_error_at: Optional[datetime] = Field(
        default=None, description="Tidspunkt hvor filen fik permanent space error"
    )

    destination_path: Optional[str] = Field(
        default=None,
        description="Sti til destination filen (med evt. navnekonflikt suffix)",
    )

    # Growing file tracking
    growth_rate_mbps: float = Field(
        default=0.0,
        ge=0.0,
        description="Filens vækstrate i MB per sekund (kun for growing files)",
    )

    bytes_copied: int = Field(
        default=0,
        ge=0,
        description="Antal bytes kopieret indtil videre (for growing copy progress)",
    )

    copy_speed_mbps: float = Field(
        default=0.0,
        ge=0.0,
        description="Aktuel copy hastighed i MB per sekund (for alle copy modes)",
    )

    last_growth_check: Optional[datetime] = Field(
        default=None, description="Sidste gang vi tjekkede for file growth"
    )

    # Additional growing file tracking fields to eliminate duplicate state in GrowingFileDetector
    previous_file_size: int = Field(
        default=0,
        ge=0,
        description="Forrige filstørrelse før sidste size check (til growth detection)",
    )

    first_seen_size: int = Field(
        default=0,
        ge=0,
        description="Filstørrelse da filen først blev opdaget (til growth analysis)",
    )

    growth_stable_since: Optional[datetime] = Field(
        default=None,
        description="Tidspunkt hvor filen sidst stoppede med at vokse (til stability detection)",
    )

    # Retry tracking - consolidated in TrackedFile
    retry_info: Optional["RetryInfo"] = Field(
        default=None, description="Active retry information if file has scheduled retry"
    )

    model_config = ConfigDict(
        # Eksempel data til dokumentation
        json_schema_extra={
            "example": {
                "file_path": "/source/video_clip_001.mxv",
                "status": "Copying",
                "file_size": 1073741824,
                "last_write_time": "2025-10-08T14:30:00",
                "copy_progress": 67.5,
                "error_message": None,
                "retry_count": 0,
                "discovered_at": "2025-10-08T14:25:00",
                "started_copying_at": "2025-10-08T14:27:00",
                "completed_at": None,
                "destination_path": "/destination/video_clip_001.mxv",
            }
        }
    )


class StorageInfo(BaseModel):
    """
    Storage information for a single path (source or destination).

    Contains disk space, accessibility status, and configuration thresholds.
    """

    path: str = Field(..., description="Absolut sti til storage location")

    is_accessible: bool = Field(
        ..., description="Om stien er tilgængelig (mounted/exists)"
    )

    has_write_access: bool = Field(..., description="Om vi kan skrive til stien")

    free_space_gb: float = Field(..., ge=0.0, description="Ledig plads i GB")

    total_space_gb: float = Field(..., ge=0.0, description="Total plads i GB")

    used_space_gb: float = Field(..., ge=0.0, description="Brugt plads i GB")

    status: StorageStatus = Field(..., description="Current storage status")

    warning_threshold_gb: float = Field(
        ..., ge=0.0, description="Warning threshold i GB"
    )

    critical_threshold_gb: float = Field(
        ..., ge=0.0, description="Critical threshold i GB"
    )

    last_checked: datetime = Field(..., description="Tidspunkt for sidste check")

    error_message: Optional[str] = Field(
        default=None, description="Fejlbesked hvis der er problemer"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "path": "/mnt/nas/destination",
                "is_accessible": True,
                "has_write_access": True,
                "free_space_gb": 45.2,
                "total_space_gb": 2048.0,
                "used_space_gb": 2002.8,
                "status": "WARNING",
                "warning_threshold_gb": 50.0,
                "critical_threshold_gb": 20.0,
                "last_checked": "2025-10-09T10:30:00Z",
            }
        }
    )


class StorageUpdate(BaseModel):
    """
    Event data structure for storage change notifications.

    Used by StorageMonitorService to notify WebSocketManager of changes.
    """

    storage_type: str = Field(
        ..., description="Type of storage: 'source' or 'destination'"
    )

    old_status: Optional[StorageStatus] = Field(
        default=None, description="Previous storage status"
    )

    new_status: StorageStatus = Field(..., description="New storage status")

    storage_info: StorageInfo = Field(..., description="Complete storage information")

    timestamp: datetime = Field(
        default_factory=datetime.now, description="Tidspunkt for opdateringen"
    )

    model_config = ConfigDict()


class MountStatusUpdate(BaseModel):
    """
    Event data structure for network mount status notifications.

    Used by StorageMonitorService to notify WebSocketManager of mount operations
    for real-time UI feedback during network mount attempts.
    """

    storage_type: str = Field(
        ..., description="Type of storage: 'source' or 'destination'"
    )

    mount_status: MountStatus = Field(..., description="Current mount operation status")

    share_url: Optional[str] = Field(
        default=None, description="Network share URL being mounted (e.g., //nas/shared)"
    )

    mount_path: Optional[str] = Field(
        default=None,
        description="Local path where share is mounted (e.g., /Volumes/shared)",
    )

    target_path: str = Field(
        ..., description="Target storage path that triggered mount operation"
    )

    error_message: Optional[str] = Field(
        default=None, description="Error message if mount operation failed"
    )

    timestamp: datetime = Field(
        default_factory=datetime.now, description="Timestamp of mount status update"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "storage_type": "destination",
                "mount_status": "ATTEMPTING",
                "share_url": "//nas/shared",
                "mount_path": "/Volumes/shared",
                "target_path": "/Volumes/shared/ingest",
                "error_message": None,
                "timestamp": "2025-10-13T14:30:00Z",
            }
        }
    )


class FileStateUpdate(BaseModel):
    """
    Event data structure for pub/sub system.

    Bruges til at notificere subscribers om ændringer i fil status.
    """

    file_path: str
    old_status: Optional[FileStatus]
    new_status: FileStatus
    tracked_file: TrackedFile
    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = ConfigDict()


class SpaceCheckResult(BaseModel):
    """
    Result of disk space pre-flight check before file copying.

    Used by FileCopyService to determine if destination has sufficient space
    for a file before attempting to copy it. Includes logic for determining
    if space shortage might be temporary.
    """

    has_space: bool = Field(
        ..., description="Whether destination has enough space for the file"
    )

    available_bytes: int = Field(
        ..., description="Available space on destination in bytes"
    )

    required_bytes: int = Field(
        ..., description="Required space including file size and safety margin"
    )

    file_size_bytes: int = Field(..., description="Actual file size in bytes")

    safety_margin_bytes: int = Field(
        ..., description="Safety margin in bytes to prevent disk full"
    )

    reason: str = Field(
        ..., description="Human-readable explanation of the space check result"
    )

    timestamp: datetime = Field(
        default_factory=datetime.now, description="When the space check was performed"
    )

    def is_temporary_shortage(self) -> bool:
        """
        Determine if space shortage might be temporary and worth retrying.

        Logic: If we're within 20% of required space, it might be temporary
        due to other operations completing, temp files being cleaned, etc.

        Returns:
            True if shortage might be temporary and worth retrying later
        """
        if self.has_space:
            return False

        shortage = self.required_bytes - self.available_bytes
        shortage_percentage = shortage / self.required_bytes

        # Consider temporary if shortage is less than 20% of required space
        return shortage_percentage < 0.2

    def get_shortage_gb(self) -> float:
        """
        Get space shortage amount in GB for display purposes.

        Returns:
            Shortage in GB, or 0.0 if there's sufficient space
        """
        if self.has_space:
            return 0.0
        return (self.required_bytes - self.available_bytes) / (1024**3)

    def get_available_gb(self) -> float:
        """Get available space in GB for display"""
        return self.available_bytes / (1024**3)

    def get_required_gb(self) -> float:
        """Get required space in GB for display"""
        return self.required_bytes / (1024**3)

    model_config = ConfigDict()


class RetryInfo(BaseModel):
    """
    Information about scheduled retry operations for space-related failures.

    Used directly in TrackedFile to maintain single source of truth.
    """

    scheduled_at: datetime = Field(..., description="When retry was scheduled")
    retry_at: datetime = Field(..., description="When retry should execute")
    reason: str = Field(..., description="Reason for retry (e.g., 'space shortage')")
    retry_type: str = Field(default="space", description="Type of retry operation")

    # Note: asyncio.Task cannot be serialized in Pydantic, so we handle it separately in StateManager

    model_config = ConfigDict()
