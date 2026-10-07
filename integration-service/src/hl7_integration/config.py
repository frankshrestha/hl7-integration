"""Service configuration, read from environment variables (or a local .env file)."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(default="postgresql://localhost:5432/hl7_int")
    database_pool_min_size: int = 1
    database_pool_max_size: int = 10

    http_host: str = "127.0.0.1"
    http_port: int = 8085

    local_application: str = "HL7_INT"
    local_facility: str = ""

    hl7_api_url: str = "http://localhost:8000/api/integrations/lab-results"
    hl7_api_timeout_seconds: float = 10.0
    hl7_int_client_id: str = "hl7-service"
    hl7_api_hmac_secret: SecretStr = SecretStr("")

    delivery_max_attempts: int = 12
    delivery_backoff_base_seconds: float = 5.0
    delivery_backoff_cap_seconds: float = 300.0
    delivery_lease_seconds: float = 60.0
    delivery_batch_size: int = 20
    delivery_poll_interval_seconds: float = 1.0

    batch_max_records: int = 300

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
