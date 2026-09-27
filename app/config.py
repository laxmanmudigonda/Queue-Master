from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    api_key: str = Field(min_length=24)
    queue_key: str = "queuemaster:ready"
    lease_seconds: float = Field(default=15, ge=1)
    poll_seconds: float = Field(default=0.2, gt=0)
    scheduler_seconds: float = Field(default=1, gt=0)
    backoff_seconds: float = Field(default=2, gt=0)
    max_backoff_seconds: float = Field(default=60, gt=0)
    request_limit: int = 262144


settings = Settings()
