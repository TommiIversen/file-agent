from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    # Filstier
    source_directory: str
    destination_directory: str

    # Output folder template system
    output_folder_template_enabled: bool = False
    output_folder_rules: str = ""  # JSON string or simple rule format
    output_folder_default_category: str = "OTHER"
    output_folder_date_format: str = "filename[0:6]"  # Extract first 6 chars as date

    # Timing konfiguration
    file_stable_time_seconds: int = 120
    polling_interval_seconds: int = 10

    # Filkopiering
    use_temporary_file: bool = True
    max_retry_attempts: int = 3
    retry_delay_seconds: int = 10
    global_retry_delay_seconds: int = 60
    copy_progress_update_interval: int = (
        1  # Update progress every N percent (10 = every 10%)
    )

    # Chunk sizes for network copy optimization
    normal_file_chunk_size_kb: int = (
        1024  # 1MB chunks for normal files (network optimized)
    )
    large_file_chunk_size_kb: int = 2048  # 2MB chunks for files > 1GB
    large_file_threshold_gb: float = 1.0  # Files larger than this use large chunks

    # Logging konfiguration
    log_level: str = "INFO"
    log_file_path: str = "logs/file_agent.log"
    log_retention_days: int = 30
    log_max_size_mb: int = 100
    console_log_format: str = "colored"  # "colored" eller "simple"
    file_log_format: str = "json"  # "json" eller "simple"

    # Storage monitoring
    storage_check_interval_seconds: int = 60
    source_warning_threshold_gb: float = 10.0
    source_critical_threshold_gb: float = 5.0
    destination_warning_threshold_gb: float = 50.0
    destination_critical_threshold_gb: float = 20.0
    storage_test_file_prefix: str = ".file_agent_test_"

    # Space management for file copying
    enable_pre_copy_space_check: bool = True
    copy_safety_margin_gb: float = 1.0  # Safety margin to prevent disk full
    space_retry_delay_seconds: int = 300  # 5 minutes between space retries
    max_space_retries: int = 6  # Max 30 minutes waiting for space
    minimum_free_space_after_copy_gb: float = 2.0  # Minimum space to leave after copy

    # Completed file management
    keep_completed_files_hours: int = 24  # Keep completed files in memory for 24 hours
    max_completed_files_in_memory: int = 1000  # Max completed files to keep in memory

    # Growing file support
    enable_growing_file_support: bool = False  # Enable growing file copy support
    growing_file_min_size_mb: int = 100  # Minimum size in MB to start growing copy
    growing_file_safety_margin_mb: int = 50  # Stay this many MB behind write head
    growing_file_poll_interval_seconds: int = 5  # Check file growth every N seconds
    growing_file_growth_timeout_seconds: int = (
        30  # Consider stable after N seconds no growth
    )
    growing_file_chunk_size_kb: int = 2048  # Chunk size for growing copy (2MB)
    growing_copy_pause_ms: int = 100  # Pause between growing copy cycles (throttling)

    # Resume functionality
    enable_secure_resume: bool = (
        True  # Enable secure resume functionality for interrupted copies
    )
    resume_verification_mode: str = (
        "conservative"  # Resume mode: conservative, performance, or paranoid
    )
    resume_min_file_size_mb: int = 10  # Minimum file size for resume attempts (MB)
    resume_max_verification_mb: int = 100  # Maximum verification size for resume (MB)
    resume_timeout_seconds: int = 300  # Maximum time for resume verification (5 min)

    # Parallel processing
    max_concurrent_copies: int = 8  # Maximum number of concurrent copy operations

    # Network mount configuration
    enable_auto_mount: bool = False  # Enable automatic network mount attempts
    network_share_url: str = ""  # Network share URL (e.g., smb://server/share)
    windows_drive_letter: str = ""  # Windows drive letter (e.g., "Z") or empty for UNC
    macos_mount_point: str = ""  # macOS mount point prefix (default: /Volumes)

    model_config = SettingsConfigDict(env_file="settings.env")

    @property
    def log_directory(self) -> Path:
        """Returnerer log directory som Path objekt"""
        return Path(self.log_file_path).parent
