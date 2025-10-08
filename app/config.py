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
    
    # Logging konfiguration
    log_level: str = "INFO"
    log_file_path: str = "logs/file_agent.log"
    log_retention_days: int = 30
    log_max_size_mb: int = 100
    console_log_format: str = "colored"  # "colored" eller "simple"
    file_log_format: str = "json"       # "json" eller "simple"
    
    model_config = SettingsConfigDict(env_file="settings.env")
    
    @property
    def log_directory(self) -> Path:
        """Returnerer log directory som Path objekt"""
        return Path(self.log_file_path).parent
