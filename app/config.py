from pathlib import Path
import logging
import sys

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from .utils.host_config import get_hostname, get_hostname_settings_file, list_all_settings_files, get_data_dir, get_logs_dir, get_database_path

_log = logging.getLogger(__name__)


def _get_app_directory() -> str:
    """Return the directory where the application lives."""
    if getattr(sys, 'frozen', False):
        # PyInstaller frozen build — use the executable's directory
        return str(Path(sys.executable).parent.resolve())
    return str(Path('.').resolve())


def _read_build_time() -> str:
    """Read BUILD_TIME file created by CI. Returns 'n/a' if missing."""
    search_paths = []

    # 1. PyInstaller _MEIPASS (bundled data files)
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        search_paths.append(Path(meipass) / 'BUILD_TIME')

    # 2. Executable's directory (for onedir builds)
    if getattr(sys, 'frozen', False):
        search_paths.append(Path(sys.executable).parent / 'BUILD_TIME')

    # 3. Current working directory (development)
    search_paths.append(Path('.') / 'BUILD_TIME')

    for path in search_paths:
        try:
            value = path.read_text().strip()
            _log.debug(f"BUILD_TIME found at: {path.resolve()} → '{value}'")
            return value
        except FileNotFoundError:
            _log.debug(f"BUILD_TIME not found at: {path.resolve()}")

    _log.debug("BUILD_TIME file not found in any search path")
    return 'n/a'


BUILD_TIME: str = _read_build_time()
APP_DIRECTORY: str = _get_app_directory()


class Settings(BaseSettings):
    # Database
    database_path: str = Field(
        default_factory=get_database_path,
        description="Path to SQLite database file"
    )

    # Filstier
    source_directory: str
    destination_directory: str

    # Output folder template system
    output_folder_template_enabled: bool = False
    output_folder_rules: str = "" # JSON string or simple rule format
    output_folder_default_category: str = "OTHER"
    output_folder_date_format: str = "filename[0:6]" # Extract first 6 chars as date
    output_folder_time_format: str = "filename[7:13]" # Extract chars 7-13 as time

    # Timing konfiguration
    file_stable_time_seconds: int = 120
    polling_interval_seconds: int = 10

    # Filkopiering
    use_temporary_file: bool = False
    max_retry_attempts: int = 3
    retry_delay_seconds: int = 10
    global_retry_delay_seconds: int = 60
    copy_progress_update_interval: int = (
        1 # Update progress every N percent (10 = every 10%)
    )
    file_operation_timeout_seconds: int = 30 # Timeout for individual file operations (open, read, write)
    graceful_shutdown_timeout_seconds: float = 30.0 # Grace period for workers to finish before hard cancel

    # Simple, optimal chunk size for all file transfers
    chunk_size_kb: int = 2048 # 2MB chunks - optimal for network transfers

    # Logging konfiguration
    log_level: str = "INFO"
    log_file_path: str = Field(
        default_factory=lambda: str(get_logs_dir() / "file_agent.log"),
        description="Path to log file"
    )
    log_retention_days: int = 30

    # Storage monitoring
    storage_check_interval_seconds: int = 30
    source_warning_threshold_gb: float = 10.0
    source_critical_threshold_gb: float = 5.0
    destination_warning_threshold_gb: float = 50.0
    destination_critical_threshold_gb: float = 20.0
    storage_test_file_prefix: str = ".file_agent_test_"
    storage_io_timeout_seconds: float = 5.0  # Per-operation I/O timeout for local paths
    storage_io_timeout_network_seconds: float = 10.0  # Per-operation I/O timeout for network/UNC paths
    storage_check_timeout_seconds: float = 30.0  # Outer timeout for entire storage check operation

    # Space management for file copying
    enable_pre_copy_space_check: bool = True
    copy_safety_margin_gb: float = 1.0 # Safety margin to prevent disk full
    space_retry_delay_seconds: int = 300 # 5 minutes between space retries
    max_space_retries: int = 6 # Max 30 minutes waiting for space
    minimum_free_space_after_copy_gb: float = 2.0 # Minimum space to leave after copy
    space_error_cooldown_minutes: int = (
        1 # Cooldown period for SPACE_ERROR files (minutes)
    )

    # File history management
    keep_files_hours: int = 336 # Keep ALL files in memory for 14 days (14*24=336 hours) - provides complete UI log

    # Growing file support (now default)
    growing_file_min_size_mb: int = 50 # Minimum size in MB to start growing copy
    growing_file_safety_margin_mb: int = 50 # Stay this many MB behind write head
    growing_file_poll_interval_seconds: int = 5 # Check file growth every N seconds
    growing_file_growth_timeout_seconds: int = (
        20 # Consider stable after N seconds no growth
    )
    growing_file_chunk_size_kb: int = 2048 # Chunk size for growing copy (2MB)
    growing_copy_pause_ms: int = 100 # Pause between growing copy cycles (throttling)

    # Resume functionality
    enable_secure_resume: bool = (
        True # Enable secure resume functionality for interrupted copies
    )

    # Parallel processing
    max_concurrent_copies: int = 7 # Maximum number of concurrent copy operations

    # Network mount configuration
    enable_auto_mount: bool = False # Enable automatic network mount attempts
    network_share_url: str = "" # Network share URL (e.g., smb://server/share)
    windows_drive_letter: str = "" # Windows drive letter (e.g., "Z") or empty for UNC
    macos_mount_point: str = "" # macOS mount point prefix (default: /Volumes)

    # Just In Engine integration
    justin_api_base_url: str = Field(
        default="http://localhost:8080",
        description="Base URL for Just In Engine API"
    )
    justin_fast_poll_interval_seconds: float = Field(
        default=3.0,
        description="Fast polling interval for recording status (seconds)"
    )
    justin_slow_poll_interval_seconds: float = Field(
        default=30.0,
        description="Slow polling interval for error checking (seconds)"
    )
    justin_api_timeout_seconds: float = Field(
        default=2.0,
        description="HTTP timeout for Just In API calls (seconds)"
    )
    justin_auto_stop_minutes: int = Field(
        default=0,
        description="Auto-stop all channels after N minutes of recording (0 = disabled)"
    )
    justin_auto_stop_warning_minutes: int = Field(
        default=5,
        description="Tally blinks N minutes before auto-stop limit is reached"
    )

    # Tally Light integration
    tally_light_switch_type: str = Field(
        default="ip_power_9255",
        description="Type of power switch (ip_power_9255, mock)"
    )
    tally_light_switch_ip: str = Field(
        default="10.65.77.9",
        description="IP address of the power switch"
    )
    tally_light_switch_username: str = Field(
        default="admin",
        description="Username for the power switch"
    )
    tally_light_switch_password: str = Field(
        default="",
        description="Password for the power switch"
    )
    tally_light_blink_interval_seconds: float = Field(
        default=0.5,
        description="Blink interval for tally light (seconds)"
    )
    tally_light_api_timeout_seconds: float = Field(
        default=2.0,
        description="HTTP timeout for Tally Light API calls (seconds)"
    )

    model_config = SettingsConfigDict(env_file=get_hostname_settings_file())

    @property
    def log_directory(self) -> Path:
        """Returnerer log directory som Path objekt"""
        return Path(self.log_file_path).parent

    @property
    def config_file_info(self) -> dict:
        """Return information about which configuration file is being used."""
        return {
            "hostname": get_hostname(),
            "active_config_file": get_hostname_settings_file(),
            "all_available_configs": list_all_settings_files(),
        }
