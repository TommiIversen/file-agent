from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    source_directory: str
    destination_directory: str

    model_config = SettingsConfigDict(env_file="settings.env")
