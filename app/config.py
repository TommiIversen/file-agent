from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    # Filstier
    source_directory: str
    destination_directory: str
    
    # Timing konfiguration
    file_stable_time_seconds: int = 120
    polling_interval_seconds: int = 10
    
    # Filkopiering
    use_temporary_file: bool = True
    max_retry_attempts: int = 3
    retry_delay_seconds: int = 10
    global_retry_delay_seconds: int = 60
    copy_progress_update_interval: int = 1  # Update progress every N percent (10 = every 10%)
    
    # Logging konfiguration
    log_level: str = "INFO"
    log_file_path: str = "logs/file_agent.log"
    log_retention_days: int = 30
    log_max_size_mb: int = 100
    console_log_format: str = "colored"  # "colored" eller "simple"
    file_log_format: str = "json"       # "json" eller "simple"
    
    # Storage monitoring
    storage_check_interval_seconds: int = 60
    source_warning_threshold_gb: float = 10.0
    source_critical_threshold_gb: float = 5.0
    destination_warning_threshold_gb: float = 50.0
    destination_critical_threshold_gb: float = 20.0
    storage_test_file_prefix: str = ".file_agent_test_"
    
    # Space management for file copying
    enable_pre_copy_space_check: bool = True
    copy_safety_margin_gb: float = 1.0          # Safety margin to prevent disk full
    space_retry_delay_seconds: int = 300        # 5 minutes between space retries  
    max_space_retries: int = 6                  # Max 30 minutes waiting for space
    minimum_free_space_after_copy_gb: float = 2.0  # Minimum space to leave after copy
    
    # Completed file management
    keep_completed_files_hours: int = 24        # Keep completed files in memory for 24 hours
    max_completed_files_in_memory: int = 1000   # Max completed files to keep in memory
    
    model_config = SettingsConfigDict(env_file="settings.env")
    
    @property
    def log_directory(self) -> Path:
        """Returnerer log directory som Path objekt"""
        return Path(self.log_file_path).parent
